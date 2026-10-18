"""Runs the stages in order. Each stage's output is cached as stages/<name>.json and skipped when present."""
import threading
import traceback
from typing import Callable

from . import detect, geometry, ingest, motion, ocr, plates, reid, scene, track
from .store import STAGES, Clip

StageFn = Callable[[Clip, Callable[[float, str], None]], dict]
RUNNERS: dict[str, StageFn] = {
    "ingest": ingest.run,
    "detect": detect.run,
    "track": track.run,
    "reid": reid.run,
    "plates": plates.run,
    "ocr": ocr.run,
    "motion": motion.run,
    "geometry": geometry.run,
    "scene": scene.run,
}
_active: set[str] = set()
_active_lock = threading.Lock()


# Stages whose output depends on which detections belong to which road user. User corrections (merges, tiers,
# labels) only need these re-run; motion, plates and OCR don't change.
IDENTITY_STAGES = ["track", "reid", "geometry", "scene"]


def run_pipeline(clip: Clip, force_from: str | None = None, rerun: list[str] | None = None) -> None:
    with _active_lock:
        if clip.id in _active:
            return
        _active.add(clip.id)
    try:
        if force_from:
            clip.clear_stages(force_from)
        for name in rerun or []:
            (clip.stages_dir / f"{name}.json").unlink(missing_ok=True)
        clip.update_status(state="running", error=None)
        for name in STAGES:
            if clip.has_stage(name):
                clip.update_status(name, state="done", progress=1.0)
                continue
            clip.update_status(name, state="running", progress=0.0, message="")

            def progress(p: float, msg: str = "", _name: str = name) -> None:
                clip.update_status(_name, progress=round(min(max(p, 0.0), 1.0), 3), message=msg)

            try:
                out = RUNNERS[name](clip, progress)
            except Exception as e:  # noqa: BLE001 - surface any stage failure to the UI
                traceback.print_exc()
                clip.update_status(name, state="error", message=str(e)[:500])
                clip.update_status(state="error", error=f"{name}: {e}"[:500])
                return
            clip.write_stage(name, out)
            clip.update_status(name, state="done", progress=1.0, message=out.get("summary", "") if isinstance(out, dict) else "")
        clip.update_status(state="done")
    finally:
        with _active_lock:
            _active.discard(clip.id)


def start_background(clip: Clip, force_from: str | None = None, rerun: list[str] | None = None) -> None:
    threading.Thread(target=run_pipeline, args=(clip, force_from, rerun), daemon=True).start()


def is_running(clip: Clip) -> bool:
    with _active_lock:
        return clip.id in _active
