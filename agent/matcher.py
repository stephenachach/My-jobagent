"""Match jobs against the user profile -> score 0-100 + reasons.

Rule-based scoring: transparent, free, runs anywhere. Combined later with
LLM drafting (tailor.py) for the smart documents.
"""
import re
from datetime import date, datetime

WORD = re.compile(r"\b[a-z][a-z+#./]*\b")
STOP = {"at", "in", "of", "to", "and", "for", "with", "the", "a", "an", "is"}
# single words that alone are NOT strong indicators of a target role
GENERIC = {"officer", "support", "assistant", "intern", "analyst", "developer", "engineer"}


def _words(text: str) -> set:
    return {w for w in WORD.findall((text or "").lower()) if len(w) >= 2 and w not in STOP}


def _days_old(s: str):
    """ISO date string -> days old, or None if unknown."""
    try:
        d = datetime.strptime((s or "").strip()[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except ValueError:
        return None


def score_job(job: dict, profile: dict) -> dict:
    """Returns {score, matched_skills, reasons}."""
    title_w = _words(job.get("title", ""))
    text_w = _words(f"{job.get('title','')} {job.get('description','')}")
    reasons, matched = [], []
    score = 0.0

    # 1) Target-role words in the TITLE (strongest signal)
    target_words = set()
    for role in profile.get("target_roles", []):
        target_words |= _words(role)
    title_hits = title_w & target_words
    specific = title_hits - GENERIC
    if len(title_hits) >= 2:
        score += min(50, 22 * len(title_hits))
        reasons.append(f"Title closely matches your target roles ({', '.join(sorted(title_hits))})")
    elif specific:
        score += 20
        reasons.append(f"Title touches your target roles ({', '.join(sorted(title_hits))})")
    elif title_hits:
        score += 8

    # 2) Skills mentioned in the posting
    for skill in profile.get("skills", []):
        sw = _words(skill)
        if sw and sw <= text_w:
            score += 10
            matched.append(skill)
    if matched:
        reasons.append(f"Skills matched: {', '.join(matched[:6])}")

    # 3) Junior-friendly signals
    junior_words = {"intern", "internship", "graduate", "trainee", "entry", "junior",
                    "attachment", "fresher"}
    if title_w & junior_words:
        score += 16
        reasons.append("Junior/graduate-friendly role")

    # 4) Location fit
    prefs = profile.get("preferences", {})
    locs = [l.lower() for l in prefs.get("locations", [])]
    loc_text = (job.get("location") or "").lower()
    if job.get("remote") and prefs.get("remote_ok", True):
        score += 8
        reasons.append("Remote role")
    elif any(l in loc_text for l in locs if l):
        score += 10
        reasons.append(f"Location fits ({job.get('location','')})")

    # 5) Degree relevance
    if "bbit" in text_w or ("business" in text_w and "information" in text_w and "technology" in text_w) \
       or "business information technology" in f"{job.get('title','')} {job.get('description','')}".lower():
        score += 8
        reasons.append("BBIT degree directly relevant")

    # 5b) HIRING-ODDS BOOSTERS — jobs with better chances of an offer
    #     Freshness: applying early beats the crowd
    days_old = _days_old(job.get("posted_date") or "")
    if days_old is not None:
        if days_old <= 1:
            score += 14
            reasons.append("🆕 Posted today — applying early beats the crowd")
        elif days_old <= 3:
            score += 9
            reasons.append(f"🆕 Posted {days_old} day(s) ago — still fresh")
        elif days_old <= 7:
            score += 4
        elif days_old > 30:
            score -= 12
            reasons.append(f"⚠ Old posting ({days_old} days) — may be filled")
    #     Mass intake: "35 posts" style hiring has far better odds
    m = re.search(r"(\d+)\s*(?:posts?|positions?|vacanc\w*)", (job.get("title") or ""), re.I)
    if m and int(m.group(1)) >= 3:
        score += 10
        reasons.append(f"🎯 Mass intake ({m.group(1)} posts) — much higher hiring odds")
    elif m:
        score += 5
        reasons.append("Multiple openings in this advert")

    # 6) Penalties — the experience-LEVEL gate (agent/experience.py, driven by
    # settings search.max_experience_years) already removed jobs above the candidate's
    # level before scoring; this only down-ranks what is left.
    title_lower = (job.get("title") or "").lower()
    excluded = False
    for bad in prefs.get("exclude_keywords", []):
        if bad.lower() in title_lower:
            score -= 60
            reasons.append(f"Excluded keyword in title: '{bad}'")
            excluded = True
            break
    senior_w = {"principal", "architect", "director", "phd", "head"}
    if title_w & senior_w and not excluded:
        score -= 15
        reasons.append("Very senior title — lower priority")

    score = max(0, min(100, round(score)))
    return {"score": score, "matched_skills": matched, "reasons": reasons}
