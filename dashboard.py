#!/usr/bin/env python3
"""Approval dashboard — review drafted CVs & letters, approve or reject.

Run:  python3 dashboard.py   (then open the preview URL)
"""
import html
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, redirect, url_for, Response, send_file
from urllib.parse import quote as q

from agent import store, tailor
from agent import sender as sender_mod
from agent.config import load_settings, load_profile
from agent.sources import whatsapp
import run_search

app = Flask(__name__)

PROFILE_NAME = (load_profile().get("name") or "Candidate")


def _web_apply_async(job_id, extra_answers=None):
    """Run the browser auto-filler in the background; update the job + notify."""
    import threading

    def work():
        conn = store.connect()
        row = store.job_by_id(conn, job_id)
        if not row:
            return
        store.update(conn, job_id, status="applying")
        store.log_event(conn, job_id, "web_apply_start", "browser agent opening the application form")
        try:
            from agent import formfill, cvpdf
            _cfg = load_settings()
            _wa = _cfg.get("web_apply", {})
            out = os.path.join("data", "applications", f"job_{job_id}")
            cv = cvpdf.md_to_pdf(row["cv_md"], os.path.join(out, f"{PROFILE_NAME} - CV.pdf"))
            ap = formfill.WebApplier(
                headless=not _wa.get("show_browser", False),
                allow_human=_wa.get("show_browser", False),
                human_wait=int(_wa.get("human_wait_minutes", 5)) * 60,
                review_wait=int(_wa.get("review_wait_minutes", 15)) * 60,
                submit_automatically=False)
            res = ap.run(dict(row), cv, row["letter_md"], extra_answers=extra_answers)
            status_map = {"submitted": "sent", "filled": "needs_review",
                          "needs_review": "needs_review", "needs_login": "needs_login",
                          "needs_security_check": "needs_security_check", "closed": "closed",
                          "failed": "needs_review"}
            store.update(conn, job_id, status=status_map.get(res["status"], "needs_review"))
            store.log_event(conn, job_id, f"web_apply_{res['status']}", res.get("detail", ""))
            if res.get("missing"):
                import json as _json
                _dir = os.path.join("data", "applications", f"job_{job_id}")
                os.makedirs(_dir, exist_ok=True)
                _json.dump(res["missing"], open(os.path.join(_dir, "missing.json"), "w"))
            if res["status"] == "submitted":
                sender_mod.queue_application_result(
                    "submitted", row["title"], row["company"],
                    "web form submitted", job_id=job_id,
                    proof=f"data/applications/job_{job_id}/web_proof.png")
            else:
                sender_mod.queue_application_result(
                    "waiting", row["title"], row["company"], res.get("detail", ""),
                    questions=res.get("missing") or [], job_id=job_id)
        except ImportError:
            store.log_event(conn, job_id, "web_apply_unavailable",
                            "playwright not installed - run: pip install playwright && playwright install chromium")
            store.update(conn, job_id, status="needs_review")
        except Exception as e:
            store.log_event(conn, job_id, "web_apply_error", str(e)[:200])
            store.update(conn, job_id, status="needs_review")

    threading.Thread(target=work, daemon=True).start()

# ---------------------------------------------------------------- styling
CSS = """
:root{--bg:#0e1220;--card:#171d31;--ink:#e8ecf7;--mut:#93a0bd;--acc:#4f8cff;--ok:#2ecc8f;--bad:#ff6b6b;--warn:#ffb347}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);padding:18px;max-width:1000px;margin:auto}
h1{font-size:1.45rem;margin-bottom:2px} .sub{color:var(--mut);font-size:.9rem;margin-bottom:16px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.stat{background:var(--card);border-radius:12px;padding:10px 16px;min-width:100px}
.stat b{display:block;font-size:1.3rem}.stat span{color:var(--mut);font-size:.75rem;text-transform:uppercase;letter-spacing:.5px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.tab{padding:7px 14px;border-radius:99px;background:var(--card);color:var(--mut);text-decoration:none;font-size:.85rem;border:1px solid transparent}
.tab.on{color:#fff;border-color:var(--acc);background:#1c2745}
.card{background:var(--card);border-radius:14px;padding:16px;margin-bottom:12px;border-left:4px solid var(--acc)}
.card h3{font-size:1rem;margin-bottom:3px}
.card .co{color:var(--mut);font-size:.85rem;margin-bottom:8px}
.badge{display:inline-block;font-size:.7rem;padding:2px 9px;border-radius:99px;margin-right:6px;background:#243055;color:#bcd0ff}
.score{float:right;font-weight:700;color:var(--ok)}
.actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
button,a.btn{cursor:pointer;border:none;border-radius:9px;padding:8px 16px;font-size:.85rem;font-weight:600;text-decoration:none;display:inline-block}
.approve{background:var(--ok);color:#04150e}.reject{background:transparent;color:var(--bad);border:1px solid var(--bad)}
.run{background:var(--acc);color:#fff;margin-left:auto}
.link{color:var(--acc);text-decoration:none;font-size:.85rem}
.doc{background:#10162a;border-radius:12px;padding:20px;margin:12px 0;white-space:pre-wrap;font-family:Georgia,serif;font-size:.95rem;line-height:1.65;max-height:480px;overflow:auto;border:1px solid #26304f}
.paper{background:#fff;color:#111;border-radius:6px;padding:30px 34px;margin:12px 0;font-family:'Times New Roman',Times,serif;font-size:14.5px;line-height:1.68;max-height:520px;overflow:auto;box-shadow:0 2px 14px rgba(0,0,0,.35)}
.paper .dname{font-size:21px;font-weight:700;letter-spacing:.5px;margin-bottom:6px;color:#111}
.paper .dhead{color:#222;margin-bottom:2px}
.paper .dcontact{color:#444;font-size:13px;margin-bottom:12px}
.paper .dsec{font-weight:700;letter-spacing:1px;font-size:13px;margin-top:18px;margin-bottom:8px;padding-bottom:0;border-bottom:none;color:#111;text-transform:uppercase}
.paper .dsub{font-weight:700;font-size:14.5px;margin-top:12px;margin-bottom:4px;color:#111}
.paper ul{margin:6px 0 10px;padding-left:20px}
.paper li{margin-bottom:5px;line-height:1.6}
.paper li.sub{list-style-type:disc;color:#222;margin-left:14px}
.paper p{margin:9px 0}
.newbadge{background:#123d2c;color:#7ef0b8}
.aibad{background:#33140f;border:1px solid #ff6b6b;color:#ffd0c8;border-radius:12px;padding:12px 16px;margin:12px 0;font-size:.86rem;line-height:1.5}
.aibad code{background:#1b0d0a;padding:1px 5px;border-radius:4px;color:#ffd0c8}
.aiok{background:#0e2f22;border:1px solid #2ecc8f;color:#8df0c0;border-radius:12px;padding:12px 16px;margin:12px 0;font-size:.86rem}
textarea{width:100%;background:#0b1020;color:#dfe6ff;border:1px solid #2a3557;border-radius:10px;padding:12px;font-family:'Times New Roman',Times,serif;font-size:.82rem;line-height:1.5;min-height:260px}
.savebar{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.toolbar{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.tbtn{background:#243055;color:#dfe6ff;border:none;border-radius:7px;padding:6px 13px;font-size:.85rem;cursor:pointer;font-weight:700}
.tbtn.i{font-style:italic;font-weight:400}
.tbtn:hover{background:#31406e}
.editgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.editgrid{grid-template-columns:1fr}}
.prevlabel{color:var(--mut);font-size:.78rem;margin:8px 0 4px;text-transform:uppercase;letter-spacing:.6px}
.fmt{color:var(--mut);font-size:.78rem;margin-top:6px}
.urlbox{background:#10162a;border:1px solid #2a3557;border-radius:10px;padding:10px 12px;font-family:Consolas,monospace;font-size:.82rem;word-break:break-all;cursor:pointer;color:#9db4e8;user-select:all;margin:6px 0}
.urlbox:hover{border-color:var(--acc)}
h2{font-size:1.1rem;margin:18px 0 8px}
.reasons{color:var(--mut);font-size:.83rem;margin-top:6px}
.empty{text-align:center;color:var(--mut);padding:40px 0}
.flash{background:#1c2745;border:1px solid var(--acc);padding:10px 14px;border-radius:10px;margin-bottom:12px;font-size:.9rem}
.bigstatus{padding:16px 18px;border-radius:14px;font-size:1.05rem;font-weight:700;margin:10px 0;display:flex;alignitems:center;gap:10px}
.bigstatus.applying{background:#241b3f;border:2px solid #9b7bff;color:#c9b3ff;animation:pulse 1.6s infinite}
.bigstatus.sent{background:#0e2f22;border:2px solid #2ecc8f;color:#8df0c0}
.bigstatus.review{background:#33270f;border:2px solid #ffb347;color:#ffd98a}
.bigstatus.login{background:#33140f;border:2px solid #ff6b6b;color:#ffb3a8}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
.back{color:var(--mut);text-decoration:none;font-size:.85rem}
@media(max-width:600px){body{padding:12px}.doc{padding:14px;font-size:.88rem}}
"""

