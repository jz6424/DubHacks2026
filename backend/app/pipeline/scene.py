"""Assemble the single document the frontend renders: clip info, actors (boxes + road positions), ego, lanes, quality."""
from typing import Callable

from .store import Clip


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    meta = clip.meta()
    ing = clip.stage("ingest")
    trk = clip.stage("track")
    geo = clip.stage("geometry")
    ocr = clip.stage("ocr") or {"present": False, "samples": []}
    det = clip.stage("detect")

    actors = []
    for a in trk["actors"]:
        ground = geo["actors"].get(a["id"])
        actors.append({
            "id": a["id"], "cls": a["cls"], "group": a["group"], "label": a.get("label"), "manual": a.get("manual", False),
            "t_start": a["samples"][0]["t"], "t_end": a["samples"][-1]["t"],
            "boxes": [{"t": s["t"], "box": s["box"], "interp": s["interp"]} for s in a["samples"]],
            "ground": ground or [],
        })
    return {
        "clip": {"id": clip.id, "title": meta.get("title", clip.id), "source_url": meta.get("source_url"),
                 "license": meta.get("license"), "attribution": meta.get("attribution"),
                 "duration": ing["video"]["duration"], "width": ing["video"]["width"],
                 "height": ing["video"]["height"], "fps": ing["video"]["fps"]},
        "frame_fps": ing["frame_fps"],
        "frames": [f["t"] for f in ing["frames"]],
        "actors": actors,
        "ego": geo["ego"],
        "geometry": {"status": geo["status"], "calibration": geo["calibration"], "lanes": geo["lanes"],
                     "road_lines": geo.get("road_lines", [])},
        "overlay": ocr,
        "quality": geo["quality"] + [{"level": "info", "code": "notes", "message": n} for n in ing.get("notes", [])],
        "stats": {"model_tokens": det.get("usage"), "raw_tracks": trk["raw_tracks"], "auto_merges": trk["auto_merges"],
                  "overrides": trk["overrides"]},
        "summary": f"{len(actors)} actors, geometry {geo['status']}",
    }
