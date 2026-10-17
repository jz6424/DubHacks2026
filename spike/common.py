"""Shared helpers for the go/no-go spike: env loading, frame extraction, timed model calls with caching."""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIPS = ROOT / "clips"
FRAMES = ROOT / "frames"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

MODEL = "perceptron-mk1.5"


def load_env() -> None:
    env = ROOT.parent / ".env"
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()


def extract_frames(clip: str, fps: float, start: float = 0.0, end: float | None = None, width: int = 1280) -> list[tuple[Path, int]]:
    """Extract frames with ffmpeg; returns [(path, t_ms)] where t_ms is on the original clip timeline."""
    src = CLIPS / f"{clip}.webm"
    d = FRAMES / f"{clip}_{fps:g}fps_{start:g}_{end}"
    if not d.exists():
        d.mkdir(parents=True)
        cmd = ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-i", str(src)]
        if end is not None:
            cmd += ["-t", str(end - start)]
        cmd += ["-vf", f"fps={fps},scale={width}:-2", "-q:v", "3", str(d / "f_%04d.jpg")]
        subprocess.run(cmd, check=True)
    files = sorted(d.glob("f_*.jpg"))
    return [(f, int(round((start + i / fps) * 1000))) for i, f in enumerate(files)]


def timed(name: str, fn, *args, **kwargs):
    """Run a model call, record latency/usage/raw text to out/<name>.json, and return (result, record)."""
    cached = OUT / f"{name}.json"
    if cached.exists():
        rec = json.loads(cached.read_text())
        return None, rec
    for attempt in range(6):
        t0 = time.time()
        try:
            res = fn(*args, **kwargs)
            break
        except Exception as e:  # rate limit (Cloudflare 1015) or transient 5xx
            msg = str(e)
            if attempt == 5 or not ("rate limit" in msg.lower() or "1015" in msg or "50" in msg[:400]):
                raise
            print(f"[{name}] retry {attempt + 1}: {msg.strip().splitlines()[0][:80] if msg.strip() else type(e).__name__}")
            time.sleep(2 * 2 ** attempt)
    dt = time.time() - t0
    rec = {
        "name": name,
        "latency_s": round(dt, 2),
        "usage": _jsonable(getattr(res, "usage", None)),
        "finish_reason": getattr(res, "finish_reason", None),
        "text": getattr(res, "text", None),
        "reasoning": getattr(res, "reasoning", None),
        "tracks": [_jsonable(t) for t in (getattr(res, "tracks", None) or [])],
        "boxes": [_jsonable(b) for b in (getattr(res, "boxes", None) or [])],
        "clips": [_jsonable(c) for c in (getattr(res, "clips", None) or [])],
    }
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(f"[{name}] {dt:.1f}s usage={rec['usage']} finish={rec['finish_reason']} "
          f"tracks={len(rec['tracks'])} boxes={len(rec['boxes'])} clips={len(rec['clips'])}")
    return res, rec


def _jsonable(o):
    if o is None:
        return None
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if isinstance(o, dict):
        return o
    return getattr(o, "__dict__", str(o))
