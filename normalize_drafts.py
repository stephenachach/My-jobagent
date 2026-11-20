#!/usr/bin/env python3
"""One-off: normalize all pending drafts to the candidate's final CV format.

- Header: name / role titles / town / phone / email on five separate lines
- EXPERIENCE & ACADEMIC PROJECT: one bold "Role, Company (Period)" line,
  then plain sentences (no bullet markers) each ending with a full stop
- SKILLS & other bullets: keep "- " bullets, ensure full stops
"""
import re
import sqlite3
import sys

sys.path.insert(0, ".")

ROLE_KW = re.compile(r"\b(intern|internship|team leader|officer|developer|designer|"
                     r"analyst|trainee|programmer|administrator|technician|collector|"
                     r"collection officer|support|graphic designer)\b", re.I)
PERIOD_RE = re.compile(r"([A-Za-z]*\s?\d{4}\s*(?:to|–|—|-)\s*(?:[A-Za-z]+\s+)?(?:\d{4}|Present)|\b20\d\d\b)")


def _end_stop(line):
    s = line.rstrip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _parse_entry_header(header_lines):
    """Lines like '**KMC** - **ICT Intern**' / '**KMC — ICT Intern**' /
    '**KMC**' + '**ICT Intern** | May 2026 to July 2026'  ->  role, company, period."""
    joined = " ".join(h.strip() for h in header_lines if h.strip())
    period_m = PERIOD_RE.search(joined)
    period = period_m.group(1).strip() if period_m else ""
    # drop the period and ANY parenthetical remnants, collect candidate names
    wo_period = joined.replace(period, " ") if period else joined
    wo_period = re.sub(r"\([^)]*\)", " ", wo_period)
    bolds = re.findall(r"\*\*(.+?)\*\*", wo_period)
    if not bolds:
        bolds = [wo_period]
    parts = []
    for b in bolds:
        bits = re.split(r"\s+(?:at|—|–|-)\s+|\s*\|\s*|\s*,\s+", b)
        parts += [x.strip(" ,|-") for x in bits if x.strip(" ,|-")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    role = next((p for p in parts if ROLE_KW.search(p)), parts[0])
    company = next((p for p in parts if p != role), "")
    return role, company, period


def restructure_experience_section(text):
    lines = text.split("\n")
    out, header_buf, body_buf, in_entry = [], [], [], False

    def flush():
        nonlocal header_buf, body_buf, in_entry
        if header_buf:
            parsed = _parse_entry_header(header_buf)
            if parsed:
                role, company, period = parsed
                head = f"**{role}" + (f", {company}" if company else "") + \
                       (f" ({period})" if period else "") + "**"
                out.append(head)
            else:
                out.extend(header_buf)
        for b in body_buf:
            b = b.strip()
            if b.startswith("- "):
                b = b[2:].strip()
            elif b.startswith("– ") or b.startswith("• "):
                b = b[2:].strip()
            if b:
                out.append(_end_stop(b))
        header_buf, body_buf, in_entry = [], [], False

    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            if in_entry:
                flush()
            out.append(s)
            continue
        if s.strip().startswith("-"):
            if in_entry:
                body_buf.append(s.strip())
            else:
                out.append(_end_stop(s.strip()))
            continue
        if "**" in s and not s.startswith("##"):
            if in_entry and body_buf:
                flush()
            in_entry = True
            header_buf.append(s)
            continue
        if in_entry and not body_buf and (PERIOD_RE.search(s) or "|" in s or "**" in s or s.strip().startswith("**")):
            header_buf.append(s)
            continue
        if in_entry:
            body_buf.append(s)
        else:
            out.append(_end_stop(s) if len(s.strip()) > 40 else s)
    flush()
    return "\n".join(out)


def add_bullet_stops(text):
    lines = []
    for ln in text.split("\n"):
        s = ln.rstrip()
        st = s.strip()
        if st.startswith("- ") and len(st) > 5:
            indent = s[:len(s) - len(s.lstrip())]
            lines.append(indent + _end_stop(st))
        else:
            lines.append(s)
    return "\n".join(lines)


def fix_header(cv):
    lines = cv.split("\n")
    if not lines or not lines[0].startswith("# "):
        return cv
    name = lines[0]
    rest = lines[1:]

    def is_phone(s): return bool(re.match(r"^[\d\s+()-]{9,}$", s))
    def is_roles(s): return s and "@" not in s and "|" not in s and "·" not in s \
        and not is_phone(s) and not s.startswith("#")

    # Case A: a joined contact line with separators still exists
    joined_ci = next((i for i, l in enumerate(rest[:4]) if "@" in l and ("|" in l or "·" in l)), None)
    if joined_ci is not None:
        contact = rest[joined_ci].replace("·", "|")
        parts = [p.strip() for p in contact.split("|") if p.strip()]
        email = next((p for p in parts if "@" in p), "")
        phone = next((p for p in parts if is_phone(p)), "")
        location = next((p for p in parts if p not in (email, phone)), "")
        roles = rest[0].strip() if joined_ci > 0 and is_roles(rest[0].strip()) else ""
        header = [name] + ([roles] if roles else []) + [x for x in (location, phone, email) if x]
        remainder = rest[joined_ci + 1:]
        if roles and joined_ci > 0:
            remainder = rest[1:joined_ci] + remainder
        return "\n".join(header + [""] + remainder)

    # Case B: items already on separate lines (maybe out of order) — reorder them
    window, consumed = [], set()
    roles = ""
    for i, l in enumerate(rest[:8]):
        s = l.strip()
        if not s:
            continue
        if s.startswith("## "):
            break
        if is_roles(s) and not roles and not any(ch.isdigit() for ch in s):
            roles = s
            consumed.add(i)
        else:
            window.append((i, s))
    email = next((i for i, s in window if "@" in s), None)
    phone = next((i for i, s in window if is_phone(s)), None)
    location = next((i for i, s in window
                     if i not in (email, phone) and not s.startswith("#")
                     and ("," in s or "kenya" in s.lower())), None)
    if email is None:
        return cv  # nothing recognizable; leave untouched
    for i in (email, phone, location):
        if i is not None:
            consumed.add(i)
    header = [name] + ([roles] if roles else []) + \
             [rest[i].strip() for i in (location, phone, email) if i is not None]
    remainder = [l for i, l in enumerate(rest) if i not in consumed]
    while remainder and remainder[0].strip() == "":
        remainder.pop(0)
    return "\n".join(header + [""] + remainder)


def normalize_cv(cv):
    cv = fix_header(cv)
    sections = re.split(r"(^## .+$)", cv, flags=re.M)
    result = []
    last_header = ""
    for seg in sections:
        if seg.startswith("## "):
            last_header = seg.strip()
            result.append(seg)
        elif last_header in ("## EXPERIENCE", "## ACADEMIC PROJECT", "## ACADEMIC"):
            result.append(restructure_experience_section(seg))
            last_header = ""
        else:
            result.append(add_bullet_stops(seg))
    return "".join(result)


if __name__ == "__main__":
    conn = sqlite3.connect("data/jobagent.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, cv_md FROM jobs WHERE status='pending'").fetchall()
    for row in rows:
        conn.execute("UPDATE jobs SET cv_md=? WHERE id=?",
                     (normalize_cv(row["cv_md"] or ""), row["id"]))
    conn.commit()
    print(f"normalized {len(rows)} drafts")
