"""Remotive — free public API, remote jobs worldwide."""
import requests
from ..models import Job

API = "https://remotive.com/api/remote-jobs"


def fetch(queries=None, delay=0, max_per_query=None) -> list[Job]:
    """If queries given, search per query; else fetch the general feed."""
    urls = [f"{API}?limit=60"]
    for q in (queries or []):
        urls.append(f"{API}?search={requests.utils.quote(q)}&limit=25")
    jobs, seen = [], set()
    for url in urls:
        try:
            r = requests.get(url, timeout=25, headers={"User-Agent": "JobAgent/0.1 (personal job search)"})
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            continue
        for item in data.get("jobs", []):
            if item.get("url") in seen:
                continue
            seen.add(item.get("url"))
            jobs.append(Job(
                source="remotive",
                url=item.get("url", ""),
                title=item.get("title", ""),
                company=(item.get("company_name") or "").strip(),
                location=", ".join(filter(None, [item.get("candidate_required_location"), "Remote"])),
                description=(item.get("description") or "")[:6000],
                apply_url=item.get("url", ""),
                posted_date=(item.get("publication_date") or "")[:10],
                remote=True,
                salary=item.get("salary") or "",
            ))
    return jobs
