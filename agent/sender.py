"""Sending applications + email notifications.

Activated when settings.yaml -> email is configured (it now is).
Flow: approve in dashboard -> if the posting has an email -> send CV + letter
PDFs -> mark sent -> notify the configured address.
"""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage

import yaml

from . import cvpdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from agent.config import load_settings, load_profile
APPS_DIR = os.path.join(ROOT, "data", "applications")


def _cfg() -> dict:
    """Always read current settings so env vars / edits work without a restart."""
    return load_settings()


def email_configured() -> bool:
    e = _cfg().get("email") or {}
    return bool(e.get("username") and e.get("app_password"))


def _smtp():
    e = _cfg()["email"]
    s = smtplib.SMTP(e["smtp_host"], e["smtp_port"], timeout=30)
    s.starttls(context=ssl.create_default_context())
    s.login(e["username"], e["app_password"])
    return s


def _safe_name(t: str) -> re.sub:
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")[:60]


def send_application(job: dict, cv_md: str, letter_md: str) -> dict:
    """Send one approved application: letter as body + CV & letter PDFs attached."""
    if not job.get("apply_email"):
        return {"ok": False, "detail": "No email address on the posting — apply via the link instead."}
    if not email_configured():
        return {"ok": False, "detail": "SMTP not configured in settings.yaml"}

    name = load_profile()["name"]
    role = re.sub(r"\s*[-–(]?\s*\d+\s*(posts?|positions?|vacanc\w*)\s*[)]?", "", job["title"], flags=re.I).strip(" -,")

    out = os.path.join(APPS_DIR, f"job_{job.get('id', 0)}_{_safe_name(role)}")
    cv_pdf = cvpdf.md_to_pdf(cv_md, os.path.join(out, f"{name} - CV.pdf"))
    letter_pdf = cvpdf.md_to_pdf(letter_md, os.path.join(out, f"{name} - Application Letter.pdf"))

    msg = EmailMessage()
    msg["Subject"] = f"APPLICATION: {role} — {name}"
    msg["From"] = f"{_cfg()['email'].get('from_name', name)} <{_cfg()['email']['username']}>"
    msg["To"] = job["apply_email"]
    # Optional visible copy. Leave application_cc blank when the employer
    # should not see the copied address.
    cc = (_cfg()["email"].get("application_cc") or "").strip()
    if cc:
        msg["Cc"] = cc
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", letter_md)
    msg.set_content(plain)
    msg.add_alternative(
        f'<html><body style="font-family:Georgia,serif;line-height:1.6;color:#222">'
        f'<pre style="white-space:pre-wrap;font-family:Georgia,serif;font-size:15px">{plain}</pre>'
        f"</body></html>", subtype="html")
    for path in (cv_pdf, letter_pdf):
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=os.path.basename(path))
    try:
        with _smtp() as s:
            s.send_message(msg)
        sent_at = __import__("time").strftime("%d %b %Y %H:%M")
        detail = (f"Emailed from {_cfg()['email']['username']} to {job['apply_email']} at {sent_at}"
                  + (f" (Cc: {cc})" if cc else ""))
        return {"ok": True, "detail": detail, "files": [cv_pdf, letter_pdf]}
    except Exception as ex:
        return {"ok": False, "detail": f"SMTP error: {ex}"}


def send_notification(subject: str, body: str) -> bool:
    """Email the configured notification address."""
    to = _cfg().get("notify", {}).get("email_to")
    if not to or not email_configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _cfg()["email"]["username"]
    msg["To"] = to
    msg.set_content(body)
    try:
        with _smtp() as s:
            s.send_message(msg)
        return True
    except Exception:
        return False


def notify_applied(job: dict, detail: str = "") -> bool:
    base = _cfg().get("schedule", {}).get("base_url") or ""
    link = f"\n  Open in dashboard: {base}/job/{job.get('id')}" if base else ""
    body = (f"Your Job Agent applied for:\n\n"
            f"  Role:    {job['title']}\n"
            f"  Company: {job.get('company') or '—'}\n"
            f"  Sent to: {job.get('apply_email')}\n"
            f"  Source:  {job.get('url')}\n\n"
            f"{detail}\n\nDrafts sent: CV + application letter (PDF), from "
            f"{_cfg()['email']['username']}.{link}")
    return send_notification(f"✅ Applied: {job['title']} — {job.get('company') or ''}", body)


