"""Web application auto-filler — the agent that completes online job applications.

Uses Playwright (headless Chromium) to:
  1. Open the posting / apply link
  2. Follow the real application form (Workable, Greenhouse, Lever,
     SmartRecruiters, Teamtailor, BambooHR, or any standard form)
  3. Fill the candidate's details, paste the tailored letter, upload the CV PDF
  4. Tick consent boxes, and submit — or stop safely and screenshot when a
     human step (login / account creation / unknown required field) appears

Every run leaves a screenshot + step log in data/applications/job_<id>/. Login
sessions are kept in data/browser_profile/ so you sign into each platform in the
visible browser, rather than giving the Job Agent your password.
"""
import os
import re
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from agent.config import load_profile
PROFILE = load_profile()

ATS_MARKERS = {
    "workable": "apply.workable.com",
    "greenhouse": "greenhouse.io",
    "lever": "lever.co",
    "smartrecruiters": "smartrecruiters.com",
    "teamtailor": "teamtailor.com",
    "bamboohr": "bamboohr.com",
    "ashby": "ashbyhq.com",
}

FIELD_MAP = [
    # (matcher regex on label/placeholder/name/id, value function)
    (r"first[\s_-]?name|given[\s_-]?name", lambda p: p["name"].split()[0]),
    (r"last[\s_-]?name|surname|family[\s_-]?name", lambda p: " ".join(p["name"].split()[1:]) or p["name"].split()[0]),
    (r"full[\s_-]?name|^name$|your name|applicant name|sender[\s_-]?name", lambda p: p["name"]),
    (r"e-?mail", lambda p: p["email"]),
    (r"phone|mobile|cell|telephone|contact[\s_-]?number", lambda p: p["phone"]),
    (r"city|location|where.*(live|based)|residence|town", lambda p: p["location"]),
    (r"linkedin", lambda p: p.get("linkedin") or ""),
    (r"website|portfolio|github", lambda p: p.get("linkedin") or ""),
    (r"salary|expectation|compensation", lambda p: "Open to discussion"),
    (r"notice|start.*(date|availability)|available.*(from|start)", lambda p: "Immediately"),
    (r"how.*(hear|find)|source|referral", lambda p: "Job board"),
]

LETTER_HINTS = r"cover[\s_-]?letter|message|motivation|why.*you|additional.*(info|comment)|tell.*us|introduction|pitch|body|sell yourself"
CONSENT_HINTS = r"consent|agree|privacy|terms|gdpr|confirm|acknowledge"
CLOSED_MARKERS = (
    "job closed", "position closed", "applications are closed", "application closed",
    "no longer accepting applications", "no longer available", "position has been filled",
    "vacancy closed", "expired vacancy", "this advert has expired",
)


