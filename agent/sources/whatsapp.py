"""WhatsApp channel source.

WhatsApp Channels have no public API and no RSS feed, so there is no way to
"scrape" them like MyJobMag. Instead you copy the channel's messages and paste
them into the agent:

  * the dashboard  ->  the "WhatsApp inbox" page, or
  * the drop file  ->  data/whatsapp_inbox.txt

Real WhatsApp job channels mix genuine vacancies with greetings, jokes,
forwards, memes and pure chatter. This module separates the two:

  1. split the blob into individual messages,
  2. drop the noise (chit-chat, jokes, forwards, media-only posts),
  3. pull out each real advert's title, company, location, description,
     apply link/email and any deadline,
  4. hand the survivors to the normal pipeline for scoring + drafting.

Like tailor.py there are two engines: a transparent rule-based parser that
always runs offline, upgraded by an AI extractor whenever an LLM key is set
(the AI is much better at ignoring jokes and only keeping true vacancies).
"""
import hashlib
import json
import os
import re
import time
from datetime import date, datetime

import yaml

from ..models import Job

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.config import load_settings  # noqa: E402


def _load_yaml(name: str) -> dict:
    """Shared loader: example fallback, env overrides, placeholders stripped."""
    try:
        from agent.config import load_settings
        return load_settings()
    except Exception:
        return {}


SETTINGS = _load_yaml("settings.yaml")
_WA = (SETTINGS.get("whatsapp") or {}) if isinstance(SETTINGS, dict) else {}
INBOX = os.path.join(ROOT, _WA.get("inbox_file") or os.path.join("data", "whatsapp_inbox.txt"))
MEDIA_DIR = os.path.join(ROOT, _WA.get("media_dir") or os.path.join("data", "whatsapp_media"))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0; personal job-search tool)"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}

# ---- regex building blocks ---------------------------------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
# "[05/10/2026, 09:14:22] Name:" or "05/10/2026, 09:14 - Name:"
HEADER_RE = re.compile(
    r"^\[?\d{1,2}[/.]\d{1,2}[/.]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?\]?\s*[-–]?\s*[^:\n]{0,40}:")
# lines that start a fresh advert inside one big block
OPENERS_RE = re.compile(
    r"^\s*(?:[*•\-–]\s*)?(?:WE\s+ARE\s+HIRING|WE'?RE\s+HIRING|NOW\s+HIRING|HIRING|VACAN(?:CY|CIES)|"
    r"JOB\s+(?:TITLE|ADVERT|OPPORTUNITY|VACANCY|DESCRIPTION)|OPEN\s+POSITION|POSITION|"
    r"URGENT(?:LY)?|RECRUIT(?:MENT|ING)|NEW\s+JOB|CALL\s+FOR)\b", re.I)

MEDIA_MARKERS = ("<media omitted>", "image omitted", "photo omitted", "video omitted",
                 "audio omitted", "sticker omitted", "document omitted", "gif omitted",
                 "\u200eimage omitted", "this message was deleted", "missed voice call")

NOISE_PHRASES = (
    "forwarded many times", "forwarded", "join this channel", "join our channel", "join the channel",
    "subscribe", "follow this channel", "follow us", "for more jobs join", "for more info join",
    "for more updates", "good morning", "good afternoon", "good evening", "good night", "goodmorning",
    "have a blessed", "blessed day", "happy birthday", "happy new month", "happy new year",
    "rest in peace", "rip ", "condolences", "admin", "hii everyone", "hi all", "hello members",
    "hey guys", "test message", "ignore this", "this is a test",
)

