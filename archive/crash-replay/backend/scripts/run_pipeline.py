"""Run the pipeline for one clip from the command line: python scripts/run_pipeline.py <clip_id> [--from STAGE]."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.runner import run_pipeline  # noqa: E402
from app.pipeline.store import STAGES, Clip  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_id")
    ap.add_argument("--from", dest="from_stage", choices=STAGES)
    args = ap.parse_args()
    clip = Clip(args.clip_id)
    if not clip.exists():
        sys.exit(f"no such clip: {args.clip_id}")
    run_pipeline(clip, force_from=args.from_stage)
    st = clip.status()
    for name in STAGES:
        s = st["stages"].get(name, {})
        print(f"{name:9s} {s.get('state', '?'):8s} {s.get('message', '')}")
    if st.get("state") == "error":
        sys.exit(1)
    geo = clip.stage("geometry")
    if geo:
        print(json.dumps(geo["calibration"], indent=1))
        for q in geo["quality"]:
            print(f"[{q['level']}] {q['message']}")


if __name__ == "__main__":
    main()
