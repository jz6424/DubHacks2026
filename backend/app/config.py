"""Paths and settings. Loads the repo-root .env without overriding real environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "huskymatch"
JOBS = DATA / "jobs"
CATALOG_DB = DATA / "clubs.db"
SYSTEM_PROMPT_FILE = ROOT / "prompts" / "huskymatch_system.md"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

MODEL = os.environ.get("HUSKYMATCH_MODEL", "claude-opus-5-5")
RESEARCHERS = int(os.environ.get("HUSKYMATCH_RESEARCHERS", "3"))  # parallel research agents per student
TARGET_CARDS = int(os.environ.get("HUSKYMATCH_TARGET_CARDS", "13"))  # aim for 10–15 cards per student
CATALOG_MAX_AGE_DAYS = float(os.environ.get("HUSKYMATCH_CATALOG_DAYS", "14"))  # older catalog entries get re-researched
LIMITS_DB = DATA / "limits.db"
MAX_JOBS_PER_IP_PER_DAY = int(os.environ.get("HUSKYMATCH_MAX_JOBS_PER_IP_PER_DAY", "3"))  # new research runs per visitor
DAILY_BUDGET_USD = float(os.environ.get("HUSKYMATCH_DAILY_BUDGET_USD", "20"))  # across all visitors, per UTC day
JOB_COST_RESERVE_USD = float(os.environ.get("HUSKYMATCH_JOB_COST_RESERVE_USD", "3"))  # a new run needs this much left
