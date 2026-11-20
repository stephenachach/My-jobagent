"""Draft generator: tailored CV + cover letter per job, in the candidate's style.

Two engines:
  1. Template engine (default): mirrors the structure and voice of the candidate's
     real CV and application letter. Skills are reordered per the job
     description; only real experience is ever used.
  2. AI engine: if settings.llm.api_key is set, Gemini/OpenAI rewrites the
     documents using the same style guide — smarter wording, same facts.
"""
import json
import os
import re
from typing import Optional

import yaml

from agent.config import load_settings, load_profile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = load_profile()      # kept for backwards compatibility
SETTINGS = load_settings()    # kept for backwards compatibility
last_ai_error = ""            # surfaced by check_ai.py / dashboard header
last_engine = ""              # "ai" or "template", for the dashboard label

WORD = re.compile(r"\b[a-z][a-z+#./]*\b")
STOP = {"at", "in", "of", "to", "and", "for", "with", "the", "a", "an", "is", "your", "our"}

# strip vacancy counts etc. from titles when used in sentences: "ICT Support Intern -35 Posts"
NOISE_RE = re.compile(r"\s*[-–(]?\s*\d+\s*(posts?|positions?|vacanc\w*)\s*[)]?", re.I)


def clean_title(t: str) -> str:
    return NOISE_RE.sub("", (t or "")).strip(" -,")


# complementary job titles per focus — used for the role-title line under the name
COMPLEMENT = {
    "support": ("ICT Support Technician", "ICT Officer"),
    "administrator": ("Systems Administrator", "Network Administrator"),
    "developer": ("Software Developer", "Web Developer"),
    "data": ("Data Analyst", "Data Officer"),
    "analyst": ("Business Analyst", "ICT Officer"),
    "default": ("ICT Officer", "IT Graduate"),
}


def role_titles(job: dict) -> str:
    """e.g. 'Data Analyst Intern, Data Officer' — the line HR reads right under the name."""
    t = clean_title(job.get("title", ""))
    t = re.sub(r"\([^)]*\)", "", t)                     # drop parentheticals
    # take the short first segment when the title uses dashes
    for sep in ("–", " - ", " — "):
        if sep in t:
            head = t.split(sep)[0].strip()
            if len(head.split()) >= 2:
                t = head
                break
    words = t.split()
    if len(words) > 6:
        t = " ".join(words[:6]).rstrip(" &").strip()
    primary = t.strip(" -,")
    c1, c2 = COMPLEMENT.get(_focus(job), COMPLEMENT["default"])
    pw = _words(primary)

    def redundant(comp: str) -> bool:
        cw = _words(comp)
        shared = cw & pw
        return len(shared) >= 2 or (comp.split()[-1].lower() in pw if comp.split() else False)

    pick = c2 if redundant(c1) else c1
    if redundant(pick):
        pick = ""
    return ", ".join([p for p in (primary, pick) if p])


FOCUS_RULES = [
    ("developer", {"developer", "programmer", "software", "web", "application", "fullstack", "full-stack", "php", "python", "java"}),
    ("data", {"data", "analytics", "statistics", "statistical", "insights", "reporting", "collection"}),
    ("analyst", {"business", "analyst", "systems", "analysis", "requirements", "process"}),
    ("administrator", {"administrator", "administration", "network", "networking", "server", "sysadmin", "infrastructure"}),
    ("support", {"support", "helpdesk", "help", "desk", "technician", "ict", "it", "customer", "service", "assistant"}),
]


def _words(text: str) -> set:
    return {w for w in WORD.findall((text or "").lower()) if len(w) >= 2 and w not in STOP}


def _focus(job: dict) -> str:
    w = _words(f"{job.get('title','')} {job.get('description','')[:1500]}")
    best, best_hits = "default", 0
    for name, kws in FOCUS_RULES:
        hits = len(w & kws)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


FOCUS_SKILL_WORDS = {
    "developer": {"php", "mysql", "html", "css", "javascript", "bootstrap", "web", "development", "application", "flask", "python", "api", "netlify"},
    "data": {"excel", "formulas", "pivottables", "data", "reporting", "collection", "accuracy", "mysql", "workspace", "database", "intelligence", "analysis", "analytics", "sql", "dashboards"},
    "analyst": {"documentation", "guides", "rollouts", "onboarding", "reports", "reporting", "excel", "mysql", "analysis", "systems", "design", "business", "intelligence", "dashboards"},
    "administrator": {"installation", "configuration", "upgrades", "patches", "antivirus", "network", "devices", "printers", "administration"},
    "support": {"support", "troubleshooting", "computers", "printers", "software", "devices", "training", "coaching", "helpdesk", "ict"},
}

