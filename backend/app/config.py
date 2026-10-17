import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
MEDIA_DIR = DATA / "media"
PLANS_DIR = DATA / "plans"
for d in (MEDIA_DIR, PLANS_DIR):
    d.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("PERCEPTRON_MODEL", "perceptron-mk1.5")
INGEST_REASONING = os.getenv("INGEST_REASONING", "high")
CHECK_REASONING = os.getenv("CHECK_REASONING", "low")