def send_digest(rows, header: str = None) -> bool:
    """Summary of everything drafted/approved/sent — with tappable links."""
    base = _cfg().get("schedule", {}).get("base_url") or ""
    if not rows:
        body = "Nothing drafted yet — the agent will search again tomorrow at the scheduled time."
    else:
        lines = []
        for r in rows:
            link = f" ({base}/job/{r['id']})" if base and r.get("status") == "pending" else ""
            lines.append(f"• [{r['status'].upper()}] {r['title']} at {r.get('company') or '?'}{link}")
        body = (header or "Your Job Agent digest:") + "\n\n" + "\n".join(lines)
        if base:
            body += f"\n\nOpen the dashboard to review & approve: {base}"
        else:
            body += "\n\nOpen the dashboard on your laptop (http://localhost:7860) to review & approve."
    return send_notification(_cfg().get("notify", {}).get("digest_subject", "Job Agent digest"), body)


# ------------------------------------------------------------------ collective notifications
# One combined email when a whole batch of applications finishes — not one
# email per job. Items queue up; when nothing is still "applying" and the
# queue has been quiet for ~75s, a single summary email goes out.
import threading as _threading

_batch_lock = _threading.Lock()
_batch_items = []
_batch_timer = None


def queue_application_result(kind, title, company="", detail="", questions=None, job_id=None, proof=""):
    """kind: 'submitted' | 'waiting'. Collective email fires when all done."""
    global _batch_timer
    with _batch_lock:
        _batch_items.append({"kind": kind, "title": title, "company": company or "",
                             "detail": detail, "questions": questions or [],
                             "job_id": job_id, "proof": proof})
        if _batch_timer:
            _batch_timer.cancel()
    t = _threading.Timer(75, _flush_batch)
    t.daemon = True
    with _batch_lock:
        _batch_timer = t
    t.start()


def _flush_batch():
    global _batch_timer
    # still something applying? wait a little longer (cap via 45s re-checks)
    try:
        from . import store as _store
        conn = _store.connect()
        busy = conn.execute("SELECT COUNT(*) n FROM jobs WHERE status='applying'").fetchone()["n"]
        conn.close()
        if busy:
            t = _threading.Timer(45, _flush_batch)
            t.daemon = True
            with _batch_lock:
                _batch_timer = t
            t.start()
            return
    except Exception:
        pass
    with _batch_lock:
        items = _batch_items[:]
        _batch_items[:] = []
        _batch_timer = None
    if not items:
        return
    base = _cfg().get("schedule", {}).get("base_url") or ""
    submitted = [i for i in items if i["kind"] == "submitted"]
    waiting = [i for i in items if i["kind"] == "waiting"]
    lines = ["All applications in this batch are now complete.", ""]
    if submitted:
        lines.append(f"SUBMITTED SUCCESSFULLY ({len(submitted)}):")
        for i in submitted:
            p = f"  proof: {i['proof']}" if i["proof"] else ""
            lines.append(f"  + {i['title']} at {i['company'] or '?'} - {i['detail']}{p}")
        lines.append("")
    if waiting:
        lines.append(f"WAITING FOR YOUR ANSWERS ({len(waiting)}):")
        for i in waiting:
            qs = ", ".join(i["questions"]) if i["questions"] else "open the job page to see"
            lines.append(f"  ? {i['title']} at {i['company'] or '?'} needs: {qs}")
            if base and i["job_id"]:
                lines.append(f"    answer here: {base}/job/{i['job_id']}/complete")
        lines.append("")
    lines.append("Proof screenshots for every web application are saved in")
    lines.append("data/applications/ and shown on each job's page in your dashboard.")
    send_notification(
        f"Job Agent done - {len(submitted)} submitted, {len(waiting)} awaiting your answers",
        "\n".join(lines))
