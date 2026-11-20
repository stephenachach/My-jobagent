"""Fuzu Kenya public job-listing fetcher.

Fuzu occasionally presents a Cloudflare challenge. This fetcher does not try to
bypass it: that run returns no Fuzu jobs and the next scheduled check retries.
"""
import re
import time
from datetime import date, timedelta
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://www.fuzu.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0; personal job-search tool)"}


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _posted_date(text: str) -> str:
    """Return a date only when the listing card actually states one.

    Do not treat a page-fetch date as a posting date: search pages can retain
    expired adverts and that made old Fuzu jobs look brand new.
    """
    value = (text or "").lower()
    today = date.today()
    if re.search(r"\bposted\s+today\b|\btoday\b", value):
        return today.isoformat()
    if re.search(r"\byesterday\b", value):
        return (today - timedelta(days=1)).isoformat()
    ago = re.search(r"(?:posted\s+)?(\d+)\s+days?\s+ago", value)
    if ago:
        return (today - timedelta(days=int(ago.group(1)))).isoformat()
    absolute = re.search(r"\b(\d{1,2})\s+([a-z]{3,9})\s+(20\d{2})\b", value, re.I)
    if absolute:
        try:
            return date.fromisoformat("%04d-%02d-%02d" % (
                int(absolute.group(3)),
                list(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")).index(absolute.group(2)[:3].lower()) + 1,
                int(absolute.group(1)),
            )).isoformat()
        except (ValueError, IndexError):
            pass
    return ""


def fetch(queries: list[str] | None = None, delay: float = 1.5, max_per_query: int = 25) -> list[Job]:
    """Search the public Kenya listings for the configured role terms."""
    jobs, seen = [], set()
    for term in (queries or ["information technology"])[:8]:
        url = f"{BASE}/kenya/job?filters%5Bterm%5D={quote_plus(term)}&page=1"
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            if response.status_code != 200 or "challenge-error-text" in response.text.lower():
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select('a[href*="/kenya/jobs/"]'):
            href = urljoin(BASE, link.get("href", ""))
            title = _text(link)
            if not href or href in seen or not title or len(title) > 180:
                continue
            seen.add(href)
            card = link
            for _ in range(5):
                card = card.parent if card else None
                if card and len(_text(card)) >= 80:
                    break
            text = _text(card)
            location_match = re.search(r"([A-Za-z ]+)\s*[•·]\s*Kenya", text)
            jobs.append(Job(
                source="fuzu", url=href, title=title, company="",
                location=(location_match.group(1).strip() + ", Kenya") if location_match else "Kenya",
                description=text[:2500], apply_url=href, posted_date=_posted_date(text),
                remote="remote" in text.lower(),
            ))
            if len(jobs) >= max_per_query:
                break
        time.sleep(delay)
    return jobs