STRONG_SIGNALS = (
    "send your cv", "send cv", "send your resume", "send resume", "send your application",
    "send application", "email your cv", "email cv", "apply via", "apply through",
    "apply on or before", "apply before", "apply by", "apply now", "apply here",
    "applications are invited", "invites applications", "interested candidates",
    "qualified candidates", "suitable candidates", "qualified persons", "how to apply",
    "we are hiring", "we're hiring", "we are looking for", "we are seeking", "is hiring",
    "are hiring", "we are recruiting", "is recruiting", "job title", "job advert",
    "job opportunity", "job vacancy", "job vacancies", "vacancy exists", "position:",
    "vacancy:", "deadline", "closing date", "application deadline", "applications close",
    "qualifications", "responsibilities", "duties", "job description", "terms of reference",
    "salary", "ksh", "kes ", "per month", "monthly", "stipend", "gross pay",
    "remuneration", "basic pay", "allowance", "full time", "part time", "contractual",
    "attach your", "submit your application", "send your application letter",
)

ROLE_WORDS = {
    "intern", "internship", "attachment", "attach", "trainee", "graduate", "fresher", "entry",
    "junior", "officer", "assistant", "administrator", "admin", "support", "helpdesk",
    "technician", "technologist", "developer", "programmer", "engineer", "analyst", "designer",
    "architect", "consultant", "coordinator", "supervisor", "manager", "clerk", "receptionist",
    "secretary", "accountant", "auditor", "cashier", "teller", "driver", "messenger", "salesman",
    "saleswoman", "sales", "marketer", "marketing", "teacher", "tutor", "nurse", "pharmacist",
    "lab", "laboratory", "chef", "cook", "waiter", "waitress", "housekeeper", "security", "guard",
    "cleaner", "storekeeper", "procurement", "logistics", "dispatch", "data", "ict", "network",
    "systems", "software", "web", "mobile", "trainer", "facilitator", "community", "field",
    "research", "monitoring", "evaluation", "records", "archives", "customer", "operations",
    "production", "quality", "maintenance", "electrician", "plumber", "welder", "mechanic",
    "operator", "surveyor", "quantity", "foreman", "human resource", "hr", "payroll", "finance",
    "credit", "loan", "insurance", "banking", "microfinance", "sacco", "communication",
    "journalist", "reporter", "editor", "photographer", "videographer", "graphic", "animator",
    "icto", "ict support", "ict assistant", "volunteer", "casual",
}
ROLE_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(w) for w in ROLE_WORDS), key=len, reverse=True)) + r")\b", re.I)

TOWNS = (
    "nairobi", "kiambu", "mombasa", "kisumu", "nakuru", "uasin gishu", "nyeri", "meru", "kajiado",
    "machakos", "murang'a", "muranga", "kericho", "bungoma", "kakamega", "kisii", "laikipia", "embu",
    "kitui", "kilifi", "kwale", "garissa", "wajir", "mandera", "marsabit", "isiolo", "turkana",
    "west pokot", "trans nzoia", "baringo", "nandi", "siaya", "homa bay", "migori", "nyamira",
    "kirinyaga", "nyandarua", "narok", "bomet", "vihiga", "busia", "lamu", "taita", "taveta",
    "samburu", "kerugoya", "voi", "naivasha", "thika", "kitengela", "eldoret", "ruiru", "juja",
    "athi river", "mlolongo", "syokimau", "kitale", "malindi", "diani", "ngong", "kikuyu",
)
TOWNS_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(TOWNS, key=len, reverse=True)) + r")\b", re.I)

DATE_TOKEN = r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4})"
DEADLINE_RE = re.compile(r"(?:deadline|closing date|closes?|apply (?:on or )?before|apply by|"
                         r"application deadline|last date|due date|submit by)\D{0,25}" + DATE_TOKEN, re.I)
POSTED_RE = re.compile(r"(?:posted|advertised|published|date posted|date advertised)\D{0,15}" + DATE_TOKEN, re.I)

TITLE_LABEL_RE = re.compile(r"^\s*(?:job\s*title|position|role|vacancy|title|post)\s*[:\-–]\s*(.+)$", re.I | re.M)
HIRING_FOR_RE = re.compile(r"\b(?:hiring|recruiting|seeking|looking for|vacancy for|position for|"
                           r"vacancies for)\s+(?:a|an|the)?\s*([A-Za-z][\w /&+.\-]{2,60})", re.I)
COMPANY_LABEL_RE = re.compile(r"^\s*(?:company|organisation|organization|employer|firm|institution|"
                              r"agency)\s*[:\-–]\s*(.+)$", re.I | re.M)
