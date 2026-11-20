#!/usr/bin/env python3
"""Regenerate stored CV + letter drafts from the CURRENT config/profile.yaml.

The dashboard shows drafts saved in data/jobagent.db. If you edited your CV
after those drafts were created, they will still look old until you refresh them.

This command always uses your own profile wording and never calls the AI API,
so it is instant and offline. It rebuilds the professional layout too: bold
plain headings, single round dot bullets on multi-sentence sections, full stops,
generous spacing and a PROFILE that opens with skills matched to each job.

Run from C:\\jobagent:
    python refresh_cv.py
    python refresh_cv.py --job-id 3
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import store, tailor  # noqa: E402
from agent.config import config_status, load_profile  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, help="refresh only this job id")
    a = ap.parse_args()

    st = config_status()
    if st["settings_source"].endswith("settings.example.yaml"):
        print("Note: no config/settings.yaml was read, so example settings are in use.")
        print("Your AI key and email settings are NOT active until settings.yaml parses.")
        print("Run python check_ai.py to see the exact reason.\n")

    conn = store.connect()
    if a.job_id:
        row = store.job_by_id(conn, a.job_id)
        rows = [dict(row)] if row else []
        if not rows:
            print(f"No job with id {a.job_id}")
            return 1
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM jobs").fetchall()]

    profile = load_profile()
    count = 0
    for row in rows:
        job = {k: row.get(k) for k in ("title", "company", "location",
                                       "description", "salary", "url", "apply_email")}
        cv_md = tailor.humanize(tailor.template_cv(job, profile))
        letter_md = tailor.humanize(tailor.template_letter(job, profile))
        store.update(conn, row["id"], cv_md=cv_md,
                     letter_md=letter_md, engine="template")
        store.log_event(conn, row["id"], "cv_refreshed",
                        "regenerated from current config/profile.yaml in plain human wording")
        count += 1
    conn.close()
    print(f"Refreshed {count} draft(s) from config/profile.yaml.")
    print("No AI calls were made, so this finished immediately.")
    print("Open the dashboard, click a job, then View / Save CV or CV PDF.")
    print("You should now see graduated in 2026, your three projects and their links,")
    print("bold well-spaced headings, dot bullets and full stops, with no hyphens")
    print("used as bullets, no brackets and no markdown symbols.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