SHELL = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Agent</title><style>{css}</style></head><body>{body}</body></html>"""


def esc(t): return html.escape(str(t or ""))


def _short_ai_error(msg: str) -> str:
    """Keep the actionable first sentence of an AI error, drop the JSON noise."""
    t = " ".join(str(msg or "").split())
    t = t.split("API key not valid")[0].strip(" .:-")
    return (t or "AI error")[:160]


def md_html(md: str) -> str:
    """Draft text -> clean paper HTML. Plain human text and old markdown both
    get bold, well-spaced headings without adding symbols to the saved draft."""
    import re as _re
    sections = {
        "PROFILE", "SKILLS", "EXPERIENCE", "EDUCATION", "ACADEMIC PROJECT",
        "SELECTED PROJECTS", "ADDITIONAL INFORMATION", "REFERENCES",
    }
    subheadings = {"Technical", "People and Communication"}

    def looks_like_heading(t):
        if not t or t.startswith("http"):
            return False
        if t.isupper() and len(t) < 70 and " " in t:
            return True
        if "," in t and _re.search(r"\b(19|20)\d{2}\b", t) and len(t) < 120:
            return True
        if t.startswith(("Bachelor", "Diploma", "Certificate", "Master")):
            return True
        return False

    out, ul, first = [], False, True

    def close():
        nonlocal ul
        if ul:
            out.append("</ul>")
            ul = False

    def bold(t):
        t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(t))
        t = _re.sub(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)", r"\1", t)
        return _re.sub(r"(https?://[^\s<]+)",
                       r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)

    for raw in (md or "").split("\n"):
        s = raw.rstrip()
        t = s.strip()
        if not t:
            continue
        if first and t.startswith("# "):
            close(); out.append(f'<div class="dname">{bold(t[2:])}</div>')
            first = False
            continue
        if first:
            close(); out.append(f'<div class="dname">{bold(t)}</div>')
            first = False
            continue
        if t.startswith("## "):
            close(); out.append(f'<div class="dsec">{esc(t[3:]).upper()}</div>')
        elif t.startswith("### "):
            close(); out.append(f'<div class="dsub">{bold(t[4:])}</div>')
        elif t in sections:
            close(); out.append(f'<div class="dsec">{esc(t)}</div>')
        elif t in subheadings or looks_like_heading(t):
            close(); out.append(f'<div class="dsub">{bold(t)}</div>')
        elif t.startswith("• ") or t.startswith("- "):
            if not ul:
                out.append("<ul>"); ul = True
            out.append(f'<li>{bold(t[2:])}</li>')
        elif out and ("·" in t or "@" in t or _re.search(r"\+?\d[\d\s-]{7,}", t)) and not any("dsec" in o for o in out):
            out.append(f'<div class="dcontact">{bold(t)}</div>')
        elif out and not any("dsec" in o for o in out):
            out.append(f'<div class="dhead">{bold(t)}</div>')
        else:
            close(); out.append(f"<p>{bold(t)}</p>")
    close()
    return '<div class="paper">' + "".join(out) + "</div>"


def score_color(s):
    s = s or 0
    return "#2ecc8f" if s >= 60 else ("#ffb347" if s >= 40 else "#93a0bd")


def job_card(row, active_tab):
    skills = eval(row["matched_skills"]) if row["matched_skills"] else []
    badges = "".join(f'<span class="badge">{esc(s[:28])}</span>' for s in skills[:4])
    fresh = ""
    try:
        import datetime as _dt
        age = (_dt.datetime.now() - _dt.datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 86400
        if age < 2:
            fresh = '<span class="badge newbadge">🆕</span>'
    except Exception:
        pass
    status_colors = {"pending": "#ffb347", "approved": "#2ecc8f", "rejected": "#ff6b6b", "sent": "#4f8cff",
                      "skipped": "#556", "applying": "#9b7bff", "needs_review": "#ff9f43", "needs_login": "#ff6b6b"}
    st = row["status"]
    actions = ""
    if st == "pending":
        actions = f"""<div class=actions>
        <form method=post action="/job/{row['id']}/approve"><button class=approve>✓ Approve draft only</button></form>
        <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{row['id']}/edit">✏️ Edit</a>
        <form method=post action="/job/{row['id']}/reject"><button class=reject>✕ Reject</button></form></div>"""
    elif st in ("needs_review", "needs_login", "needs_form"):
        actions = f"""<div class=actions>
        <form method=post action="/job/{row['id']}/webapply"><button class=approve>🤖 Retry auto-fill</button></form>
        <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{row['id']}">View status ↗</a></div>"""
    elif st == "approved":
        actions = f"""<div class=actions><span class=badge style=background:#123d2c;color:#7ef0b8>queued to send</span>
        <a class="btn approve" style=background:#4f8cff;color:#fff href="{esc(row['apply_url'])}" target=_blank>Open application ↗</a></div>"""
    return f"""<div class=card style=border-left-color:{score_color(row['score'])}">
    <span class=score style=color:{score_color(row['score'])}>{int(row['score'] or 0)}</span>
    <h3><a href="/job/{row['id']}" style=color:var(--ink);text-decoration:none>{esc(row['title'])}</a> {fresh}</h3>
    <div class=co>{esc(row['company'] or '—')} · {esc(row['location'] or '')} · via {esc(row['source'])}
      <span class="badge" style=background:{status_colors.get(st,'#243055')};color:#fff>{st}</span></div>
    {badges}{actions}</div>"""


