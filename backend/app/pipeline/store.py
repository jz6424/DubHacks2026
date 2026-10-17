"""On-disk layout for one clip: data/clips/<id>/{meta.json, status.json, source.*, video.mp4, frames/, stages/, cache/}."""
import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from ..config import CLIPS

STAGES = ["ingest", "detect", "track", "plates", "ocr", "motion", "geometry", "scene"]
_lock = threading.Lock()


def _finite(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


class Clip:
    def __init__(self, clip_id: str):
        self.id = clip_id
        self.dir = CLIPS / clip_id
        self.frames_dir = self.dir / "frames"
        self.stages_dir = self.dir / "stages"
        self.cache_dir = self.dir / "cache"
        self.video = self.dir / "video.mp4"

    @classmethod
    def all(cls) -> list["Clip"]:
        if not CLIPS.exists():
            return []
        return [cls(p.name) for p in sorted(CLIPS.iterdir()) if (p / "meta.json").exists()]

    def exists(self) -> bool:
        return (self.dir / "meta.json").exists()

    def source(self) -> Path:
        found = sorted(self.dir.glob("source.*"))
        if not found:
            raise FileNotFoundError(f"no source video for clip {self.id}")
        return found[0]

    # --- json helpers
    def _read(self, path: Path, default: Any = None) -> Any:
        return json.loads(path.read_text()) if path.exists() else default

    def _write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        # Browsers reject NaN/Infinity in JSON; unknown numbers are null.
        tmp.write_text(json.dumps(_finite(data), allow_nan=False))
        tmp.replace(path)

    def meta(self) -> dict:
        return self._read(self.dir / "meta.json", {})

    def write_meta(self, meta: dict) -> None:
        self._write(self.dir / "meta.json", meta)

    def stage(self, name: str) -> Any:
        return self._read(self.stages_dir / f"{name}.json")

    def has_stage(self, name: str) -> bool:
        return (self.stages_dir / f"{name}.json").exists()

    def write_stage(self, name: str, data: Any) -> None:
        self._write(self.stages_dir / f"{name}.json", data)

    def clear_stages(self, from_stage: str) -> None:
        for name in STAGES[STAGES.index(from_stage):]:
            (self.stages_dir / f"{name}.json").unlink(missing_ok=True)

    # --- status
    def status(self) -> dict:
        st = self._read(self.dir / "status.json")
        if st is None:
            st = {"state": "idle", "stages": {s: {"state": "done" if self.has_stage(s) else "pending",
                                                  "progress": 1.0 if self.has_stage(s) else 0.0, "message": ""}
                                              for s in STAGES}}
        return st

    def update_status(self, stage: str | None = None, **fields: Any) -> None:
        with _lock:
            st = self.status()
            if stage is None:
                st.update(fields)
            else:
                st["stages"].setdefault(stage, {}).update(fields)
            st["updated"] = time.time()
            self._write(self.dir / "status.json", st)
