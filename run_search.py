#!/usr/bin/env python3
"""The agent pipeline: FETCH jobs -> SCORE them -> DRAFT CVs + letters.

Run:  python3 run_search.py
      python3 run_search.py --max 10 --min-score 40 --no-detail
"""
import argparse
import os
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
from agent import store, tailor
from agent.sources import SOURCES
from agent.sources.myjobmag import fetch_detail
from agent.models import Job
from agent.experience import check_level

ROOT = os.path.dirname(os.path.abspath(__file__))
from agent.config import load_settings, load_profile
PROFILE = load_profile()
SETTINGS = load_settings()


CLOSED_MARKERS = (
    "job closed", "position closed", "applications are closed", "application closed",
    "no longer accepting applications", "no longer available", "position has been filled",
    "vacancy closed", "expired vacancy", "this advert has expired",
)


def _job_is_eligible(job: dict, cfg: dict) -> tuple[bool, str]:
    """Apply conservative freshness/closure checks before any draft is made."""
    haystack = " ".join(str(job.get(k) or "") for k in ("title", "description")).lower()
    if any(marker in haystack for marker in CLOSED_MARKERS):
        return False, "Listing indicates that applications are closed"
    max_years = cfg.get("max_experience_years")
    if max_years is not None:
        ok, why = check_level(job, float(max_years), bool(cfg.get("require_entry_signal", False)))
        if not ok:
            return False, why
    raw_date = (job.get("posted_date") or "").strip()[:10]
    try:
        posted = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        if cfg.get("require_posted_date", True):
            return False, "No reliable posting date; strict freshness gate"
        return True, ""
    age = (date.today() - posted).days
    if age < -1 or age > int(cfg.get("max_job_age_days", 7)):
        return False, f"Posting is {age} days old (limit: {cfg.get('max_job_age_days', 7)})"
    return True, ""


def _score_and_draft(conn, cfg, summary, max_drafts, min_score, fetch_details, delay, verbose):
    """Steps 3 + 4 of the pipeline: score every 'new' job, then draft the best.

    Shared by run() (fetch from boards) and process_new() (jobs already in the
    DB, e.g. pasted from a WhatsApp channel).
    """
    from agent.matcher import score_job
    rows = conn.execute("SELECT * FROM jobs WHERE status='new'").fetchall()
    scored = []
    for row in rows:
        eligible, reason = _job_is_eligible(dict(row), cfg)
        if not eligible:
            store.update(conn, row["id"], status="skipped", reasons=str([reason]))
            store.log_event(conn, row["id"], "skipped", reason)
            summary["skipped"] += 1
            continue
        s = score_job(dict(row), PROFILE)
        store.update(conn, row["id"], score=s["score"],
                     matched_skills=str(s["matched_skills"]), reasons=str(s["reasons"]),
                     status="scored")
        scored.append((s["score"], row))
        summary["scored"] += 1
    scored.sort(key=lambda t: -t[0])

    drafted = 0
    for score, row in scored:
        if drafted >= max_drafts or score < min_score:
            store.update(conn, row["id"], status="skipped")
            summary["skipped"] += 1
            continue
        job_dict = dict(row)
        if fetch_details and row["source"] == "myjobmag":
            time.sleep(delay)
            det = fetch_detail(Job(source=row["source"], url=row["url"], title=row["title"],
                                   company=row["company"], location=row["location"],
                                   description=row["description"], apply_url=row["apply_url"]))
            if len(det.description) > len(job_dict.get("description") or ""):
                job_dict["description"] = det.description
                store.update(conn, row["id"],
                             **{"description": det.description,
                                **({"apply_email": det.apply_email} if det.apply_email else {})})
        result = tailor.generate(job_dict)
        store.update(conn, row["id"], cv_md=result["cv_md"], letter_md=result["letter_md"],
                     engine=result["engine"], status="pending")
        store.log_event(conn, row["id"], "drafted", f"engine={result['engine']} score={score}")
        drafted += 1
        summary["drafted"] += 1
        if verbose:
            print(f"  ✎ drafted #{row['id']} [{result['engine']}] {row['title'][:60]} (score {score})")
    return summary


def process_new(verbose=False) -> dict:
    """Score + draft any jobs already stored with status 'new'.

    Used after jobs are added directly (e.g. the WhatsApp inbox paste), so they
    go through the exact same scoring + CV/letter drafting as a normal run.
    """
    cfg = SETTINGS["search"]
    summary = {"fetched": 0, "new": 0, "scored": 0, "drafted": 0, "skipped": 0,
               "engine": "AI" if tailor.ai_available() else "template"}
    conn = store.connect()
    _score_and_draft(conn, cfg, summary, cfg["max_drafts_per_run"], cfg["min_match_score"],
                     cfg["fetch_job_details"], cfg.get("polite_delay_seconds", 1.5), verbose)
    store.log_event(conn, None, "process_new", str(summary))
    return summary


def run(max_drafts=None, min_score=None, fetch_details=None, verbose=True) -> dict:
    cfg = SETTINGS["search"]
    max_drafts = max_drafts if max_drafts is not None else cfg["max_drafts_per_run"]
    min_score = min_score if min_score is not None else cfg["min_match_score"]
    fetch_details = fetch_details if fetch_details is not None else cfg["fetch_job_details"]
    delay = cfg.get("polite_delay_seconds", 1.5)
    engine = "AI" if tailor.ai_available() else "template"
    summary = {"fetched": 0, "new": 0, "scored": 0, "drafted": 0, "skipped": 0, "engine": engine}

    conn = store.connect()

    # 1) FETCH from all sources
    jobs: list[Job] = []
    for name in cfg["sources"]:
        fn = SOURCES.get(name)
        if not fn:
            continue
        try:
            got = fn(cfg.get("queries", []), delay=delay) if name in (
                "myjobmag", "brightermonday", "fuzu", "remotive") else fn()
            jobs.extend(got)
            if verbose:
                print(f"  [{name}] fetched {len(got)} jobs")
        except Exception as e:
            if verbose:
                print(f"  [{name}] ERROR: {e}")
    summary["fetched"] = len(jobs)

    # 2) STORE (dedupe by URL)
    for j in jobs:
        if store.upsert_job(conn, {"source": j.source, "url": j.url, "title": j.title,
                                   "company": j.company, "location": j.location,
                                   "description": j.description, "apply_url": j.apply_url or j.url,
                                   "apply_email": j.apply_email, "posted_date": j.posted_date,
                                   "remote": j.remote, "salary": j.salary}):
            summary["new"] += 1

    # 3) SCORE the unscored ('new') jobs  ->  4) DRAFT the best ones
    _score_and_draft(conn, cfg, summary, max_drafts, min_score, fetch_details, delay, verbose)

    store.log_event(conn, None, "run", str(summary))
    if verbose:
        print("\n=== RUN COMPLETE ===")
        print(f"  fetched={summary['fetched']} new={summary['new']} scored={summary['scored']}")
        print(f"  drafted={summary['drafted']} skipped={summary['skipped']} engine={engine}")
        print("  Open the dashboard to review & approve drafts.")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None, help="max drafts this run")
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--no-detail", action="store_true", help="skip fetching full job pages")
    a = ap.parse_args()
    run(max_drafts=a.max, min_score=a.min_score, fetch_details=not a.no_detail)