@app.route("/")
def index():
    conn = store.connect()
    tab = request.args.get("tab", "pending")
    s = store.stats(conn)
    pending, approved = s.get("pending", 0), s.get("approved", 0)
    sent, rejected = s.get("sent", 0), s.get("rejected", 0)
    flash = ""
    if request.args.get("ran"):
        flash = f"<div class=flash>✅ Search run complete. New drafts ready below for your review.</div>"
    if request.args.get("msg"):
        flash = f"<div class=flash>{esc(request.args['msg'])}</div>"
    tabs = [("pending", f"📝 Pending review ({pending})"), ("approved", f"✅ Approved ({approved})"),
            ("sent", f"📤 Sent ({sent})"), ("rejected", f"🗑 Rejected ({rejected})"), ("skipped", "⋯ Skipped")]
    rows = store.jobs_by_status(conn, tab)
    cards = "".join(job_card(r, tab) for r in rows) or f'<div class=empty>No jobs here yet.<br>Run a search below.</div>'
    st_ai = tailor.ai_status()
    if st_ai["available"] and not st_ai["last_error"]:
        engine = ("AI \u2728 (last draft was AI-written)" if st_ai.get("last_engine") == "ai"
                  else "AI ready \u2728 (regenerate a draft to use it)")
    else:
        engine = "template (built-in wording)"
    if st_ai["last_error"]:
        engine = "template ({" + esc(_short_ai_error(st_ai["last_error"])) + "})"
    _sched = load_settings().get("schedule", {}) or {}
    sched_note = (f" · ⏰ autopilot daily at {_sched.get('time')}" if _sched.get("enabled") else "")
    ai_banner = ""
    if st_ai["last_error"]:
        ai_banner = (f'<div class="aibad"><b>The AI writer is not working right now.</b> '
                     f'Every draft below was written by the built-in template engine, '
                     f'not by Gemini. Reason: {esc(st_ai["last_error"])[:300]}<br>'
                     f'Fix it, then run <code>python check_ai.py</code> to confirm. '
                     f'<a class="link" href="/ai">Open the AI check page</a></div>')
    elif not st_ai["available"]:
        ai_banner = ('<div class="aibad"><b>No AI key is set.</b> Drafts use the built-in '
                     'template engine. Add your Gemini key to config/settings.yaml under '
                     'llm.api_key, then run <code>python check_ai.py</code>. '
                     '<a class="link" href="/ai">Open the AI check page</a></div>')
    body = f"""
    <h1>🤖 Your Job Agent <span style="font-size:.7em;color:var(--mut)">draft engine: {engine}{sched_note}</span></h1>
    <div class=sub>BBIT graduate · Kenya + remote · drafts wait for YOUR approval</div>
    {ai_banner}
    {flash}
    <div class=stats>
      <div class=stat><b>{pending}</b><span>awaiting you</span></div>
      <div class=stat><b>{approved}</b><span>approved</span></div>
      <div class=stat><b>{sent}</b><span>sent</span></div>
      <div class=stat><b>{s.get('skipped',0)}</b><span>skipped</span></div>
    </div>
    <div class=bar>
      {''.join(f'<a class="tab {"on" if t==tab else ""}" href="/?tab={t}">{lbl}</a>' for t,lbl in tabs)}
      <a class="tab" href="/whatsapp">💬 WhatsApp inbox</a>
      <form method=post action="/notify/digest" style="margin-left:8px"><button class="run" style="background:#243055;color:#bcd0ff">📧 Email me a digest</button></form>
      <form method=post action="/run" style="margin-left:auto"><button class=run>⟳ Run job search now</button></form>
    </div>
    {cards}"""
    return SHELL.format(css=CSS, body=body)


def _status_banner(status, job_id=None):
    m = {
        "applying": ("🤖 Applying…", "applying", "The browser agent is on the website right now, filling your application. This page updates itself — watch it turn green."),
        "sent": ("✅ SENT SUCCESSFULLY", "sent", "Your application was submitted. Proof screenshot + email copy are below."),
        "needs_review": ("✍ ANSWER BELOW TO FINISH", "review", "The agent filled what it could and stopped safely. The questions it needs are RIGHT BELOW this box — answer them and it fills them in, submits, and this turns green."),
        "needs_form": ("🔗 APPLICATION LINK NEEDED", "review", "This posting keeps its form on an external page. Paste the direct application link below (open the posting to find it) and the agent continues from there."),
        "needs_login": ("🔐 THIS BOARD ASKS FOR A LOGIN", "login", "The application form here only opens for signed-in members. Paste the employer's direct application link below (or their email) and the agent continues. On your PC you can also sign in once in the open browser window and the agent takes over."),
    }
    if status not in m:
        return ""
    t, cls, sub = m[status]
    return f'<div class="bigstatus {cls}"><div>{t}<div style="font-weight:400;font-size:.85rem;margin-top:4px;color:inherit">{sub}</div></div></div>'



def _inline_questions(job_id):
    """When the agent needs answers, the questions appear right on the job page."""
    missing = _missing_fields(job_id)
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    fields = ""
    for i, k in enumerate(missing):
        fields += ('<label style="display:block;margin:10px 0"><b>' + esc(k) + '</b>'
                   '<input name="ans_' + str(i) + '" placeholder="type your answer here" required '
                   'style="width:100%;background:#0b1020;color:#dfe6ff;border:1px solid #2a3557;'
                   'border-radius:8px;padding:9px;margin-top:4px;font-size:.95rem"></label>')
    if not fields:
        return f"""
    <div class="bigstatus review"><div>&#128279; <b>Give the direct application link</b>
    <div style="font-weight:400;font-size:.88rem;margin-top:6px">Open the original posting, find the &ldquo;Apply&rdquo; button, copy the page it opens, and paste it here &mdash; the agent takes over from there.</div></div></div>
    <form method=post action="/job/{job_id}/complete" style="margin-bottom:14px">
    <input name="direct_link" placeholder="https://the-employer-application-page..." required
    style="width:100%;background:#0b1020;color:#dfe6ff;border:1px solid #2a3557;border-radius:8px;padding:9px;font-size:.95rem">
    <div class=savebar><button class=approve>&#9989; Continue with this link</button></div></form>"""
    return f"""
    <div class="bigstatus review"><div>&#9997; <b>The agent needs {len(missing)} answer(s) from you to finish this application</b>
    <div style="font-weight:400;font-size:.88rem;margin-top:6px">Answer below - the agent fills them in, then opens the completed form for your review and final Submit click.</div></div></div>
    <form method=post action="/job/{job_id}/complete" style="margin-bottom:14px">{fields}
    <button class=approve>&#9989; Continue to filled form</button></form>"""