# The PROFILE always opens with the skills that match THIS vacancy. Every line
# below uses only facts already present in the real MASTER PROFILE.
FOCUS_OPENING = {
    "support": ("My ICT support skills cover first line troubleshooting of computers, printers "
                "and software, installing and configuring devices, system rollouts, user "
                "onboarding and user guides written in plain language."),
    "administrator": ("My systems administration skills cover installation, configuration and "
                      "upgrades, software updates, patches and antivirus management, network "
                      "administration and user onboarding."),
    "developer": ("My development skills cover Python and Flask, PHP 8 and MySQL, responsive "
                  "HTML, CSS and JavaScript, REST APIs and Netlify deployment."),
    "data": ("My data and analysis skills cover Excel formulas and PivotTables, database "
             "management, business intelligence, accurate field data collection and reporting."),
    "analyst": ("My business analysis skills cover system analysis and design, database "
                "management, business intelligence, reporting dashboards and clear technical "
                "documentation."),
    "default": ("My business technology skills cover ICT support, system rollouts, "
                "documentation, database work and web development."),
}


def _ordered_skills(job: dict, profile: dict) -> list:
    """the candidate's technical skills, best-matching-first for this job.
    Score = fraction of the bullet's words that appear in the job posting
    (so short precise bullets beat long generic ones) + focus bonus."""
    text = _words(f"{job.get('title','')} {job.get('description','')}")
    focus = _focus(job)
    bonus_kw = FOCUS_SKILL_WORDS.get(focus, set())
    tech = profile.get("skills_technical", [])
    def score(skill):
        sw = _words(skill)
        if not sw:
            return 0.0
        ratio = len(sw & text) / len(sw)
        bonus = 0.45 if (sw & bonus_kw) else 0.0
        return ratio + bonus
    ranked = sorted(tech, key=score, reverse=True)
    # Job-matched skills always lead the SKILLS section, then the rest follow.
    focused, rest = [], []
    for skill in ranked:
        (focused if (_words(skill) & bonus_kw) else rest).append(skill)
    return focused + rest


# --------------------------------------------------------------------------
# Template engine — CV mirrors the candidate's real CV structure
# --------------------------------------------------------------------------
def _placeholder_project(title) -> bool:
    """Skip example/placeholder project entries so they never reach a real CV."""
    t = str(title or "").strip().upper()
    return (not t) or t.startswith("ADD YOUR") or "REPLACE" in t or t.startswith("PROJECT ")


def _plain_sentences(items):
    out = []
    for x in items or []:
        t = str(x).strip()
        if not t:
            continue
        if not t.endswith((".", "!", "?")):
            t += "."
        out.append(t)
    return out


def _paragraph(items):
    return " ".join(_plain_sentences(items))


def _dot(text):
    """Give a plain prose line a full stop, but never touch headings or URLs."""
    t = str(text).strip()
    if not t or "http" in t:
        return t
    return t if t.endswith((".", "!", "?")) else t + "."


def _bullets(items):
    """Round dot bullets for sections that hold several separate sentences."""
    out = []
    for x in items or []:
        t = _dot(str(x).strip())
        if t:
            out.append("• " + t)
    return "\n".join(out)


