"""RemoteOK — free public API, remote jobs worldwide."""
import requests
from ..models import Job

API = "https://remoteok.com/api"


def fetch(queries=None, delay=0, max_per_query=None) -> list[Job]:
    try:
        r = requests.get(API, timeout=25, headers={"User-Agent": "Mozilla/5.0 JobAgent/0.1 (personal job search)"})
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []
    jobs = []
    for item in data:
        if not isinstance(item, dict) or item.get("position") is None:
            continue  # first element is legal notice
        jobs.append(Job(
            source="remoteok",
            url=item.get("url", ""),
            title=item.get("position", ""),
            company=(item.get("company") or "").strip(),
            location="Remote",
            description=(item.get("description") or "")[:6000],
            apply_url=item.get("url", ""),
            posted_date=(item.get("date") or "")[:10],
            remote=True,
            salary=item.get("salary") or "",
        ))
    return jobs