def _posting_link(row):
    import json as _json
    url = (row["apply_url"] or row["url"] or "").strip()
    if not url:
        return ""
    jurl = _json.dumps(url)
    return f"""
    <h2>&#128279; Original posting link <span style="font-size:.7em;color:var(--mut)">(tap the text to select, then Ctrl+C / long-press copy)</span></h2>
    <div class=urlbox onclick="document.getSelection().selectAllChildren(this)">{esc(url)}</div>
    <div class=savebar>
      <button class=tbtn onclick="copyPostUrl()">&#128203; Copy link</button>
      <span id=copystat style="color:var(--mut);font-size:.85rem"></span>
    </div>
    <script>function copyPostUrl(){{const t=document.createElement('textarea');t.value={jurl};
      document.body.appendChild(t);t.select();let ok=false;
      try{{ok=document.execCommand('copy')}}catch(e){{}}
      document.body.removeChild(t);
      document.getElementById('copystat').textContent = ok ? 'Copied! Paste it in your browser.' : 'Auto-copy blocked here - the link above is selected, press Ctrl+C.';
      if(!ok){{document.getSelection().selectAllChildren(document.querySelector('.urlbox'));}}}}</script>"""



def _activity(conn, job_id) -> str:
    """Delivery log / proof-of-sending panel for a job."""
    evs = conn.execute("SELECT event, detail, created_at FROM events WHERE job_id=? ORDER BY id DESC LIMIT 5", (job_id,)).fetchall()
    if not evs:
        return ""
    icons = {"drafted": "✎", "approved": "✓", "sent": "📤", "send_failed": "⚠", "rejected": "✕", "edited": "✏️"}
    rows = "".join(f"<div>{icons.get(e['event'],'·')} <b>{esc(e['event'])}</b> — {esc(e['detail'] or '')} <span style='color:var(--mut)'>· {esc(e['created_at'])}</span></div>" for e in evs)
    tip = ("<div class=flash style=margin-top:8px>📬 <b>Proof this was really sent:</b> ① a blind copy of the exact email was delivered to your notification address ② "
           "check the <b>Sent folder</b> of the sending address in your settings ③ the exact PDFs sent are saved in <code>data/applications/</code>. "
           "If an address bounces, the failure appears here and in your inbox.</div>" if any(e["event"] == "sent" for e in evs) else "")
    return f'<h2>📬 Activity log</h2><div class=doc style=max-height:200px>{rows}</div>{tip}'


def _has_proof(job_id):
    return os.path.exists(os.path.join("data", "applications", f"job_{job_id}", "web_proof.png"))


@app.route("/ai")
def ai_page():
    """One page that answers: is the AI working, and if not, why?"""
    st = tailor.ai_status()
    llm = load_settings().get("llm") or {}
    key = str(llm.get("api_key") or "")
    masked = (key[:4] + "..." + key[-4:] + " (" + str(len(key)) + " chars)") if len(key) > 8 else ("set but very short" if key else "not set")
    rows = [
        ("Draft engine last used", "AI" if st["available"] and not st["last_error"] else "template (built-in wording)"),
        ("Provider", esc(str(llm.get("provider") or "none"))),
        ("Model", esc(str(llm.get("model") or "(default)"))),
        ("Key", esc(masked)),
        ("Last AI error", esc(_short_ai_error(st["last_error"])) if st["last_error"] else "none"),
    ]
    table = "".join(f"<tr><td class=ftkey>{k}</td><td>{v}</td></tr>" for k, v in rows)
    tip = ("<div class=aiok><b>AI is configured.</b> If a specific draft still looks template-written, "
           "it was probably made before the key worked. Open the job, click Edit, then Save &amp; approve "
           "draft only to regenerate it.</div>") if (st["available"] and not st["last_error"]) else (
           "<div class=aibad><b>AI is not working.</b> Drafts are template-written. In VS Code open "
           "<code>config/settings.yaml</code>, put your Gemini key under <code>llm.api_key</code> "
           "on one line with no quotes, save, then run <code>python check_ai.py</code> in the terminal. "
           "That prints the exact reason if it still fails.</div>")
    body = f"""<a class=back href="/">← back to jobs</a>
    <h1 style=margin-top:8px>✨ AI check</h1>
    {tip}
    <div class=bulkbox style="background:#10162a;border:1px solid #2a3557;border-radius:12px;padding:6px 14px">
      <table class=ftable>{table}</table>
    </div>
    <div class=sub style="margin-top:14px">The dashboard only calls Gemini when it writes a draft. Nothing is sent anywhere else.</div>"""
    return SHELL.format(css=CSS + "\n.ftable{width:100%;border-collapse:collapse}.ftable td{padding:8px 4px;border-bottom:1px solid #22304f;font-size:.88rem;vertical-align:top}.ftkey{color:var(--mut);width:38%}", body=body)


