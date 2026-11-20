"""MyJobMag Kenya — https://www.myjobmag.co.ke  (scraped politely, low volume)."""
import re
import time
import requests
from bs4 import BeautifulSoup
from ..models import Job

BASE = "https://www.myjobmag.co.ke"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobAgent/0.1 (personal job search)"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MONTHS = "jan february march april may june july august september october november december"


def _norm_date(s: str) -> str:
    """'02 September' or '02 September 2026' -> ISO date (year inferred)."""
    from datetime import date
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s*(\d{4})?", s)
    if not m:
        return ""
    day, mon = int(m.group(1)), m.group(2).lower()
    names = MONTHS.split()
    mi = next((i + 1 for i, nm in enumerate(names) if mon.startswith(nm[:3])), 0)
    if not mi:
        return ""
    year = int(m.group(3)) if m.group(3) else date.today().year
    try:
        d = date(year, mi, day)
        if not m.group(3) and (date.today() - d).days > 15:   # listing from last year
            d = date(year - 1, mi, day)
        return d.isoformat()
    except ValueError:
        return ""


def fetch(queries: list[str], delay: float = 1.5, max_per_query: int = 25) -> list[Job]:
    jobs, seen = [], set()
    for q in queries:
        url = f"{BASE}/search/jobs?q={requests.utils.quote(q)}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                time.sleep(delay)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for li in soup.select("li.job-list-li"):
                a = li.select_one("li.mag-b h2 a") or li.select_one("h2 a")
                if not a:
                    continue
                href = a.get("href", "")
                if href.startswith("/"):
                    href = BASE + href
                if href in seen:
                    continue
                seen.add(href)
                title_full = a.get_text(strip=True)          # "Title at Company"
                title, company = title_full, ""
                if " at " in title_full:
                    title, company = title_full.rsplit(" at ", 1)
                desc_div = li.select_one("li.job-desc")
                date_li = li.select_one("li#job-date")
                jobs.append(Job(
                    source="myjobmag", url=href, title=title.strip(), company=company.strip(),
                    location="Kenya", description=desc_div.get_text(" ", strip=True) if desc_div else "",
                    apply_url=href,
                    posted_date=_norm_date(date_li.get_text(strip=True) if date_li else ""),
                ))
                if len([j for j in jobs if j.url == href]) and len(jobs) >= max_per_query * len(queries):
                    break
        except requests.RequestException:
            pass
        time.sleep(delay)                                     # politeness
    return jobs


def fetch_detail(job: Job) -> Job:
    """Open the job page for the full description + apply email."""
    try:
        r = requests.get(job.url, headers=HEADERS, timeout=20)
        if r.status_code != 200:                       # one polite retry
            time.sleep(3)
            r = requests.get(job.url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return job
        soup = BeautifulSoup(r.text, "html.parser")
        desc = soup.select_one("li.job-description") or soup.select_one("[id=printable]") \
            or soup.select_one("article") or soup.select_one("main")
        if desc:
            for junk in desc.find_all(["script", "style", "ins", "form"]):
                junk.decompose()
            job.description = desc.get_text("\n", strip=True)[:6000]
        emails = [e for e in EMAIL_RE.findall(job.description)
                  if not e.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and "example" not in e.lower()]
        if emails:
            job.apply_email = emails[0]
        # date posted
        m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", job.description[:500])
        if m:
            job.posted_date = _norm_date(m.group(1))
    except requests.RequestException:
        pass
    return job