ORG_SUFFIX_RE = re.compile(
    r"\b([A-Z][A-Za-z&',.\-]*(?:\s+[A-Z][A-Za-z&',.\-]*){0,4}\s+(?:Limited|Ltd|PLC|Plc|Company|Corporation|"
    r"Corp|Group|Holdings|Agency|Bank|University|College|Hospital|Sacco|SACCO|Authority|Commission|"
    r"Ministry|Foundation|Trust|Cent(?:re|er)|Institute|Services|Solutions|Technologies|Enterprises|"
    r"Consultants|Associates|Partners|Kenya|International))\b")
IS_HIRING_RE = re.compile(r"\b([A-Z][A-Za-z&',.\-]*(?:[ \t]+[A-Z][A-Za-z&',.\-]*){0,4})[ \t]+(?:is|are)[ \t]+"
                          r"(?:hiring|recruiting|looking|seeking)\b")
LOC_LABEL_RE = re.compile(r"^\s*(?:location|duty station|work station|station|based in|based at|"
                          r"town|city|county|place)\s*[:\-–]\s*(.+)$", re.I | re.M)


def read_inbox() -> str:
    """Read the drop file, ignoring comment lines (start with #)."""
    try:
        raw = open(INBOX, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""
    return "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("#"))


def split_messages(text: str) -> list[str]:
    """Best-effort split of a copied channel blob into individual messages."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    chunks: list[str] = []
    for block in re.split(r"\n{2,}", text):
        lines, cur = block.split("\n"), []
        for ln in lines:
            if HEADER_RE.match(ln.strip()):
                if cur:
                    chunks.append("\n".join(cur).strip())
                cur = [HEADER_RE.sub("", ln, count=1).strip()]
            else:
                cur.append(ln)
        if cur:
            chunks.append("\n".join(cur).strip())
    # a single huge block with no blank lines: break it at advert openers
    out: list[str] = []
    for c in chunks:
        if len(c) > 1200:
            parts, buf = [], []
            for ln in c.split("\n"):
                if OPENERS_RE.match(ln) and buf:
                    parts.append("\n".join(buf).strip())
                    buf = [ln]
                else:
                    buf.append(ln)
            if buf:
                parts.append("\n".join(buf).strip())
            out.extend(parts)
        else:
            out.append(c)
    return [c for c in out if c.strip()]


# ---- small helpers -----------------------------------------------------------
def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip(" *_•-–—:.|")


def _parse_any_date(s: str) -> str:
    """Best-effort date -> ISO, only when a year is present (never guess a year)."""
    s = _clean_line(s)
    s = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", s, flags=re.I)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d",
                "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})", s)
    if m:
        return _parse_any_date(m.group(1))
    m = re.search(r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", s)
    if m:
        return _parse_any_date(m.group(1))
    return ""


def _has_signal(low: str) -> bool:
    return any(s in low for s in STRONG_SIGNALS) or bool(ROLE_RE.search(low))


def looks_like_job(msg: str) -> tuple[bool, dict]:
    """Decide whether one message is a genuine advert (vs joke/chatter/forward)."""
    low = (msg or "").lower()
    meta: dict = {}
    if any(mk in low for mk in MEDIA_MARKERS) and not _has_signal(low):
        return False, {"reason": "media only"}
    if len(msg.strip()) < 25:
        return False, {"reason": "too short"}
    strong = sum(1 for s in STRONG_SIGNALS if s in low)
    roles = len(set(m.group(0).lower() for m in ROLE_RE.finditer(low)))
    has_contact = bool(EMAIL_RE.search(msg) or URL_RE.search(msg))
    has_deadline = bool(DEADLINE_RE.search(msg))
    meta.update(strong=strong, roles=roles, contact=has_contact, deadline=has_deadline)
    noise = any(p in low for p in NOISE_PHRASES)
    if noise and strong == 0 and roles < 2:
        return False, {"reason": "chatter/joke"}
    keep = (strong >= 1 and roles >= 1) or (strong >= 2) or (roles >= 2 and has_contact)
    return keep, meta


def _email(msg: str) -> str:
    for e in EMAIL_RE.findall(msg):
        el = e.lower()
        if el.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        if "example" in el or "whatsapp" in el:
            continue
        return e
    return ""


def _link(msg: str) -> str:
    urls = [u.rstrip(".,);]") for u in URL_RE.findall(msg)]
    for u in urls:
        if re.search(r"apply|career|vacanc|job|recruit|forms?\.|greenhouse|lever|workable|smartrecruit", u, re.I):
            return u
    return urls[0] if urls else ""


GENERIC_TITLES = {"vacancy", "vacancies", "job", "jobs", "position", "positions", "opening",
                  "openings", "we are hiring", "we're hiring", "now hiring", "hiring",
                  "job alert", "job opportunity", "recruitment"}
LEAD_LABEL_RE = re.compile(
    r"^\s*(?:urgent(?:ly)?\s*)?(?:vacanc(?:y|ies)|job\s*(?:vacancy|opportunity|opening|alert)?|"
    r"position|post|we\s+are\s+hiring|now\s+hiring|hiring|recruiting|recruitment)\s*[:\-–]?\s*", re.I)


def _prettify_title(t: str) -> str:
    """Drop noisy lead-ins like 'URGENT VACANCY - ' / 'WE ARE HIRING: ' from a title."""
    raw = _clean_line(t)
    cleaned = _clean_line(LEAD_LABEL_RE.sub("", raw))
    return cleaned or raw


def _extract_title(msg: str) -> str:
    m = TITLE_LABEL_RE.search(msg)
    if m and m.group(1).strip():
        return _prettify_title(m.group(1))[:90]
    # first line that reads like a role (the strongest, most human-readable title)
    for ln in msg.split("\n"):
        t = _clean_line(ln)
        if not (3 <= len(t) <= 95) or EMAIL_RE.search(t) or URL_RE.search(t):
            continue
        if t.lower() in GENERIC_TITLES:
            continue
        if ROLE_RE.search(t) or t.isupper():
            if not any(p in t.lower() for p in NOISE_PHRASES):
                pt = _prettify_title(t)
                if pt:
                    return pt[:90]
    m = HIRING_FOR_RE.search(msg)
    if m and m.group(1).strip():
        return _prettify_title(m.group(1))[:90]
    for ln in msg.split("\n"):
        t = _clean_line(ln)
        if 3 <= len(t) <= 95 and not EMAIL_RE.search(t) and not URL_RE.search(t):
            return _prettify_title(t)[:90]
    return ""


_BAD_COMPANY = {"we", "they", "it", "i", "the", "this", "that", "our", "your", "you", "he", "she",
                "here", "there", "remote", "online", "company", "organization", "organisation",
                "employer", "firm", "institution", "agency", "job", "vacancy", "position", "deadline"}


def _valid_company(c: str) -> str:
    c = _clean_line(c)
    if len(c) < 3 or c.lower() in _BAD_COMPANY or c.lower() in TOWNS:
        return ""
    return c[:80]


def _extract_company(msg: str, title: str) -> str:
    m = COMPANY_LABEL_RE.search(msg)
    if m and m.group(1).strip():
        v = _valid_company(m.group(1))
        if v:
            return v
    if title and " at " in title:
        v = _valid_company(title.rsplit(" at ", 1)[1])
        if v:
            return v
    m = IS_HIRING_RE.search(msg)
    if m:
        v = _valid_company(m.group(1))
        if v:
            return v
    m = ORG_SUFFIX_RE.search(msg)
    if m:
        v = _valid_company(m.group(1))
        if v:
            return v
    return ""


def _extract_location(msg: str) -> str:
    m = LOC_LABEL_RE.search(msg)
    if m and m.group(1).strip():
        return _clean_line(m.group(1))[:60]
    low = msg.lower()
    m = TOWNS_RE.search(low)
    if m:
        return m.group(1).title()
    if re.search(r"\bkenya\b", low):
        return "Kenya"
    if re.search(r"\bremote|work from home|wfh|home based\b", low):
        return "Remote"
    return ""


def _clean_desc(msg: str) -> str:
    """Tidy a raw message into a description block for the drafting engine."""
    lines = []
    for ln in (msg or "").split("\n"):
        t = re.sub(r"[ \t]+", " ", ln).rstrip()
        if t:
            lines.append(t)
    return "\n".join(lines)[:6000]


def _stable_url(title: str, company: str, desc: str) -> str:
    key = re.sub(r"\W+", " ", f"{title} {company} {desc[:200]}".lower()).strip()
    return "whatsapp://" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _expired(iso: str) -> bool:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").date() < date.today()
    except ValueError:
        return False


def _job_from_rules(msg: str):
    """Turn one advert message into a Job, or None if its deadline has passed."""
    dl = DEADLINE_RE.search(msg)
    if dl:
        iso = _parse_any_date(dl.group(1))
        if iso and _expired(iso):
            return None
    title = _extract_title(msg)
    company = _extract_company(msg, title)
    if title and company and title.lower().endswith(" at " + company.lower()):
        title = title[: -(len(company) + 4)].strip()
    loc = _extract_location(msg)
    posted_m = POSTED_RE.search(msg)
    posted = _parse_any_date(posted_m.group(1)) if posted_m else ""
    if not posted and _WA.get("assume_posted_today", True):
        posted = date.today().isoformat()
    desc = _clean_desc(msg)
    return Job(
        source="whatsapp",
        url=_stable_url(title or desc[:60], company, desc),
        title=title or "Job vacancy (from WhatsApp channel)",
        company=company, location=loc, description=desc,
        apply_url=_link(msg), apply_email=_email(msg), posted_date=posted,
        remote=(loc == "Remote"),
    )


def _job_from_item(item: dict):
    """Build a Job from one AI-extracted JSON object."""
    title = _clean_line(item.get("title") or "")
    if not title:
        return None
    dl = _clean_line(item.get("deadline") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", dl) and _expired(dl[:10]):
        return None
    company = _clean_line(item.get("company") or "")
    desc = _clean_line(item.get("description") or "") or title
    loc = _clean_line(item.get("location") or "")
    email = _clean_line(item.get("apply_email") or "")
    if not EMAIL_RE.fullmatch(email or "x"):
        email = ""
    link = _clean_line(item.get("apply_url") or "")
    posted = date.today().isoformat() if _WA.get("assume_posted_today", True) else ""
    return Job(
        source="whatsapp",
        url=_stable_url(title, company, desc),
        title=title[:120], company=company, location=loc, description=desc,
        apply_url=link, apply_email=email, posted_date=posted, remote=(loc == "Remote"),
    )


def _dedupe(jobs: list) -> list:
    seen, out = set(), []
    for j in jobs:
        if j.url in seen:
            continue
        seen.add(j.url)
        out.append(j)
    return out


# ---- AI extractor (optional, mirrors tailor.py) ------------------------------
LLM_SYSTEM = (
    "You are a data extractor for a job-hunting assistant. The user pastes the raw text of many "
    "WhatsApp messages from job channels. Those messages mix REAL job vacancies with greetings, "
    "jokes, forwards, memes, adverts, religion, politics and pure chatter. Extract ONLY genuine job "
    "vacancies a person could actually apply for. Ignore everything that is not a vacancy. For each "
    "real vacancy return an object with keys: title, company, location, description (1-3 sentences of "
    "the real duties/requirements), apply_email, apply_url, deadline (YYYY-MM-DD or empty). "
    "Return ONLY a JSON array. If there are no real vacancies, return []."
)

VISION_PROMPT = (
    "The attached image is a screenshot or photo of a WhatsApp job advert. Read all the text in the "
    "image and extract ONLY the genuine job vacancy it advertises (ignore jokes, greetings or non-job "
    "content). Use the same JSON array format: title, company, location, description, apply_email, "
    "apply_url, deadline. If the image is not a job advert, return []."
)


def _llm_available() -> bool:
    llm = (load_settings().get("llm") or {})
    return bool(llm.get("api_key")) and llm.get("provider") in ("gemini", "openai")


def _llm_call(prompt: str, system: str) -> str:
    import requests
    llm = load_settings().get("llm") or {}
    provider, key = llm.get("provider"), llm.get("api_key")
    if provider == "gemini":
        model = llm.get("model", "gemini-3.8-flash")
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "systemInstruction": {"parts": [{"text": system}]},
                  "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.1}},
            timeout=120)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": llm.get("model", "gpt-4o-mini"),
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}],
                  "temperature": 0.1},
            timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("no LLM provider configured")


def _chunks(text: str, size: int = 6000) -> list:
    """Split a long paste on blank lines into LLM-sized chunks."""
    out, cur, n = [], [], 0
    for para in re.split(r"\n{2,}", text):
        if n and n + len(para) > size:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(para)
        n += len(para)
    if cur:
        out.append("\n\n".join(cur))
    return out


def _json_array(raw: str) -> list:
    """Pull a JSON array out of an LLM reply (tolerates extra prose/fences)."""
    m = re.search(r"\[.*\]", raw or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _ai_items(text: str) -> list:
    items = []
    for chunk in _chunks(text):
        try:
            raw = _llm_call(chunk, LLM_SYSTEM)
        except Exception:
            continue
        items.extend(_json_array(raw))
    return items


def _llm_vision(path: str) -> str:
    """Send one image to the configured LLM and return its (text) reply."""
    import base64
    import requests
    llm = SETTINGS.get("llm") or {}
    provider, key = llm.get("provider"), llm.get("api_key")
    ext = os.path.splitext(path)[1].lower()
    mime = MIME.get(ext, "image/png")
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    if provider == "gemini":
        model = llm.get("model", "gemini-2.0-flash")
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": VISION_PROMPT},
                                          {"inline_data": {"mime_type": mime, "data": b64}}]}],
                  "systemInstruction": {"parts": [{"text": LLM_SYSTEM}]}},
            timeout=90)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": llm.get("model", "gpt-4o-mini"),
                  "messages": [{"role": "system", "content": LLM_SYSTEM},
                               {"role": "user", "content": [
                                   {"type": "text", "text": VISION_PROMPT},
                                   {"type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"}}]}],
                  "temperature": 0.1},
            timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("no LLM provider configured")


# ---- image adverts (drop folder -> AI vision) --------------------------------
def _is_image(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def _mark_done(path: str):
    """Move a processed image into MEDIA_DIR/processed so it is not read twice."""
    import shutil
    done = os.path.join(MEDIA_DIR, "processed")
    try:
        os.makedirs(done, exist_ok=True)
        target = os.path.join(done, os.path.basename(path))
        if os.path.exists(target):
            base, ext = os.path.splitext(os.path.basename(path))
            target = os.path.join(done, f"{base}_{int(time.time())}{ext}")
        shutil.move(path, target)
    except Exception:
        pass


def analyze_media() -> dict:
    """Read screenshots/photos of image adverts from data/whatsapp_media/."""
    out = {"jobs": [], "files": 0, "processed": 0, "engine": "ai"}
    if not os.path.isdir(MEDIA_DIR):
        return out
    files = [f for f in sorted(os.listdir(MEDIA_DIR))
             if _is_image(f) and os.path.isfile(os.path.join(MEDIA_DIR, f))]
    out["files"] = len(files)
    if not files or not _WA.get("use_ai", True) or not _llm_available():
        if files:
            out["engine"] = "unavailable"
        return out
    jobs = []
    for name in files:
        path = os.path.join(MEDIA_DIR, name)
        try:
            raw = _llm_vision(path)
        except Exception:
            continue  # keep the file so a later run can retry
        for it in _json_array(raw):
            j = _job_from_item(it)
            if j:
                jobs.append(j)
        _mark_done(path)
        out["processed"] += 1
    out["jobs"] = _dedupe(jobs)
    return out


# ---- follow job-board links for the full advert ------------------------------
def _board(url: str) -> str:
    u = (url or "").lower()
    for name in ("myjobmag.co.ke", "brightermonday.co.ke", "fuzu.com", "remotive.com", "remoteok.com"):
        if name in u:
            return name.split(".")[0]
    return ""


def _generic_detail(url: str, delay: float):
    """Fetch an article page and return (text, email)."""
    import requests
    from bs4 import BeautifulSoup
    time.sleep(delay)
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for junk in soup.find_all(["script", "style", "nav", "footer", "form", "ins", "header"]):
        junk.decompose()
    node = (soup.select_one("article") or soup.select_one("main")
            or soup.select_one("[class*=job-description]") or soup.select_one("[class*=description]")
            or soup.body)
    text = node.get_text("\n", strip=True) if node else ""
    text = re.sub(r"\n{3,}", "\n\n", text)[:6000]
    return text, _email(text)


def _enrich_one(job, delay: float):
    link = (job.apply_url or "").strip()
    if not link.lower().startswith("http"):
        return
    board = _board(link)
    if not board:
        return
    try:
        if board == "myjobmag":
            from .myjobmag import fetch_detail
            time.sleep(delay)
            probe = Job(source="myjobmag", url=link, title=job.title, company=job.company,
                        location=job.location, description=job.description, apply_url=link)
            det = fetch_detail(probe)
            if len(det.description or "") > len(job.description or ""):
                job.description = det.description
            if det.apply_email and not job.apply_email:
                job.apply_email = det.apply_email
            if det.posted_date and not job.posted_date:
                job.posted_date = det.posted_date
        else:
            text, email = _generic_detail(link, delay)
            if len(text) > len(job.description or ""):
                job.description = text
            if email and not job.apply_email:
                job.apply_email = email
    except Exception:
        pass


def enrich(jobs: list, delay=None) -> list:
    """Follow known job-board links and pull the full advert details."""
    if not _WA.get("enrich_links", True):
        return jobs
    if delay is None:
        delay = float((SETTINGS.get("search") or {}).get("polite_delay_seconds", 1.5))
    for j in jobs:
        if _board(j.apply_url):
            _enrich_one(j, delay)
    return jobs


# ---- public API --------------------------------------------------------------
def analyze(text: str, use_ai=None) -> dict:
    """Return {'jobs', 'messages', 'dropped', 'engine', 'noise_examples'}."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    out = {"jobs": [], "messages": 0, "dropped": 0, "engine": "rules", "noise_examples": []}
    if not text:
        return out
    if use_ai is None:
        use_ai = bool(_WA.get("use_ai", True))
    messages = split_messages(text)
    out["messages"] = len(messages)

    if use_ai and _llm_available():
        jobs = [j for j in (_job_from_item(it) for it in _ai_items(text)) if j]
        if jobs:
            out["jobs"] = _dedupe(jobs)
            out["engine"] = "ai"
            # still report how much noise the rules would have found, for transparency
            out["dropped"] = sum(1 for m in messages if not looks_like_job(m)[0])
            return out

    jobs = []
    for m in messages:
        ok, _meta = looks_like_job(m)
        if not ok:
            out["dropped"] += 1
            if len(out["noise_examples"]) < 5 and len(m) < 120:
                out["noise_examples"].append(m[:80])
            continue
        j = _job_from_rules(m)
        if j:
            jobs.append(j)
    out["jobs"] = _dedupe(jobs)
    return out


def fetch(queries=None, delay=0, max_per_query=None) -> list:
    """Pipeline entry point.

    Reads the pasted inbox file AND the image drop folder, follows any known
    job-board links for the full advert, and returns the resulting jobs. Called
    with no arguments by run_search, so every scheduled run picks these up too.
    """
    jobs = []
    text = read_inbox()
    if text.strip():
        try:
            jobs += analyze(text)["jobs"]
        except Exception:
            pass
    try:
        jobs += analyze_media()["jobs"]
    except Exception:
        pass
    jobs = _dedupe(jobs)
    try:
        enrich(jobs)
    except Exception:
        pass
    if max_per_query:
        jobs = jobs[:max_per_query]
    return jobs