def template_cv(job: dict, profile: dict) -> str:
    """Professional CV: bold plain headings, dot bullets, job-matched opening."""
    p = profile or {}
    projects = [pr for pr in (p.get("projects") or [])
                if isinstance(pr, dict) and not _placeholder_project(pr.get("title"))]
    focus = _focus(job)
    tech = _ordered_skills(job, p)
    # The project portfolio sentence is a closing summary, not a lead skill.
    tech = ([t for t in tech if "I have applied these skills" not in t]
            + [t for t in tech if "I have applied these skills" in t])
    people = p.get("skills_people", []) or []
    role = clean_title(job.get("title", ""))
    company = (job.get("company") or "").strip()

    opening = FOCUS_OPENING.get(focus, FOCUS_OPENING["default"])
    summary = " ".join(str(p.get("career_summary") or "").split()).strip()
    closing = (f"I am applying for the {role} position"
               + (f" at {company}" if company else "")
               + " because I want to contribute from day one and grow with the organisation.")
    profile_para = " ".join(x for x in (opening, summary, closing) if x).strip()

    def exp_block(x):
        head = ", ".join(str(x.get(k, "")).strip() for k in ("title", "org", "period")
                         if str(x.get(k, "")).strip())
        return head + "\n" + _bullets(x.get("bullets", []))

    exps = sorted(p.get("experience", []) or [],
                  key=lambda x: 0 if focus in (x.get("tags") or []) else 1)
    exp_md = "\n\n".join(exp_block(x) for x in exps)

    proj = p.get("academic_project") or {}
    proj_md = ""
    if proj and not _placeholder_project(proj.get("title")):
        head = str(proj.get("title", "")).strip()
        period = str(proj.get("period", "")).strip()
        if period:
            head += ", " + period
        proj_md = head + "\n" + _bullets(proj.get("bullets", []))

    projects_md = ""
    for pr in projects:
        head = str(pr.get("title", "")).strip()
        period = str(pr.get("period", "")).strip()
        if period:
            head += ", " + period
        lines = [head]
        if pr.get("tech"):
            lines.append(_dot("Built with " + str(pr["tech"]).strip()))
        if pr.get("link"):
            lines.append(str(pr.get("link_label") or "Link").strip() + ": " + str(pr["link"]).strip())
        if pr.get("link2"):
            lines.append(str(pr.get("link2_label") or "More").strip() + ": " + str(pr["link2"]).strip())
        lines.append(_bullets(pr.get("bullets", [])))
        projects_md += "\n".join(lines) + "\n\n"
    projects_md = projects_md.strip()

    edu_list = p.get("education") or []
    edu = edu_list[0] if edu_list and isinstance(edu_list[0], dict) else {}
    edu_md = ""
    if edu:
        edu_md = (f"{edu.get('degree','')} at {edu.get('institution','')}\n"
                  f"{edu.get('period','')}\n{edu.get('detail','')}").strip()

    refs_md = ""
    for r in (p.get("references") or []):
        if not isinstance(r, dict):
            continue
        company_name = str(r.get("company", "")).strip().upper()
        refs_md += "\n".join(x for x in (company_name,
                                        str(r.get("person", "")).strip(),
                                        str(r.get("role", "")).strip(),
                                        str(r.get("phone", "")).strip()) if x) + "\n\n"
    refs_md += "More references available on request."

    additional = _bullets(p.get("additional_info") or [])

    blocks = [
        str(p.get("name", "Candidate")).strip(),
        role_titles(job),
        str(p.get("location", "")).strip(),
        str(p.get("phone", "")).strip(),
        str(p.get("email", "")).strip(),
        "", "PROFILE", profile_para,
        "", "SKILLS", "Technical", _bullets(tech),
        "", "People and Communication", _bullets(people),
        "", "EXPERIENCE", exp_md,
    ]
    if edu_md:
        blocks += ["", "EDUCATION", edu_md]
    if proj_md:
        blocks += ["", "ACADEMIC PROJECT", proj_md]
    if projects_md:
        blocks += ["", "SELECTED PROJECTS", projects_md]
    blocks += ["", "ADDITIONAL INFORMATION", additional,
               "", "REFERENCES", refs_md]
    return "\n".join(blocks) + "\n"