def _plain(md: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", md or "")
    t = re.sub(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)", r"\1", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    return t.strip()


class WebApplier:
    def __init__(self, headless=True, timeout=90, allow_human=False, human_wait=300,
                 review_wait=900, submit_automatically=False):
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        self._pw = sync_playwright
        self.headless = headless
        self.timeout = timeout
        self.allow_human = allow_human
        self.human_wait = human_wait
        self.review_wait = review_wait
        self.submit_automatically = submit_automatically
        self.steps = []
        self.extra = {}
        self.job_title = ""

    def log(self, msg):
        self.steps.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def run(self, job: dict, cv_pdf: str, letter_md: str, dry_run=False, extra_answers=None) -> dict:
        self.extra = {k.lower().strip(): (v or "").strip() for k, v in (extra_answers or {}).items() if k and (v or "").strip()}
        self.job_title = (job.get("title") or "").strip()
        out_dir = os.path.join(ROOT, "data", "applications", f"job_{job.get('id', 0)}")
        os.makedirs(out_dir, exist_ok=True)
        shot = os.path.join(out_dir, "web_proof.png")
        result = {"status": "failed", "screenshot": shot, "steps": self.steps, "url": job.get("apply_url")}

        with self._pw() as pw:
            # A persistent, local-only Chromium profile retains normal website
            # cookies after the user signs in. Passwords and MFA codes are typed
            # only into the employer/job-board page, never collected by us.
            profile_dir = os.path.join(ROOT, "data", "browser_profile")
            os.makedirs(profile_dir, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                profile_dir, headless=self.headless)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            try:
                page.goto(job.get("apply_url") or job.get("url"), wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                self.log(f"opened posting: {page.url[:90]}")

                # Security checks, CAPTCHAs and similar anti-bot screens are
                # never solved by the agent. In visible mode, leave the real
                # site open for the account owner to complete its check, then
                # resume only after it has cleared.
                if self._has_security_check(page):
                    if self.allow_human and not self.headless and self._wait_for_security_clear(page, shot):
                        self.log("portal security check completed by you — continuing")
                    else:
                        page.screenshot(path=shot, full_page=True)
                        self.log("SECURITY CHECK — waiting for a human browser step")
                        result.update(status="needs_security_check",
                                      detail="Fuzu or the portal showed a security check. Complete it yourself in the visible browser, then retry.")
                        return result

                if self._is_closed(page):
                    page.screenshot(path=shot, full_page=True)
                    self.log("posting reports that applications are closed")
                    result.update(status="closed", detail="The employer page says this vacancy is closed; no form was filled.")
                    return result

                # 1) If this is the job board page, find the real apply link
                target = self._find_apply_link(page)
                if target and target != page.url:
                    page.goto(target, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    self.log(f"followed apply link -> {page.url[:90]}")
                    if self._has_security_check(page):
                        if self.allow_human and not self.headless and self._wait_for_security_clear(page, shot):
                            self.log("portal security check completed by you — continuing")
                        else:
                            page.screenshot(path=shot, full_page=True)
                            result.update(status="needs_security_check",
                                          detail="The application portal showed a security check. Complete it yourself in the visible browser, then retry.")
                            return result
                    if self._is_closed(page):
                        page.screenshot(path=shot, full_page=True)
                        result.update(status="closed", detail="The employer page says this vacancy is closed; no form was filled.")
                        return result

                ats = next((k for k, m in ATS_MARKERS.items() if m in page.url), "generic")
                self.log(f"application form type: {ats}")

                # 1a) login-gated form? (e.g. myjobmag native apply box for members)
                meaningful_visible, hidden_apply = 0, 0
                for fr in self._all_frames(page):
                    try:
                        for el in fr.query_selector_all("input, textarea, select"):
                            try:
                                nm = " ".join(filter(None, [el.get_attribute("name") or "",
                                                            el.get_attribute("id") or ""])).lower()
                                if re.search(r"search|newsletter|subscribe|comment|^q$|^s$|csrf|token", nm):
                                    continue
                                itype = (el.get_attribute("type") or "").lower()
                                if itype in ("hidden", "submit", "button", "radio", "checkbox", "file"):
                                    continue
                                box = el.bounding_box()
                                if box and box["width"] > 0 and box["height"] > 0:
                                    meaningful_visible += 1
                                elif re.search(r"apply|sender|cover|resume|cv|applicant|job", nm):
                                    hidden_apply += 1
                            except Exception:
                                continue
                    except Exception:
                        continue
                if meaningful_visible == 0 and hidden_apply > 0:
                    if self.allow_human and not self.headless and self._wait_for_access(page, shot):
                        self.log("login completed by you — application form is now available")
                    else:
                        page.screenshot(path=shot, full_page=True)
                        self.log(f"login-gated form detected ({hidden_apply} hidden apply fields)")
                        result.update(status="needs_login",
                                      detail="This job board keeps its application form behind a member login. Use the visible browser to sign in, then retry this application.")
                        return result

                # 1b) no form at all on this page?
                n_fillable = sum(len(fr.query_selector_all("input:visible, textarea:visible, select:visible")) or 0
                                 for fr in self._all_frames(page))
                if n_fillable == 0 and self._needs_login(page) and self.allow_human and not self.headless:
                    if self._wait_for_access(page, shot):
                        self.log("login completed by you — application form is now available")
                        n_fillable = self._visible_form_count(page)
                if n_fillable == 0:
                    page.screenshot(path=shot, full_page=True)
                    self.log("no application form found on this page")
                    result.update(status="needs_form",
                                  detail="No application form on this page - the employer likely uses an external portal. "
                                         "Paste the direct application link on the job page and the agent will continue.")
                    return result

                # 2) login wall: leave authentication, MFA and CAPTCHA to you.
                if self._needs_login(page):
                    if self.allow_human and not self.headless and self._wait_for_access(page, shot):
                        self.log("login completed by you — continuing with the application")
                    else:
                        page.screenshot(path=shot, full_page=True)
                        self.log("LOGIN/ACCOUNT WALL — stopping safely for human step")
                        result.update(status="needs_login", detail="Portal requires a login — everything else is ready.")
                        return result

                # 3) fill across up to 4 pages / iframes
                submitted = False
                for _ in range(4):
                    missing = self._fill_page(page, letter_md, cv_pdf)
                    if self._needs_login(page):
                        break
                    if dry_run:
                        page.screenshot(path=shot, full_page=True)
                        self.log("DRY RUN — filled everything, not submitting")
                        result.update(status="filled", detail=f"Filled (dry run). Missing: {missing or 'none'}")
                        return result
                    if missing and self.allow_human and not self.headless:
                        # ---- TEAM MODE: window is open; wait for the user to fill
                        # the highlighted fields, then submit automatically ----
                        self.log(f"NEEDS YOU: {', '.join(missing)} — window left open, submit will happen automatically once you fill them")
                        self._highlight_missing(page)
                        try:
                            page.bring_to_front()
                        except Exception:
                            pass
                        deadline = time.time() + self.human_wait
                        while time.time() < deadline:
                            page.wait_for_timeout(3000)
                            missing = self._fill_page(page, letter_md, cv_pdf)  # re-fill/refresh
                            if not missing:
                                break
                        if not missing:
                            self.log("you completed the missing fields")
                        else:
                            page.screenshot(path=shot, full_page=True)
                            self.log("timed out waiting — parked for manual completion")
                            result.update(status="needs_review", missing=missing,
                                          detail=f"Still missing after waiting: {', '.join(missing)}")
                            return result
                    elif missing:
                        page.screenshot(path=shot, full_page=True)
                        self.log(f"required fields unfilled: {missing} — stopping for review")
                        result.update(status="needs_review", detail=f"Could not fill: {', '.join(missing)}", missing=missing)
                        return result
                    # Review lock: the agent never activates a button.  This
                    # includes Next/Continue because some portals submit from
                    # a deceptively named button. You stay in control.
                    page.screenshot(path=shot, full_page=True)
                    if self.allow_human and not self.headless:
                        submitted = self._wait_for_final_review(page, shot)
                    else:
                        self.log("review lock: form filled, no button was clicked")
                    break
                # final state
                page.screenshot(path=shot, full_page=True)
                if submitted:
                    self.log("SUBMITTED ✅")
                    result.update(status="submitted", detail="Application submitted on the website.")
                else:
                    result.update(status="needs_review", detail="Filled as far as possible — please review the screenshot.")
                return result
            except Exception as e:
                try:
                    page.screenshot(path=shot, full_page=True)
                except Exception:
                    pass
                self.log(f"ERROR: {type(e).__name__} {str(e)[:160]}")
                result.update(status="failed", detail=str(e)[:200])
                return result
            finally:
                context.close()

    # ---------------------------------------------------------------- helpers
    def _highlight_missing(self, page):
        """Outline every unfilled required field in red + scroll to the first one."""
        try:
            first = None
            for frame in self._all_frames(page):
                for inp in frame.query_selector_all("input:visible[required], textarea:visible[required], select:visible[required]"):
                    try:
                        v = inp.input_value() if inp.get_attribute("type") != "checkbox" else "checked"
                        if not v:
                            inp.evaluate("el => el.style.outline = '3px solid red'")
                            if first is None:
                                first = inp
                    except Exception:
                        continue
            if first is not None:
                first.scroll_into_view_if_needed()
                try:
                    first.focus()
                except Exception:
                    pass
        except Exception:
            pass

    def _visible_form_count(self, page) -> int:
        total = 0
        for frame in self._all_frames(page):
            try:
                total += len(frame.query_selector_all("input:visible, textarea:visible, select:visible"))
            except Exception:
                continue
        return total

    def _wait_for_access(self, page, shot) -> bool:
        """Keep the real portal open for login, MFA or CAPTCHA; never read secrets."""
        self.log("NEEDS YOU: sign in or complete the portal check in the visible browser")
        try:
            page.bring_to_front()
        except Exception:
            pass
        deadline = time.time() + self.human_wait
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            if not self._needs_login(page) and self._visible_form_count(page) > 0:
                return True
        page.screenshot(path=shot, full_page=True)
        self.log("timed out waiting for login or portal check")
        return False

    def _has_security_check(self, page) -> bool:
        """Recognize a challenge so it can be handed to the user, never bypassed."""
        try:
            text = page.content().lower()
            return bool(re.search(
                r"checking your browser|verify you are human|security check|captcha|"
                r"challenge-error-text|just a moment\.\.\.|cf-chl-|turnstile", text))
        except Exception:
            return False

    def _wait_for_security_clear(self, page, shot) -> bool:
        self.log("NEEDS YOU: complete the portal security check in the visible browser")
        try:
            page.bring_to_front()
        except Exception:
            pass
        deadline = time.time() + self.human_wait
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            if not self._has_security_check(page):
                return True
        page.screenshot(path=shot, full_page=True)
        self.log("timed out waiting for the portal security check")
        return False

    def _is_closed(self, page) -> bool:
        try:
            text = page.content().lower()
            return any(marker in text for marker in CLOSED_MARKERS)
        except Exception:
            return False

    def _application_submitted(self, page) -> bool:
        try:
            text = page.content().lower()
            return bool(re.search(r"application (has been )?(submitted|received)|thank you for (your )?application|successfully applied", text))
        except Exception:
            return False

    def _wait_for_final_review(self, page, shot) -> bool:
        minutes = max(1, round(self.review_wait / 60))
        self.log(f"READY FOR REVIEW: form filled; inspect it and click the website's final Submit button ({minutes} min window)")
        try:
            page.bring_to_front()
        except Exception:
            pass
        deadline = time.time() + self.review_wait
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if self._application_submitted(page):
                self.log("you submitted the application")
                return True
        page.screenshot(path=shot, full_page=True)
        self.log("review window ended — application was not submitted")
        return False

    def _find_apply_link(self, page):
        """On a job-board page, find the direct application link."""
        try:
            for a in page.query_selector_all("a[href]"):
                href = (a.get_attribute("href") or "")
                text = (a.inner_text() or "").strip().lower()
                if any(m in href for m in ATS_MARKERS.values()) or \
                   (href.startswith("http") and text in ("apply", "apply now", "apply here", "apply for this job")):
                    return href
        except Exception:
            pass
        return None

    def _needs_login(self, page) -> bool:
        try:
            html = page.content().lower()
            return bool(re.search(r"(sign[\s-]?in[\s-]?(to|with)|log[\s-]?in[\s-]?(to|with)?)|create[\s-]?an?[\s-]?account|password", html)) \
                and "password" in html and page.query_selector("input[type=password]") is not None
        except Exception:
            return False

    def _all_frames(self, page):
        return [page] + [f for f in page.frames if f is not page]

    def _fill_page(self, page, letter_md, cv_pdf) -> list:
        """Fill every recognizable field. Returns list of missing REQUIRED fields."""
        missing, filled = [], 0
        letter_text = _plain(letter_md)
        t = self.job_title
        t_words = t.split()
        if len(t_words) > 6:
            t = " ".join(t_words[:6])
        article = "an" if t[:1].lower() in "aeiou" else "a"
        subject_line = f"Application for the post of {article} {t}".strip()
        pref_locations = ["kitengela", "kajiado", "nairobi", "kenya"]
        for frame in self._all_frames(page):
            try:
                for inp in frame.query_selector_all("input:visible, textarea:visible"):
                    try:
                        itype = (inp.get_attribute("type") or "text").lower()
                        name = " ".join(filter(None, [
                            inp.get_attribute("name") or "", inp.get_attribute("id") or "",
                            inp.get_attribute("placeholder") or "",
                            (inp.get_attribute("aria-label") or ""),
                            self._label_text(frame, inp)])).lower()
                        if not name or re.search(r"search|newsletter|subscribe|comment|^q$|^s$|login|password|username", name):
                            continue
                        if itype in ("email",):
                            inp.fill(PROFILE["email"]); filled += 1
                        elif itype in ("tel",):
                            inp.fill(PROFILE["phone"]); filled += 1
                        elif itype == "file":
                            inp.set_input_files(cv_pdf)
                            self.log("uploaded CV PDF"); filled += 1
                        elif itype in ("text", ""):
                            val = None
                            if re.search(r"subject", name):
                                val = subject_line
                                self.log(f"set subject: {subject_line[:60]}")
                            for kw, ans in getattr(self, "extra", {}).items():
                                if kw and kw in name:
                                    val = ans
                                    self.log(f"used your manual answer for '{name[:40]}'")
                                    break
                            if not val:
                                val = next((fn(PROFILE) for pat, fn in FIELD_MAP
                                            if re.search(pat, name) and fn(PROFILE)), None)
                            if val:
                                inp.fill(val); filled += 1
                                if "name" in name and val == PROFILE["name"]:
                                    pass
                        elif itype == "checkbox":
                            if re.search(CONSENT_HINTS, name):
                                inp.check(); filled += 1
                            elif inp.get_attribute("required"):
                                inp.check(); filled += 1
                    except Exception:
                        continue
                for ta in frame.query_selector_all("textarea:visible"):
                    try:
                        name = " ".join(filter(None, [
                            ta.get_attribute("name") or "", ta.get_attribute("id") or "",
                            ta.get_attribute("placeholder") or "",
                            self._label_text(frame, ta)])).lower()
                        if name and re.search(LETTER_HINTS, name):
                            ta.fill(letter_text[:5000])
                            self.log("pasted tailored application letter"); filled += 1
                    except Exception:
                        continue
                try:
                    for fi in frame.query_selector_all("input[type=file]"):
                        try:
                            fi.set_input_files(cv_pdf)
                            self.log("uploaded CV PDF")
                            filled += 1
                        except Exception:
                            continue
                except Exception:
                    pass
                for sel_el in frame.query_selector_all("select:visible"):
                    try:
                        sname = (sel_el.get_attribute("name") or sel_el.get_attribute("id") or "").lower()
                        opts = [o.inner_text().strip() for o in sel_el.query_selector_all("option") if o.inner_text().strip()]
                        if not opts:
                            continue
                        choice = next((o for pref in pref_locations for o in opts
                                       if pref == o.lower() or pref in o.lower()), None)
                        if choice is None and sname and re.search(r"location|county|city|town", sname):
                            choice = opts[0] if opts[0].lower() not in ("select", "choose", "") else (opts[1] if len(opts) > 1 else None)
                        if choice is not None:
                            sel_el.select_option(label=choice)
                            self.log(f"selected '{choice}' in {sname or 'dropdown'}"); filled += 1
                        elif sel_el.get_attribute("required"):
                            missing.append(sname or "dropdown")
                    except Exception:
                        continue
            except Exception:
                continue
        self.log(f"filled {filled} field(s)")
        # missing required?
        for frame in self._all_frames(page):
            try:
                for inp in frame.query_selector_all("input:visible[required], textarea:visible[required], select:visible[required]"):
                    try:
                        v = inp.input_value() if inp.get_attribute("type") != "checkbox" else "checked"
                        if not v:
                            missing.append((inp.get_attribute("name") or inp.get_attribute("id") or "?")[:30])
                    except Exception:
                        pass
            except Exception:
                continue
        return missing

    def _label_text(self, frame, el) -> str:
        try:
            el_id = el.get_attribute("id")
            if el_id:
                lab = frame.query_selector(f"label[for='{el_id}']")
                if lab:
                    return lab.inner_text() or ""
            return ""
        except Exception:
            return ""

    def _click_next_or_submit(self, page, allow_submit=False):
        for text in ("submit application", "submit application:",
                     "apply", "submit", "send application", "next", "continue"):
            for frame in self._all_frames(page):
                try:
                    for btn in frame.query_selector_all("button:visible, input[type=submit]:visible"):
                        label = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
                        is_final = "submit" in text or text == "apply" or "send" in text
                        if is_final and not allow_submit:
                            continue
                        if label == text or (text in label and len(label) < 34):
                            btn.click()
                            self.log(f"clicked '{label or text}'")
                            return "submitted" if is_final else "next"
                except Exception:
                    continue
        return "none"
