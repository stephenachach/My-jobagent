"""BrighterMonday Kenya public job-listing fetcher."""
import re
import time
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://www.brightermonday.co.ke"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0; personal job-search tool)"}


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _posted_date(text: str) -> str:
    """Use a date displayed in the card; never invent today's date."""
    value, today = (text or "").lower(), date.today()
    if re.search(r"\bposted\s+today\b|\btoday\b", value):
        return today.isoformat()
    if re.search(r"\byesterday\b", value):
        return (today - timedelta(days=1)).isoformat()
    ago = re.search(r"(?:posted\s+)?(\d+)\s+days?\s+ago", value)
    if ago:
        return (today - timedelta(days=int(ago.group(1)))).isoformat()
    return ""


def fetch(queries=None, delay: float = 1.5, max_per_query: int = 25) -> list[Job]:
    """Fetch one public results page; matching happens in the central pipeline."""
    try:
        response = requests.get(f"{BASE}/jobs", headers=HEADERS, timeout=25)
        response.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    jobs, seen = [], set()
    for link in soup.select('a[data-cy="listing-title-link"]'):
        href = urljoin(BASE, link.get("href", ""))
        if not href or href in seen:
            continue
        seen.add(href)
        card = link
        for _ in range(5):
            card = card.parent if card else None
            if card and len(_text(card)) >= 120:
                break
        text = _text(card)
        title = (link.get("title") or _text(link)).strip()
        if not title:
            continue
        company_node = card.select_one("p.text-blue-700") if card else None
        location_match = re.search(r"\b(Nairobi|Mombasa|Kisumu|Nakuru|Eldoret|Thika|Kenya|Remote)\b", text, re.I)
        jobs.append(Job(
            source="brightermonday", url=href, title=title, company=_text(company_node),
            location=location_match.group(0).title() if location_match else "Kenya",
            description=text[:2500], apply_url=href, posted_date=_posted_date(text),
            remote="remote" in text.lower(),
        ))
        if len(jobs) >= max_per_query:
            break
    time.sleep(delay)
    return jobs
