"""Read a burned-in dashcam overlay (time, GPS, speed). The spike read speed/time/lat 18/18 exactly on a Garmin clip.

Probes three frames first; only if a speed overlay is present does it read one frame per second.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from pydantic import BaseModel

from ..model import ask_structured
from .store import Clip


class Overlay(BaseModel):
    overlay_present: bool
    date: str | None
    time: str | None
    latitude: float | None
    longitude: float | None
    speed_value: float | None
    speed_unit: str | None


PROMPT = ("Read the dashcam text overlay burned into this frame (usually along the top or bottom edge). Report the "
          "date, time, GPS latitude/longitude and the vehicle speed with its unit exactly as shown. Use null for "
          "anything not shown. overlay_present is false if there is no burned-in text overlay.")

UNIT_TO_MPS = {"kmh": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704}


def _mps(value: float | None, unit: str | None) -> float | None:
    if value is None or not unit:
        return None
    u = re.sub(r"[^a-z]", "", unit.lower())
    return value * UNIT_TO_MPS[u] if u in UNIT_TO_MPS else None


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    frames = clip.stage("ingest")["frames"]
    fps = clip.stage("ingest")["frame_fps"]
    step = max(1, int(round(fps)))  # one frame per second
    picked = frames[::step]

    def read(f: dict) -> dict:
        r = ask_structured(clip.frames_dir / f["file"], PROMPT, Overlay, clip.cache_dir / "ocr" / f"{f['i']:05d}.json")
        return {"t": f["t"], "i": f["i"], **(r["data"] or {"overlay_present": False})}

    probe_frames = [picked[len(picked) // 4], picked[len(picked) // 2], picked[(3 * len(picked)) // 4]]
    progress(0.05, "probing for overlay")
    with ThreadPoolExecutor(3) as ex:
        probes = list(ex.map(read, probe_frames))
    with_speed = [p for p in probes if p.get("overlay_present") and _mps(p.get("speed_value"), p.get("speed_unit")) is not None]
    if len(with_speed) < 2:
        return {"present": False, "samples": [], "summary": "no speed overlay detected"}

    rows = []
    with ThreadPoolExecutor(3) as ex:
        for n, r in enumerate(ex.map(read, picked), 1):
            rows.append(r)
            progress(n / len(picked), f"{n}/{len(picked)} overlay frames")
    samples, rejected = [], 0
    for r in rows:
        v = _mps(r.get("speed_value"), r.get("speed_unit"))
        if v is None:
            continue
        # A 1 s jump of > 20 km/h is beyond hard braking (~10 m/s^2 = 36 km/h/s is crash-level); flag rather than drop.
        suspicious = bool(samples) and abs(v - samples[-1]["speed_mps"]) > 20 / 3.6 * (r["t"] - samples[-1]["t"])
        rejected += suspicious
        samples.append({"t": r["t"], "speed_mps": round(v, 3), "raw": f"{r.get('speed_value'):g} {r.get('speed_unit')}",
                        "time": r.get("time"), "lat": r.get("latitude"), "lon": r.get("longitude"),
                        "suspicious": suspicious})
    return {"present": True, "samples": samples, "flagged": rejected,
            "summary": f"speed overlay read on {len(samples)}/{len(picked)} frames"}