def template_letter(job: dict, profile: dict) -> str:
    import time as _t
    p = profile
    role = clean_title(job.get("title", ""))
    company = (job.get("company") or "your organisation").strip()
    focus = _focus(job)
    co_short = company.split(" - ")[0].split(" – ")[0]

    emphasis = {
        "support": ("At Kenya Meat Commission I worked on the ICT helpdesk, troubleshooting computers, "
                    "printers and software, installing and configuring devices, and helping staff adopt "
                    "new systems like Zoho CRM through training and simple user guides."),
        "administrator": ("At Kenya Meat Commission I worked alongside the ICT team on system rollouts, "
                          "network improvements, software updates, patches and antivirus protection, and "
                          "installed, configured and upgraded computers, printers and peripheral devices."),
        "developer": ("For my final year project at The East African University I built a web based "
                      "attachment management system with a reporting dashboard using PHP, MySQL, HTML, CSS, "
                      "JavaScript and Bootstrap, and I continue to build for small businesses as a freelance designer."),
        "data": ("As a Data Collection Officer at Polytrack Company I collected and verified field data "
                 "for company projects, handling people's information with care and accuracy, and I am "
                 "confident with Excel formulas and PivotTables from my business intelligence coursework."),
        "analyst": ("At Kenya Meat Commission I supported the Zoho CRM rollout through system configuration, "
                    "user onboarding and user guides written in simple language, and my degree covered "
                    "system analysis and design, database management and business intelligence."),
    }.get(focus, ("At Kenya Meat Commission I worked on the ICT helpdesk, troubleshooting computers, "
                  "printers and software, installing and configuring devices, and helping staff adopt "
                  "new systems like Zoho CRM through training and simple user guides."))

    people_line = ("Earlier I led and trained a small sales team at Global Internet Fortunes, where I "
                   "learned to communicate clearly, handle questions and objections, and keep people "
                   "motivated.")

    projects_line = ("Since graduating I have also built a Python and Flask job application agent, "
                     "a multi tenant PHP and MySQL chama management system with M-Pesa billing, and "
                     "responsive restaurant websites deployed on Netlify. These projects strengthened "
                     "my troubleshooting, database and web development skills, and I would bring that "
                     "practical experience to your team.")

    date_str = _t.strftime("%d %B %Y")
    re_line = f"RE: APPLICATION FOR THE POSITION OF {role.upper()}"

    return f"""{p['name']}
{p['location']}   {p['phone']}
{p['email']}

{date_str}

Dear Sir or Madam,

{re_line}

I graduated with a Bachelor of Business Information Technology from The East African University in 2026, and I am based in Kitengela and available to start work immediately. I am writing to apply for the {role} position at {co_short}. Having read the requirements, I believe my practical background in ICT support, systems and business technology fits what you are looking for.

My experience is practical and hands on. {emphasis} {people_line}

{projects_line}

I am reliable, quick to learn and easy to work with, and I take pride in doing things properly. I am comfortable with technology, with people and with paperwork, and I am willing to start at any level and grow with the organisation.

I have attached my curriculum vitae, which includes my references. I would be grateful for the opportunity to meet you briefly and to discuss how I can contribute as your {role}. Thank you for your time and consideration.

Yours faithfully,
{p['name']}
{p['phone']}
{p['email']}
"""


# --------------------------------------------------------------------------
# AI engine
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Final cleanup: strip any AI-looking punctuation from either engine.
# Real URLs and real product names such as M-Pesa are preserved.
# --------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s)\]}>]+")


