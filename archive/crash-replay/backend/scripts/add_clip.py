"""Import a local video file as a clip: python scripts/add_clip.py <path> <clip_id> [--title TITLE].

The source is copied into data/clips/<id>/ (gitignored). Use this for personal footage that must not be committed.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.store import Clip  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("clip_id")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()
    if not args.path.exists():
        sys.exit(f"no such file: {args.path}")
    clip = Clip(args.clip_id)
    clip.dir.mkdir(parents=True, exist_ok=True)
    for old in clip.dir.glob("source.*"):
        old.unlink()
    dest = clip.dir / f"source{args.path.suffix.lower()}"
    shutil.copy2(args.path, dest)
    clip.write_meta({"id": clip.id, "title": args.title or args.path.stem, "curated": False, "private": True,
                     "license": "User's own footage (private; do not publish)", "created": time.time()})
    print(f"added {clip.id} <- {args.path} ({dest.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
