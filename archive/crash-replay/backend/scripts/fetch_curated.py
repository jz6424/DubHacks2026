"""Download the curated demo clips listed in backend/curated.json into data/clips/<id>/ with their metadata."""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import CURATED  # noqa: E402
from app.pipeline.store import Clip  # noqa: E402

UA = "CrashReplay/0.1 (DubHacks 2026 hackathon demo)"


def main() -> None:
    for item in json.loads(CURATED.read_text()):
        clip = Clip(item["id"])
        clip.dir.mkdir(parents=True, exist_ok=True)
        ext = "." + item["url"].split("?")[0].rsplit(".", 1)[-1]
        dest = clip.dir / f"source{ext}"
        if not dest.exists():
            print("downloading", item["id"])
            req = urllib.request.Request(item["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req) as r, open(dest, "wb") as out:
                out.write(r.read())
        meta = {k: v for k, v in item.items() if k != "url"}
        clip.write_meta({**clip.meta(), **meta, "curated": True, "created": clip.meta().get("created", time.time())})
        print("ready", item["id"], dest.stat().st_size // 1024, "KiB")


if __name__ == "__main__":
    main()