def humanize(text: str) -> str:
    s = str(text or "")
    urls = []

    def stash(m):
        urls.append(m.group(0))
        return f"\x00URL{len(urls) - 1}\x00"

    s = _URL_RE.sub(stash, s)
    s = re.sub(r"\[([^\]]+)\]\((\x00URL\d+\x00)\)", r"\1, \2", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    # Machine-looking list markers become one clean round dot. Real dot bullets
    # are preserved; hyphens inside words, M-Pesa and URLs are untouched.
    s = re.sub(r"(?m)^\s*[-*+–—]\s+", "• ", s)
    s = s.replace("[", "").replace("]", "")
    s = s.replace("(", "").replace(")", "")
    s = s.replace("|", " and ")
    s = s.replace("—", ", ").replace("–", ", ")
    s = s.replace("Technologies:", "Built with")
    s = s.replace("Project portfolio:", "I have also built")
    s = s.replace("Selected projects:", "My projects include")
    s = s.replace("Applied these skills in", "I have applied these skills in")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" *, *", ", ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # Restore URLs BEFORE dotting bullets, so a link never gets a trailing stop.
    for i, u in enumerate(urls):
        s = s.replace(f"\x00URL{i}\x00", u)
    lines = []
    for line in s.split("\n"):
        t = line.strip()
        if t.startswith("• ") and "http" not in t and not t.endswith((".", "!", "?")):
            t += "."
        lines.append(t)
    s = "\n".join(lines)
    return s.strip() + "\n"


STYLE_GUIDE = """STYLE GUIDE - the goal is a document that reads as if this candidate
wrote it by hand, laid out like the best professional CV a hiring manager would
not ignore. Recruiters must not suspect a machine or a template.

Write PLAIN TEXT ONLY. No markdown hashes, no asterisks, no hyphens used as
bullets, no square brackets, no decorative round brackets, no pipes, no em
dashes, no en dashes, no backticks, no arrows, no emoji and no section rules.
Section headings are short words in capital letters on their own line. The
renderer makes headings and subheadings bold and leaves generous space between
a heading and the paragraph or bullets below it. Real URLs stay on their own
line after a simple label such as Code, Portfolio or Live demo. Keep real
product names such as M-Pesa exactly as written; do not add or remove hyphens
inside a real name or a URL.

Where a section holds several separate sentences, put each on its own line
starting with a single round dot and a space, and ending with a full stop.
Use these dot bullets under SKILLS, EXPERIENCE, ACADEMIC PROJECT, SELECTED
PROJECTS and ADDITIONAL INFORMATION. Keep PROFILE and the application letter
as flowing paragraphs with no bullets.

CV structure in this order:
NAME / ROLE TITLE LINE / town / phone / email / PROFILE / SKILLS with the
subheadings Technical and People and Communication / EXPERIENCE / EDUCATION /
ACADEMIC PROJECT / SELECTED PROJECTS / ADDITIONAL INFORMATION / REFERENCES.

The ROLE TITLE LINE sits directly under the name and lists two or three comma
separated job titles that mirror THIS job, so HR sees the fit instantly.

Writing rules:
- The PROFILE is ONE plain paragraph of at most five sentences and MUST OPEN
  with one sentence naming the real skills from MASTER PROFILE that best match
  THIS job. For a data or analytics vacancy, open with Excel, PivotTables,
  databases, business intelligence, accurate data collection and reporting.
  Then state the 2026 graduation, the real internship or experience, the real
  projects, and finally the target role sentence. Never open with the degree
  when the job is asking for skills.
- Use the candidate's REAL phrasing wherever it fits. Factual, modest verbs:
  Supported, Carried out, Installed, Trained. No inflated claims.
- Reorder the SKILLS bullets so the ones this posting mentions come FIRST, and
  let them flow naturally into the rest.
- FORBIDDEN AI tells: leverage, passionate, dynamic, spearheaded, seamlessly,
  cutting edge, robust, innovative, excited to, proven track record, aligned
  with, delve, exclamation marks, emoji, and any meta text like Tailored for.
- Do NOT invent or inflate: no new employers, dates, tools, certifications,
  grades or responsibilities. Only his real experience from MASTER PROFILE.
- The candidate HAS NOW GRADUATED. Never say awaiting graduation, coursework
  completed, expected to graduate or final year student.
- SELECTED PROJECTS uses ONLY the real entries in MASTER PROFILE. Each project
  starts with its name and year on one line, then a Built with line, then the
  Code, Portfolio or Live demo lines, then dot bullets describing what he
  built. Never invent a project, tool, date, URL or outcome.
- REFERENCES: company name in capitals, then referee name, role and phone on
  separate lines, repeated per referee, ending with
  More references available on request. Never invent a referee.
- LETTER: starts Dear Sir or Madam, then a plain RE line, then the body under
  300 words, mentions one or two real experiences that best match THIS
  posting, closes Yours faithfully, and contains no lists at all.

Return STRICT JSON with cv_md and letter_md only. Both values must be plain
text with no markdown characters.
"""


SYSTEM_PROMPT = """You are a careful CV writer imitating ONE specific candidate's own writing
style so the result reads like he wrote it himself. Given a JOB posting and his
MASTER PROFILE (his real CV), produce: (1) his CV tailored to the job, (2) his
application letter. Follow the STYLE GUIDE exactly. Use ONLY facts from the
MASTER PROFILE — never invent anything. Years of experience requested are NOT a
disqualifier. Return STRICT JSON: {"cv_md": "...", "letter_md": "..."}."""


def _llm_prompt(job: dict, profile: dict) -> str:
    return (STYLE_GUIDE + "\n\nJOB POSTING:\n" + json.dumps(
        {k: (v[:3500] if isinstance(v, str) else v) for k, v in job.items() if k in
         ("title", "company", "location", "description", "salary")},
        ensure_ascii=False) + "\n\nMASTER PROFILE:\n" + json.dumps(profile, ensure_ascii=False))


def _explain_http_error(status: int, body: str) -> str:
    """Turn Google's error JSON into one line a human can act on."""
    reason = ""
    try:
        err = (json.loads(body or "{}") or {}).get("error") or {}
        reason = " ".join(str(err.get(k) or "") for k in ("status", "message")).strip()
        for d in (err.get("details") or []):
            if isinstance(d, dict) and d.get("reason"):
                reason += " " + str(d["reason"])
    except Exception:
        reason = (body or "")[:200]
    low = reason.lower()
    if "api key not valid" in low or "api_key_invalid" in low or "invalid_argument" in low:
        return ("API key rejected. Copy the key again from aistudio.google.com/apikey, "
                "paste it with no spaces or quotes, and make sure Generative Language API "
                "is enabled for that key. " + reason)[:300]
    if "quota" in low or "rate" in low or "resource_exhausted" in low:
        return ("Quota or rate limit reached on this key. Wait a minute, or check the "
                "free-tier limits in Google AI Studio. " + reason)[:300]
    if "location is not supported" in low or "user location" in low or "failed_precondition" in low:
        return ("Google is refusing the request because of your region or network. Use a "
                "connection and Google account from a supported country, and remove any VPN or "
                "proxy, then try again. " + reason)[:300]
    if "not found" in low or "not supported" in low:
        return ("This model name is not available to your key. Try setting "
                "llm.model to gemini-3.5-flash or gemini-flash-latest in "
                "config/settings.yaml. " + reason)[:300]
    if "permission" in low or "forbidden" in low or "denied" in low:
        return ("This key is not allowed to use the Generative Language API. Create a key "
                "in Google AI Studio or enable the API for the project. " + reason)[:300]
    return (reason or f"HTTP {status}")[:300]


def _gemini_payload(prompt: str) -> dict:
    return {"contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.4}}


def _call_gemini(prompt: str) -> str:
    import requests
    llm = load_settings().get("llm") or {}
    key = llm.get("api_key")
    model = llm.get("model") or "gemini-3.8-flash"
    # Gemini 3.x Flash models are "thinking" models: without a generous
    # maxOutputTokens the whole budget can go to reasoning tokens and the
    # response comes back with no text at all.
    def ask(name):
        return requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent",
            headers={"x-goog-api-key": key},
            json=_gemini_payload(prompt), timeout=120)

    r = ask(model)
    if r.status_code in (404, 400) and model != "gemini-flash-latest":
        # The configured model may have been retired. Try the moving alias once.
        alt = ask("gemini-flash-latest")
        if alt.status_code == 200:
            r = alt
    if r.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {_explain_http_error(r.status_code, r.text)}")
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemini returned no text ({exc}); try a larger maxOutputTokens") from exc
    if not text.strip():
        raise RuntimeError("Gemini returned an empty response")
    return text


def _call_openai(prompt: str) -> str:
    import requests
    s = load_settings().get("llm") or {}
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {s.get('api_key','')}"},
        json={"model": s.get("model", "gpt-4o-mini"),
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": prompt}],
              "temperature": 0.4},
        timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ai_available() -> bool:
    llm = load_settings().get("llm") or {}
    key = str(llm.get("api_key") or "").strip()
    return bool(key) and llm.get("provider") in ("gemini", "openai")


def ai_status() -> dict:
    llm = load_settings().get("llm") or {}
    return {"available": ai_available(),
            "provider": llm.get("provider") or "none",
            "model": llm.get("model") or "",
            "last_error": last_ai_error,
            "last_engine": last_engine}


def generate(job: dict) -> dict:
    "Returns {cv_md, letter_md, engine} using AI if configured, else template."
    global last_ai_error
    profile = load_profile()
    if ai_available():
        try:
            provider = (load_settings().get("llm") or {}).get("provider")
            raw = _call_gemini(_llm_prompt(job, profile)) if provider == "gemini" \
                else _call_openai(_llm_prompt(job, profile))
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                parsed = json.loads(m.group(0))
                if parsed.get("cv_md") and parsed.get("letter_md"):
                    global last_engine
                    last_ai_error = ""
                    last_engine = "ai"
                    return {"cv_md": humanize(parsed["cv_md"]), "letter_md": humanize(parsed["letter_md"]),
                            "engine": "ai"}
            last_ai_error = "AI reply had no valid cv_md/letter_md JSON"
        except Exception as exc:
            last_ai_error = f"{type(exc).__name__}: {exc}"
        print(f"[ai] using template engine: {last_ai_error}", flush=True)
    last_engine = "template"
    return {"cv_md": humanize(template_cv(job, profile)), "letter_md": humanize(template_letter(job, profile)),
            "engine": "template"}
