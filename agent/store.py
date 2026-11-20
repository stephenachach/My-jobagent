"""SQLite persistence — jobs, drafts, and their status in one table.

Statuses:
  new       -> fetched, not yet scored
  pending   -> draft CV + letter generated, waiting for YOUR approval
  approved  -> you approved; queued for sending (Phase 2)
  rejected  -> you rejected it
  sent      -> application sent (Phase 2)
  skipped   -> scored below the bar
"""
import json
import os
import sqlite3
import time
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jobagent.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, url TEXT UNIQUE, title TEXT, company TEXT,
    location TEXT, description TEXT, apply_url TEXT, apply_email TEXT,
    posted_date TEXT, remote INTEGER DEFAULT 0, salary TEXT,
    score REAL, matched_skills TEXT, reasons TEXT,
    status TEXT DEFAULT 'new',
    cv_md TEXT, letter_md TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER, event TEXT, detail TEXT, created_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # WAL lets the autopilot thread and the dashboard write at the same time.
    # Without it, clicking Approve while a search runs raises
    # "database is locked" -> HTTP 500 -> the button looks dead.
    conn = sqlite3.connect(DB_PATH, timeout=3)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN engine TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    return conn


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def upsert_job(conn: sqlite3.Connection, job_dict: dict) -> bool:
    """Insert job if new. Returns True if it was newly inserted."""
    try:
        conn.execute(
            """INSERT INTO jobs (source,url,title,company,location,description,
               apply_url,apply_email,posted_date,remote,salary,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job_dict.get("source"), job_dict["url"], job_dict.get("title", ""),
             job_dict.get("company", ""), job_dict.get("location", ""),
             job_dict.get("description", ""), job_dict.get("apply_url", ""),
             job_dict.get("apply_email", ""), job_dict.get("posted_date", ""),
             1 if job_dict.get("remote") else 0, job_dict.get("salary", ""),
             "new", now(), now()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        try:
            conn.rollback()   # release the write lock before returning
        except sqlite3.Error:
            pass
        return False  # already known


def update(conn: sqlite3.Connection, job_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in fields)
    sql = f"UPDATE jobs SET {sets} WHERE id=?"
    args = (*fields.values(), job_id)
    # Retry short lock contention instead of letting the request 500.
    for attempt in range(3):
        try:
            conn.execute(sql, args)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.25 * (attempt + 1))


def log_event(conn: sqlite3.Connection, job_id: Optional[int], event: str, detail: str = ""):
    sql = "INSERT INTO events (job_id,event,detail,created_at) VALUES (?,?,?,?)"
    args = (job_id, event, detail, now())
    for attempt in range(3):
        try:
            conn.execute(sql, args)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2:
                print(f"[store] log_event failed: {exc}", flush=True)
                return
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.25 * (attempt + 1))


def pending_jobs(conn):
    return conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY score DESC").fetchall()


def job_by_id(conn, job_id):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def jobs_by_status(conn, status):
    return conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY score DESC", (status,)).fetchall()


def stats(conn):
    rows = conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}
