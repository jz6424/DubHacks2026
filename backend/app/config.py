"""Paths and settings. Loads the repo-root .env without overriding real environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CLIPS = DATA / "clips"
CURATED = Path(__file__).resolve().parents[1] / "curated.json"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

MODEL = os.environ.get("PERCEPTRON_MODEL", "perceptron-mk1.5")
MODEL_CONCURRENCY = int(os.environ.get("MODEL_CONCURRENCY", "3"))  # 8 concurrent tripped Cloudflare 1015

FRAME_FPS = 4.0  # analysis frame rate
FRAME_WIDTH = 1280
MAX_CLIP_SECONDS = 60.0

DETECT_CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle", "person"]