@app.route("/proof/<int:job_id>")
def proof(job_id):
    p = os.path.join("data", "applications", f"job_{job_id}", "web_proof.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return Response("no screenshot yet", status=404)


@app.route("/job/<int:job_id>/webapply", methods=["POST"])
def webapply(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if row and row["status"] in ("pending", "approved", "needs_review", "needs_login", "needs_form"):
        store.update(conn, job_id, status="approved")
        _web_apply_async(job_id)
    return redirect(f"/job/{job_id}?msg=" + q("🤖 Browser agent launched — watch the Activity log below (refresh in a minute)."))


@app.route("/job/<int:job_id>")
def detail(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row:
        return SHELL.format(css=CSS, body='<div class=empty>Job not found.</div>')
    reasons = eval(row["reasons"]) if row["reasons"] else []
    st = row["status"]
    is_new = ""
    try:
        import datetime as _dt
        age = (_dt.datetime.now() - _dt.datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 86400
        if age < 2:
            is_new = '<span class="badge newbadge">🆕 FRESH</span>'
    except Exception:
        pass
    action_html = ""
    if st == "pending":
        action_html = f"""<div class=actions>
        <form method=post action="/job/{job_id}/approve"><button class=approve>✓ Approve draft only</button></form>
        <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{job_id}/edit">✏️ Edit draft first</a>
        <form method=post action="/job/{job_id}/reject"><button class=reject>✕ Reject</button></form>
        <a class="btn" style="background:#243055;color:#bcd0ff" href="{esc(row['apply_url'])}" target=_blank>View original posting ↗</a></div>"""
    elif st in ("approved", "applying", "needs_review", "needs_login"):
        proof = f'<img src="/proof/{job_id}" style="max-width:100%;border:1px solid #26304f;border-radius:8px;margin-top:8px">' if _has_proof(job_id) else ""
        if row["apply_email"]:
            action_html = f"""<div class=flash>✅ Draft approved — email application: <b>{esc(row['apply_email'])}</b></div>
            <div class=actions><form method=post action="/job/{job_id}/sendemail"><button class=approve>Send approved email application</button></form></div>"""
        else:
            url = esc(row['apply_url'])
            action_html = f"""<div class=flash>✅ Approved — the browser agent applies on the website for you.</div>
            <div class=actions>
            <form method=post action="/job/{job_id}/webapply"><button class=approve>🤖 Open, auto-fill &amp; review before submitting</button></form>
            </div>
            <div class=sub style=margin-top:8px>Application link (copy into your browser if you prefer doing it manually):</div>
            <div class=doc style=max-height:60px;user-select:all>{url}</div>
            {proof}"""
        action_html += f"""<div class=actions><form method=post action="/job/{job_id}/reject"><button class=reject>Undo approval</button></form></div>"""
    banner = _status_banner(row["status"], job_id)
    if row["status"] in ("needs_review", "needs_form", "needs_login"):
        banner += _inline_questions(job_id)
    poll = ""
    if row["status"] in ("approved", "applying"):
        poll = """<script>
function pollStatus(){
  fetch('/job/__JOBID__/status').then(r=>r.json()).then(s=>{
    if(s.status && !['approved','applying'].includes(s.status)){ location.reload(); }
  }).catch(()=>{});
}
setInterval(pollStatus, 4000);
</script>""".replace("__JOBID__", str(job_id))
    msg = request.args.get("msg", "")
    flash = f"<div class=flash>{esc(msg)}</div>" if msg else ""
    body = f"""
    <a class=back href="/">← back to list</a>
    <h1 style=margin-top:8px>{esc(row['title'])} {is_new}</h1>
    {flash}
    {banner}
    {poll}
    <div class=sub>{esc(row['company'] or '—')} · {esc(row['location'] or '')} · score {int(row['score'] or 0)}/100 · via {esc(row['source'])} · status: {st}</div>
    <div class=reasons>{'<br>'.join('• ' + esc(r) for r in reasons)}</div>
    {action_html}
    <div class=actions style="margin-top:4px">
      <a class="btn" style="background:#123d2c;color:#7ef0b8" href="/job/{job_id}/view/cv">&#128065; View / Save CV</a>
      <a class="btn" style="background:#123d2c;color:#7ef0b8" href="/job/{job_id}/view/letter">&#128065; View / Save Letter</a>
      <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{job_id}/download/cv">&#11015; CV PDF</a>
      <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{job_id}/download/letter">&#11015; Letter PDF</a>
    </div>
    {_posting_link(row)}
    <h2>📄 Job description (excerpt)</h2><div class=doc>{esc((row['description'] or '')[:2000])}…</div>
    {_activity(conn, job_id)}
    <h2>📝 Tailored CV — exactly as the employer will receive it</h2>{md_html(row['cv_md'] or '')}
    <h2>✉️ Application letter — exactly as sent</h2>{md_html(row['letter_md'] or '')}"""
    return SHELL.format(css=CSS, body=body)


@app.route("/job/<int:job_id>/status")
def job_status(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row:
        return {"status": "unknown"}
    ev = conn.execute("SELECT event, detail FROM events WHERE job_id=? ORDER BY id DESC LIMIT 1",
                      (job_id,)).fetchone()
    return {"status": row["status"],
            "last_event": ev["event"] if ev else "",
            "detail": ev["detail"] if ev else "",
            "proof": _has_proof(job_id)}



def _missing_fields(job_id):
    import json
    p = os.path.join("data", "applications", f"job_{job_id}", "missing.json")
    try:
        vals = json.load(open(p))
        out = []
        for v in vals:
            if v not in out:
                out.append(v)
        return out
    except Exception:
        conn = store.connect()
        ev = conn.execute("SELECT detail FROM events WHERE job_id=? AND event LIKE 'web_apply%' ORDER BY id DESC LIMIT 1",
                          (job_id,)).fetchone()
        if ev and ev["detail"] and ev["detail"].startswith("Could not fill:"):
            return [x.strip() for x in ev["detail"].split(":", 1)[1].split(",")]
        return []


@app.route("/job/<int:job_id>/complete", methods=["GET", "POST"])
def complete(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row:
        return redirect("/")
    if request.method == "POST":
        direct = (request.form.get("direct_link") or "").strip()
        if direct:
            store.update(conn, job_id, apply_url=direct, status="approved")
            _web_apply_async(job_id)
            return redirect(f"/job/{job_id}?msg=" + q("Following your link now — the agent fills the form and leaves it ready for your review."))
        missing = _missing_fields(job_id)
        answers = {}
        for i, key in enumerate(missing):
            val = (request.form.get("ans_" + str(i)) or "").strip()
            if val:
                answers[key] = val
        if not answers:
            return redirect(f"/job/{job_id}/complete")
        store.update(conn, job_id, status="approved")
        _web_apply_async(job_id, extra_answers=answers)
        return redirect(f"/job/{job_id}?msg=" + q("Relaunching with your answers — review the completed form and click Submit yourself."))
    missing = _missing_fields(job_id)
    fields = ""
    for i, k in enumerate(missing):
        fields += ('<label style="display:block;margin:10px 0"><b>' + esc(k) + '</b>'
                   '<input name="ans_' + str(i) + '" placeholder="type your answer here" required '
                   'style="width:100%;background:#0b1020;color:#dfe6ff;border:1px solid #2a3557;'
                   'border-radius:8px;padding:9px;margin-top:4px;font-size:.95rem"></label>')
    if not fields:
        fields = "<div class='sub'>No specific fields recorded — just retry below.</div>"
    proof = ""
    if _has_proof(job_id):
        proof = f'<img src="/proof/{job_id}" style="max-width:100%;border:1px solid #26304f;border-radius:8px">'
    body = f"""
    <a class=back href="/job/{job_id}">&larr; back to draft</a>
    <h1 style=margin-top:8px>&#128221; Complete this application &mdash; {esc(row['title'])}</h1>
    <div class=sub>The agent filled everything it could. Below is exactly where it reached, and the parts only you can answer. Fill them and press the button &mdash; the agent does the rest and submits.</div>
    <h2>&#128248; Where the agent reached</h2>{proof}
    {_posting_link(row)}
    <h2>&#9997; The parts that need you</h2>
    <form method=post>
    {fields}
    <div class=savebar>
      <button class=approve>&#9989; Submit my answers &amp; finish the application</button>
    </div></form>
    <div class=sub style=margin-top:10px>Prefer to retry as-is? Go back and press &ldquo;Retry auto-fill&rdquo;. On your PC, the &ldquo;Auto-fill&rdquo; button opens the browser window visibly and waits for you there.</div>"""
    return SHELL.format(css=CSS, body=body)



def _safe_fn(t):
    import re as _re
    return _re.sub(r"[^A-Za-z0-9]+", " ", t).strip()[:60]


@app.route("/job/<int:job_id>/download/<doc>")
def download_doc(job_id, doc):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row or doc not in ("cv", "letter"):
        return Response("not found", status=404)
    from agent import cvpdf
    label = _safe_fn(row["title"]) or "Application"
    md = row["cv_md"] if doc == "cv" else row["letter_md"]
    fname = f"{PROFILE_NAME} - {'CV' if doc == 'cv' else 'Application Letter'} - {label}.pdf"
    path = os.path.join("data", "applications", f"job_{job_id}", f"download_{doc}.pdf")
    cvpdf.md_to_pdf(md, path)
    return send_file(os.path.abspath(path), as_attachment=True, download_name=fname)



def _render_doc_pages(job_id, doc):
    """PDF -> PNG pages saved to data/applications/job_X/ for in-page viewing."""
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row or doc not in ("cv", "letter"):
        return None, 0
    from agent import cvpdf
    d = os.path.join("data", "applications", f"job_{job_id}")
    pdf_path = os.path.join(d, f"view_{doc}.pdf")
    md = row["cv_md"] if doc == "cv" else row["letter_md"]
    cvpdf.md_to_pdf(md, pdf_path)
    import pymupdf
    doc_pdf = pymupdf.open(pdf_path)
    pages = []
    for i, pg in enumerate(doc_pdf):
        pix = pg.get_pixmap(dpi=130)
        p = os.path.join(d, f"view_{doc}_{i}.png")
        pix.save(p)
        pages.append(p)
    doc_pdf.close()
    return row, pages


@app.route("/job/<int:job_id>/view/<doc>")
def view_doc(job_id, doc):
    row, pages = _render_doc_pages(job_id, doc)
    if not row:
        return redirect("/")
    imgs = "".join(f'<img src="/job/{job_id}/pageimg/{doc}/{i}" style="width:100%;max-width:820px;display:block;margin:0 auto 14px;border:1px solid #26304f;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.4)">'
                   for i in range(len(pages)))
    which = "CV" if doc == "cv" else "Application Letter"
    body = f"""
    <a class=back href="/job/{job_id}">&larr; back to draft</a>
    <h1 style=margin-top:8px>&#128065; {which} &mdash; {esc(row['title'])}</h1>
    <div class=sub>The document below is exactly what the employer receives.</div>
    <div class=actions style="margin:8px 0 14px">
      <a class="btn" style="background:#123d2c;color:#7ef0b8" href="/job/{job_id}/download/{doc}">&#11015; Download this {('CV' if doc == 'cv' else 'letter')} as PDF</a>
      <a class="btn" style="background:#243055;color:#bcd0ff" href="/job/{job_id}">&larr; back to the draft</a>
    </div>
    <div class=sub>To save on a phone: long-press an image &rarr; Save/Share. In this chat preview, PDF downloads may be blocked &mdash; use the long-press save, or the ready files in the <code>manual_apply</code> folder.</div>
    {imgs}"""
    return SHELL.format(css=CSS, body=body)


@app.route("/job/<int:job_id>/pageimg/<doc>/<int:n>")
def page_img(job_id, doc, n):
    p = os.path.join("data", "applications", f"job_{job_id}", f"view_{doc}_{n}.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return Response("gone", status=404)



@app.route("/job/<int:job_id>/edit", methods=["GET", "POST"])
def edit_draft(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row:
        return redirect("/")
    if request.method == "POST":
        store.update(conn, job_id,
                     cv_md=request.form.get("cv", ""),
                     letter_md=request.form.get("letter", ""))
        store.log_event(conn, job_id, "edited", "manual edit before approval")
        if request.form.get("then") == "approve":
            return _approve_and_maybe_send(conn, store.job_by_id(conn, job_id))
        return redirect(f"/job/{job_id}?msg=" + q("💾 Draft saved. Review it, then approve when satisfied."))
    EDIT_TMPL = """<a class=back href="/job/__JOBID__">← back to draft</a>
    <h1 style=margin-top:8px>✏️ Edit draft — __TITLE__</h1>
    <div class=sub>Type on the left — the final document updates live on the right. Use the buttons for bold / italics so you never touch the markers yourself.</div>
    <form method=post>
    <h2>📝 CV</h2>
    <div class=editgrid>
      <div>
        <div class=toolbar>
          <button type=button class=tbtn onclick="wrapSel('cvta','**','**')" title="Bold selection">B</button>
          <button type=button class=tbtn onclick="linePre('cvta','# ')" title="Big name line">Name</button>
          <button type=button class=tbtn onclick="linePre('cvta','## ')" title="Section heading">Section</button>
          <button type=button class=tbtn onclick="linePre('cvta','• ')" title="Round dot bullet">• Bullet</button>
          <button type=button class=tbtn onclick="clearFmt('cvta')" title="Strip formatting markers from selection">✗ Clear style</button>
        </div>
        <textarea id=cvta name=cv oninput="live('cvta','cvtaprev')">__CV_MD__</textarea>
        <div class=fmt>The saved draft uses plain capital headings and single round dot bullets. The buttons only add temporary markers here; the preview shows exactly what HR receives.</div>
      </div>
      <div>
        <div class=prevlabel>Live preview — exactly what HR receives</div>
        <div id=cvtaprev class=paper>__CV_PREV__</div>
      </div>
    </div>
    <h2>✉️ Application letter</h2>
    <div class=editgrid>
      <div>
        <div class=toolbar>
          <button type=button class=tbtn onclick="wrapSel('letta','**','**')">B</button>
          <button type=button class=tbtn onclick="clearFmt('letta')">✗ Clear style</button>
        </div>
        <textarea id=letta name=letter oninput="live('letta','lettaprev')">__LETTER_MD__</textarea>
        <div class=fmt>Letters are plain paragraphs — usually no formatting buttons needed.</div>
      </div>
      <div>
        <div class=prevlabel>Live preview — exactly what HR receives</div>
        <div id=lettaprev class=paper>__LETTER_PREV__</div>
      </div>
    </div>
    <div class=savebar>
      <button class=approve name="then" value="approve">💾 Save &amp; approve draft only</button>
      <button class="btn" style="background:#243055;color:#bcd0ff" name="then" value="save">💾 Save only</button>
    </div></form>
    <script>
    function escH(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
    function bold(t){return t.replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>');}
    function renderDoc(md){
      var sections={'PROFILE':1,'SKILLS':1,'EXPERIENCE':1,'EDUCATION':1,'ACADEMIC PROJECT':1,'SELECTED PROJECTS':1,'ADDITIONAL INFORMATION':1,'REFERENCES':1};
      var subheads={'Technical':1,'People and Communication':1};
      function isHead(t){
        if(!t||t.startsWith('http'))return false;
        if(t===t.toUpperCase()&&t.length<70&&t.indexOf(' ')>-1)return true;
        if(t.indexOf(',')>-1&&/(19|20)\\d{2}/.test(t)&&t.length<120)return true;
        if(/^(Bachelor|Diploma|Certificate|Master)/.test(t))return true;
        return false;
      }
      var out='',ul=false,first=true,seenSec=false;
      md.split('\\n').forEach(function(raw){
        var s=raw.replace(/\\s+$/,'');
        var t=s.trim();
        if(!t)return;
        if(first&&t.startsWith('# ')){if(ul){out+='</ul>';ul=false;}out+='<div class="dname">'+bold(escH(t.slice(2)))+'</div>';first=false;return;}
        if(first){if(ul){out+='</ul>';ul=false;}out+='<div class="dname">'+bold(escH(t))+'</div>';first=false;return;}
        if(t.startsWith('## ')){if(ul){out+='</ul>';ul=false;}out+='<div class="dsec">'+escH(t.slice(3)).toUpperCase()+'</div>';seenSec=true;return;}
        if(t.startsWith('### ')){if(ul){out+='</ul>';ul=false;}out+='<div class="dsub">'+bold(escH(t.slice(4)))+'</div>';seenSec=true;return;}
        if(sections[t]){if(ul){out+='</ul>';ul=false;}out+='<div class="dsec">'+escH(t)+'</div>';seenSec=true;return;}
        if(subheads[t]||isHead(t)){if(ul){out+='</ul>';ul=false;}out+='<div class="dsub">'+bold(escH(t))+'</div>';seenSec=true;return;}
        if(t.startsWith('• ')||t.startsWith('- ')){
          if(!ul){out+='<ul>';ul=true;}
          out+='<li>'+bold(escH(t.slice(2)))+'</li>';return;
        }
        if(ul){out+='</ul>';ul=false;}
        if(!seenSec&&(/@|·/.test(t)||/\\+?\\d[\\d\\s-]{7,}/.test(t))){out+='<div class="dcontact">'+bold(escH(t))+'</div>';return;}
        if(!seenSec){out+='<div class="dhead">'+bold(escH(t))+'</div>';return;}
        out+='<p>'+bold(escH(t))+'</p>';
      });
      if(ul)out+='</ul>';
      return out;
    }
    function live(taId,pvId){var ta=document.getElementById(taId),pv=document.getElementById(pvId);pv.innerHTML=renderDoc(ta.value);}
    function wrapSel(taId,b,a){var ta=document.getElementById(taId);var s=ta.selectionStart,e=ta.selectionEnd;
      var sel=ta.value.slice(s,e)||'text';ta.value=ta.value.slice(0,s)+b+sel+a+ta.value.slice(e);
      ta.selectionStart=s+b.length;ta.selectionEnd=s+b.length+sel.length;ta.focus();live(taId,taId+'prev');}
    function linePre(taId,pre){var ta=document.getElementById(taId);var v=ta.value,s=ta.selectionStart;
      var ls=v.lastIndexOf('\\n',s-1)+1,le=v.indexOf('\\n',s);if(le===-1)le=v.length;
      var line=v.slice(ls,le);var plain=line.replace(/^(#{1,2}\\s*|-\\s*|\\s*-\\s*|•\\s*)/,'');
      var nl=line.startsWith(pre)?plain:pre+plain;
      ta.value=v.slice(0,ls)+nl+v.slice(le);ta.selectionStart=ta.selectionEnd=ls+nl.length;ta.focus();live(taId,taId+'prev');}
    function clearFmt(taId){var ta=document.getElementById(taId);var s=ta.selectionStart,e=ta.selectionEnd;
      if(s===e){s=0;e=ta.value.length;}
      var sel=ta.value.slice(s,e).replace(/\\*\\*(.+?)\\*\\*/g,'$1').replace(/\\*(.+?)\\*/g,'$1');
      ta.value=ta.value.slice(0,s)+sel+ta.value.slice(e);ta.focus();live(taId,taId+'prev');}
    live('cvta','cvtaprev');live('letta','lettaprev');
    </script>"""
    _cv_prev = md_html(row["cv_md"] or "")
    _lt_prev = md_html(row["letter_md"] or "")
    body = (EDIT_TMPL
            .replace("__JOBID__", str(job_id))
            .replace("__TITLE__", esc(row["title"]))
            .replace("__CV_MD__", esc(row["cv_md"]))
            .replace("__LETTER_MD__", esc(row["letter_md"]))
            .replace("__CV_PREV__", _cv_prev[len('<div class="paper">'):-6] if _cv_prev else "")
            .replace("__LETTER_PREV__", _lt_prev[len('<div class="paper">'):-6] if _lt_prev else ""))
    return SHELL.format(css=CSS, body=body)


def _approve_and_maybe_send(conn, row):
    """Mark the draft approved. Sending stays a separate, deliberate action."""
    job_id = row["id"]
    try:
        store.update(conn, job_id, status="approved")
        store.log_event(conn, job_id, "approved")
    except Exception as exc:
        print(f"[approve] ERROR job {job_id}: {exc}", flush=True)
        return redirect(f"/job/{job_id}?msg=" + q(
            "Could not save the approval (the database was busy). Click Approve again in a moment."))
    return redirect(f"/job/{job_id}?msg=" + q(
        "APPROVED. This draft has moved out of the Pending review list. "
        "Review the documents, then use the button below to send or open the application form."))


@app.route("/job/<int:job_id>/sendemail", methods=["POST"])
def send_approved_email(job_id):
    """A separate deliberate action for email-based applications."""
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row or row["status"] != "approved":
        return redirect(f"/job/{job_id}?msg=" + q("Approve the draft before sending it."))
    if not row["apply_email"] or not sender_mod.email_configured():
        return redirect(f"/job/{job_id}?msg=" + q("No configured application email for this posting. Use the website review flow instead."))
    res = sender_mod.send_application(dict(row), row["cv_md"], row["letter_md"])
    if res["ok"]:
        store.update(conn, job_id, status="sent")
        store.log_event(conn, job_id, "sent", res["detail"])
        sender_mod.queue_application_result("submitted", row["title"], row["company"], res["detail"], job_id=job_id)
        return redirect(f"/job/{job_id}?msg=" + q("Email application sent. Check the Activity log for proof."))
    store.log_event(conn, job_id, "send_failed", res["detail"])
    return redirect(f"/job/{job_id}?msg=" + q(f"Sending failed: {res['detail']}"))


@app.route("/job/<int:job_id>/approve", methods=["POST"])
def approve(job_id):
    """Explicit route: never relies on a generic <action> catch-all."""
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if not row:
        return redirect("/?tab=pending&msg=" + q("That job no longer exists."))
    if row["status"] not in ("pending", "approved"):
        return redirect(f"/job/{job_id}?msg=" + q("Only pending drafts can be approved."))
    return _approve_and_maybe_send(conn, row)


@app.route("/job/<int:job_id>/reject", methods=["POST"])
def reject(job_id):
    conn = store.connect()
    row = store.job_by_id(conn, job_id)
    if row:
        try:
            store.update(conn, job_id, status="rejected")
            store.log_event(conn, job_id, "rejected")
        except Exception as exc:
            print(f"[reject] ERROR job {job_id}: {exc}", flush=True)
    return redirect("/?tab=pending&msg=" + q("Draft rejected."))


@app.route("/notify/digest", methods=["POST"])
def digest():
    conn = store.connect()
    rows = conn.execute("SELECT id, title, company, status FROM jobs WHERE status IN ('pending','approved','sent') ORDER BY status, score DESC").fetchall()
    ok = sender_mod.send_digest([dict(r) for r in rows])
    msg = "📧 Digest emailed to you!" if ok else "⚠ Could not send digest (check email settings)."
    return redirect("/?tab=pending&msg=" + q(msg))


# ---------------------------------------------------------------- scheduler
def _seconds_until(hhmm: str) -> float:
    import datetime as dt
    now = dt.datetime.now()
    h, m = map(int, hhmm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def _autopilot_wait_seconds(sched: dict) -> float:
    mode = (sched.get("mode") or "daily").lower()
    if mode == "interval":
        return max(0.5, float(sched.get("interval_hours", 4))) * 3600
    return _seconds_until(sched.get("time", "07:00"))


def _daily_autopilot():
    """Runs inside the dashboard process: scheduled search -> AI drafts -> digest."""
    import time as _t
    first_run = True
    while True:
        try:
            cfg = load_settings(refresh=True)
            sched = cfg.get("schedule", {}) or {}
            if not sched.get("enabled", False):
                _t.sleep(300)
                continue
            wait = 0 if first_run and sched.get("run_on_startup", True) else _autopilot_wait_seconds(sched)
            mode = (sched.get("mode") or "daily").lower()
            print(f"[scheduler] mode={mode} — next run in {wait/3600:.1f}h", flush=True)
            end = _t.time() + wait
            while _t.time() < end:
                _t.sleep(min(60, max(0, end - _t.time())))
            print("[scheduler] starting run...", flush=True)
            first_run = False
            summary = run_search.run(verbose=False)
            conn = store.connect()
            if sched.get("retry_template_drafts_with_ai", True) and tailor.ai_available():
                for row in conn.execute(
                        "SELECT * FROM jobs WHERE status='pending' AND (engine IS NULL OR engine!='ai') LIMIT 10").fetchall():
                    res = tailor.generate(dict(row))
                    store.update(conn, row["id"], cv_md=res["cv_md"],
                                 letter_md=res["letter_md"], engine=res["engine"])
                    _t.sleep(5)
            # email only when there is something new (avoid inbox spam)
            if summary.get("drafted", 0) > 0 or mode != "interval":
                rows = conn.execute("SELECT id,title,company,status FROM jobs WHERE status='pending' ORDER BY score DESC").fetchall()
                sender_mod.send_digest(
                    [dict(r) for r in rows],
                    header=(f"🤖 Agent run complete — {summary.get('new',0)} new jobs found, "
                            f"{summary.get('drafted',0)} new drafts ready for your approval:"))
                print("[scheduler] digest sent", flush=True)
        except Exception as e:
            print("[scheduler] ERROR:", e, flush=True)
            _t.sleep(1800)


# ---------------------------------------------------------------- WhatsApp inbox
@app.route("/whatsapp")
def whatsapp_page():
    try:
        inbox = open(whatsapp.INBOX, encoding="utf-8", errors="ignore").read()
    except Exception:
        inbox = ""
    msg = request.args.get("msg", "")
    flash = f"<div class=flash>{esc(msg)}</div>" if msg else ""
    ai_note = ("AI is ON — the messy text is read by the AI, which keeps only the real vacancies."
               if whatsapp._llm_available() else
               "AI is OFF (no LLM key) — the built-in filter is used; it still drops jokes and forwards.")
    try:
        media_count = len([f for f in os.listdir(whatsapp.MEDIA_DIR) if whatsapp._is_image(f)])
    except Exception:
        media_count = 0
    body = f"""
    <a class=back href="/">← back to list</a>
    <h1 style=margin-top:8px>💬 WhatsApp job-channel inbox</h1>
    <div class=sub>Copy messages from your WhatsApp job channels (jokes, forwards, adverts and all),
    paste them below, and the agent keeps the real vacancies — then drafts a tailored CV + letter for
    each, exactly like the normal flow. No link needed.</div>
    {flash}
    <div class=flash>🔎 {esc(ai_note)}</div>
    <form method=post action="/whatsapp">
      <textarea name=text placeholder="Paste the copied WhatsApp messages here..."></textarea>
      <div class=savebar>
        <button class=approve>🔎 Filter &amp; add jobs</button>
        <label style="margin-left:12px;color:var(--mut);font-size:.9rem">
          <input type=checkbox name=save value=1> also save to the inbox file</label>
      </div>
    </form>
    <h2>📄 Current inbox file</h2>
    <div class=doc style=max-height:200px>{esc(inbox) or '— empty —'}</div>
    <div class=flash style=margin-top:12px>📷 <b>{media_count}</b> image advert(s) waiting in
    <code>data/whatsapp_media/</code> — each is read by AI vision when you click the button
    (it needs an AI key). Processed images move to that folder's <code>processed/</code> subfolder.</div>
    <div class=fmt>Tip: tick “also save to the inbox file” and every scheduled run keeps checking it,
    so new channel messages you paste get picked up automatically. Lines starting with # are ignored
    (that is how the instructions at the top of the file stay hidden from the parser).</div>
    """
    return SHELL.format(css=CSS, body=body)


@app.route("/whatsapp", methods=["POST"])
def whatsapp_ingest():
    text = request.form.get("text", "") or ""
    if request.form.get("save"):
        os.makedirs(os.path.dirname(whatsapp.INBOX), exist_ok=True)
        with open(whatsapp.INBOX, "w", encoding="utf-8") as f:
            f.write(text)
    try:
        res = whatsapp.analyze(text)
    except Exception as e:
        res = {"jobs": [], "messages": 0, "dropped": 0, "engine": f"error: {e}"}
    try:
        media = whatsapp.analyze_media()
    except Exception:
        media = {"jobs": [], "files": 0, "processed": 0, "engine": "n/a"}
    jobs = res["jobs"] + media["jobs"]
    try:
        whatsapp.enrich(jobs)
    except Exception:
        pass
    conn = store.connect()
    added = 0
    for j in jobs:
        if store.upsert_job(conn, {"source": j.source, "url": j.url, "title": j.title,
                                   "company": j.company, "location": j.location,
                                   "description": j.description, "apply_url": j.apply_url or j.url,
                                   "apply_email": j.apply_email, "posted_date": j.posted_date,
                                   "remote": j.remote, "salary": j.salary}):
            added += 1
    summary = run_search.process_new(verbose=False) if added else {"drafted": 0}
    listed = "".join(
        f"<div class=card style=border-left-color:var(--ok)><h3>{esc(j.title)}</h3>"
        f"<div class=co>{esc(j.company or '—')} · {esc(j.location or '—')}"
        f"{(' · ' + esc(j.apply_email)) if j.apply_email else ''}</div>"
        f"<div class=reasons>{esc((j.description or '')[:220])}…</div></div>"
        for j in jobs[:40]) or '<div class=empty>No genuine job vacancies found.</div>'
    body = f"""
    <a class=back href="/whatsapp">← paste more</a>
    <h1 style=margin-top:8px>💬 WhatsApp scan results</h1>
    <div class=stats>
      <div class=stat><b>{res['messages']}</b><span>messages read</span></div>
      <div class=stat><b>{len(jobs)}</b><span>jobs found</span></div>
      <div class=stat><b>{res['dropped']}</b><span>noise dropped</span></div>
      <div class=stat><b>{media['processed']}</b><span>images read</span></div>
      <div class=stat><b>{added}</b><span>new to pipeline</span></div>
    </div>
    <div class=flash>Engine: <b>{esc(res['engine'])}</b> · {summary.get('drafted', 0)} draft(s)
    generated. New drafts are waiting for your approval.</div>
    <div class=bar><a class="tab on" href="/?tab=pending">📝 Go to pending review</a></div>
    {listed}
    """
    return SHELL.format(css=CSS, body=body)


@app.route("/run", methods=["POST"])
def run():
    summary = run_search.run(verbose=False)
    return redirect(f"/?tab=pending&ran=1")


if __name__ == "__main__":
    import threading
    threading.Thread(target=_daily_autopilot, daemon=True).start()
    try:
        _cfg = load_settings()
        _port = int((_cfg.get("dashboard") or {}).get("port", 7860))
    except Exception:
        _port = 7860
    app.run(host="0.0.0.0", port=_port, debug=False)
