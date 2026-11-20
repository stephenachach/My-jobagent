"""Experience-level gate: keep only jobs the candidate can realistically get.

Keeps internships / attachments / graduate trainee roles and jobs asking for
at most `max_experience_years` of experience (default 2). Rejects senior
titles and adverts that demand more years than that.

Pure functions, no network, so it is cheap to run on every job.
"""
import re

_WORD_NUMS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "twelve": 12, "fifteen": 15}
_NUM = r"(\d{1,2}(?:\.\d)?|" + "|".join(_WORD_NUMS) + r")"

# "2-4 years", "2 to 4 years", "3+ years", "three years", "18 months"
_YEARS_RE = re.compile(
    r"(?:" + _NUM + r"\s*(?:\+|plus)?\s*(?:-|–|—|to|or)\s*)?" + _NUM +
    r"\s*(?:\+|plus)?\s*(years?|yrs?|months?)\b", re.I)
_EXP_CONTEXT = re.compile(r"experience|experienced|exposure|track record", re.I)
_NOT_EXP = re.compile(r"years?\s+(?:of\s+)?age|aged?\s+\d", re.I)

_SENIOR_TITLE = re.compile(
    r"\b(senior|sr|snr|lead|leader|manager|head|principal|director|chief|vp|"
    r"vice president|architect|expert|supervisor|mid[- ]?level|"
    r"experienced)\b", re.I)
_JUNIOR_WORDS = re.compile(
    r"\b(intern|interns|internship|internships|attachment|attachee|trainee|"
    r"graduate|graduates|entry[- ]?level|junior|jr|fresher|fresh|apprentice|"
    r"apprenticeship|no experience)\b", re.I)
_MID_DESC = re.compile(r"\b(mid[- ]?level|senior[- ]?level|seasoned professional)\b", re.I)


def _to_num(tok: str) -> float:
    t = tok.lower()
    return float(_WORD_NUMS[t]) if t in _WORD_NUMS else float(t)


def required_years(text: str):
    """Highest MINIMUM years of experience the text asks for, or None.

    Only numbers near the word 'experience' count, so 'a company with 10 years
    in business' is ignored. For a range ('2-4 years') the lower bound is used.
    """
    text = text or ""
    best = None
    for m in _YEARS_RE.finditer(text):
        # the number and the word 'experience' must be in the same sentence
        s_start = max((text.rfind(sep, 0, m.start()) for sep in (". ", "\n", ";", "! ", "? ")),
                      default=-1)
        ends = [i for i in (text.find(sep, m.end()) for sep in (". ", "\n", ";", "! ", "? "))
                if i != -1]
        sentence = text[s_start + 1: min(ends) if ends else len(text)]
        if not _EXP_CONTEXT.search(sentence):
            continue
        if _NOT_EXP.search(text[max(0, m.start() - 10): m.end() + 10]):
            continue
        low = m.group(1) if m.group(1) else m.group(2)
        try:
            val = _to_num(low)
        except (KeyError, ValueError):
            continue
        if m.group(3).lower().startswith("m"):   # months -> years
            val = val / 12.0
        best = val if best is None else max(best, val)
    return best


def check_level(job: dict, max_years: float = 2, require_entry_signal: bool = False):
    """Return (ok, reason). reason explains a rejection (empty when ok)."""
    title = job.get("title") or ""
    desc = job.get("description") or ""
    junior_title = bool(_JUNIOR_WORDS.search(title))

    if not junior_title:
        m = _SENIOR_TITLE.search(title)
        if m:
            return False, f"Above entry level: senior-type title ('{m.group(1)}')"
        m = _MID_DESC.search(desc)
        if m:
            return False, f"Above entry level: advert says '{m.group(1)}'"

    years = required_years(f"{title}. {desc}")
    if years is not None and years > max_years:
        shown = int(years) if float(years).is_integer() else round(years, 1)
        return False, f"Needs {shown} years experience (your limit: {max_years})"

    if require_entry_signal and years is None and not (
            junior_title or _JUNIOR_WORDS.search(desc)):
        return False, "No entry-level / internship signal in the advert"
    return True, ""
