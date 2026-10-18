"""Spend limits for the public site: new research jobs per visitor per UTC day, and a global daily dollar budget.
A small SQLite ledger records each job start (by IP) and what every model call cost, by the UTC day it started."""
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone

from .config import DAILY_BUDGET_USD, JOB_COST_RESERVE_USD, LIMITS_DB, MAX_JOBS_PER_IP_PER_DAY

LIMIT_MSG = "You've hit today's limit for new searches. Try the demo, or come back tomorrow."
BUDGET_MSG = "HuskyMatch has used up today's research budget. Try the demo, or come back tomorrow."

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_starts (day TEXT NOT NULL, ip TEXT NOT NULL, job_id TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS job_starts_day_ip ON job_starts (day, ip);
CREATE TABLE IF NOT EXISTS spend (
    day TEXT NOT NULL, job_id TEXT NOT NULL, kind TEXT NOT NULL, usd REAL NOT NULL, PRIMARY KEY (day, job_id, kind));
"""

_lock = threading.Lock()  # check-then-record must be atomic across concurrent requests


class LimitHit(Exception):
    """A spend limit refused the request; str(e) is safe to show the visitor."""


def day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).date().isoformat()


def _db() -> sqlite3.Connection:
    LIMITS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LIMITS_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def spent(on: str | None = None) -> float:
    with closing(_db()) as con:
        return con.execute("SELECT coalesce(sum(usd), 0) FROM spend WHERE day = ?", (on or day(),)).fetchone()[0]


def reserve_job(ip: str, job_id: str) -> None:
    """Record a new research job for this visitor, or raise LimitHit. Reused (cached) jobs never come here."""
    today = day()
    with _lock, closing(_db()) as con, con:
        if spent(today) + JOB_COST_RESERVE_USD > DAILY_BUDGET_USD:
            raise LimitHit(BUDGET_MSG)
        n = con.execute("SELECT count(*) FROM job_starts WHERE day = ? AND ip = ?", (today, ip)).fetchone()[0]
        if n >= MAX_JOBS_PER_IP_PER_DAY:
            raise LimitHit(LIMIT_MSG)
        con.execute("INSERT INTO job_starts VALUES (?,?,?,?)", (today, ip, job_id, time.time()))


def check_budget() -> None:
    """For the cheap per-card calls: only refused once today's budget is actually used up."""
    if spent() >= DAILY_BUDGET_USD:
        raise LimitHit(BUDGET_MSG)


def set_research_cost(job_id: str, created: float, usd: float) -> None:
    """A research run's running total (replaces the previous value), booked to the day the job started."""
    with closing(_db()) as con, con:
        con.execute("INSERT INTO spend VALUES (?,?,?,?) ON CONFLICT (day, job_id, kind) DO UPDATE SET usd = excluded.usd",
                    (day(created), job_id, "research", usd))


def add_cost(job_id: str, kind: str, usd: float) -> None:
    """One extra call (more / results / draft), booked to today."""
    with closing(_db()) as con, con:
        con.execute("INSERT INTO spend VALUES (?,?,?,?)", (day(), job_id, f"{kind}:{uuid.uuid4().hex[:8]}", usd))


def status() -> dict:
    return {"day": day(), "spent_usd": round(spent(), 3), "budget_usd": DAILY_BUDGET_USD,
            "max_jobs_per_ip": MAX_JOBS_PER_IP_PER_DAY}
