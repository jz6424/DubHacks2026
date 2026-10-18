"""Shared club catalog (SQLite): every verified club any research run finds, minus the per-student fields, so later
students with overlapping interests can reuse it instead of searching the web again. Keyed by campus + normalized name;
entries older than CATALOG_MAX_AGE_DAYS are ignored (and refreshed when research finds the club again)."""
import json
import re
import sqlite3
import time
from contextlib import closing

from .config import CATALOG_DB, CATALOG_MAX_AGE_DAYS
from .profile import IDENTITY_INTEREST

PER_STUDENT = ("fit_reason", "wildcard", "interest_areas")  # not facts about the club

SCHEMA = """
CREATE TABLE IF NOT EXISTS clubs (
    campus TEXT NOT NULL, key TEXT NOT NULL, club_id TEXT NOT NULL, name TEXT NOT NULL,
    card TEXT NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY (campus, key));
CREATE TABLE IF NOT EXISTS club_interests (
    campus TEXT NOT NULL, key TEXT NOT NULL, interest TEXT NOT NULL, PRIMARY KEY (campus, key, interest));
"""


def norm(name: str) -> str:
    """'UW Robotics Club (Husky Robotics)' and 'husky robotics' should collide; keep it simple and conservative."""
    n = re.sub(r"\(.*?\)", " ", name.lower())
    n = re.sub(r"\b(uw|university of washington|the|club|association|society|at)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def _db() -> sqlite3.Connection:
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CATALOG_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if "seeded" not in {r[1] for r in con.execute("PRAGMA table_info(clubs)")}:
        con.execute("ALTER TABLE clubs ADD COLUMN seeded INTEGER NOT NULL DEFAULT 0")
    return con


def campus_of(profile: dict) -> str:
    return profile.get("campus") or "seattle"


def upsert(campus: str, card: dict, seeded: bool = False) -> None:
    """Save (or refresh) one verified club. Interest tags accumulate across runs. Seeded clubs (researched ahead of
    time with python -m app.seed) never expire; a later refresh keeps them seeded."""
    key = norm(card["name"])
    if not key:
        return
    facts = {k: v for k, v in card.items() if k not in PER_STUDENT}
    with closing(_db()) as con, con:
        con.execute("INSERT INTO clubs (campus, key, club_id, name, card, fetched_at, seeded) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT (campus, key) DO UPDATE SET club_id=excluded.club_id, name=excluded.name, "
                    "card=excluded.card, fetched_at=excluded.fetched_at, seeded=max(seeded, excluded.seeded)",
                    (campus, key, card["club_id"], card["name"], json.dumps(facts), time.time(), int(seeded)))
        con.executemany("INSERT OR IGNORE INTO club_interests VALUES (?,?,?)",
                        [(campus, key, i) for i in card.get("interest_areas") or []])


def known(campus: str, interests: list[str], identity_ok: bool, limit: int = 40) -> list[dict]:
    """Fresh (or seeded) catalog clubs tagged with any of these interests, newest first, with their interest tags."""
    if not interests:
        return []
    cutoff = time.time() - CATALOG_MAX_AGE_DAYS * 86400
    marks = ",".join("?" * len(interests))
    with closing(_db()) as con:
        rows = con.execute(
            f"SELECT c.key, c.card, (SELECT json_group_array(interest) FROM club_interests t "
            f"  WHERE t.campus = c.campus AND t.key = c.key) "
            f"FROM clubs c WHERE c.campus = ? AND (c.fetched_at > ? OR c.seeded = 1) AND EXISTS (SELECT 1 FROM club_interests i "
            f"  WHERE i.campus = c.campus AND i.key = c.key AND i.interest IN ({marks})) "
            f"ORDER BY c.fetched_at DESC LIMIT ?",
            (campus, cutoff, *interests, limit)).fetchall()
    out = []
    for _, card, tags in rows:
        tags = json.loads(tags)
        if IDENTITY_INTEREST in tags and not identity_ok:
            continue
        out.append({**json.loads(card), "interest_areas": tags})
    return out


def stats() -> dict:
    with closing(_db()) as con:
        return dict(con.execute("SELECT campus, count(*) FROM clubs GROUP BY campus").fetchall())
