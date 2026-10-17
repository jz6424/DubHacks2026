"""Assemble the single document the frontend renders: clip info, actors (boxes + road positions), ego, lanes, quality."""
from typing import Callable

from .geometry import remap_plates
from .relevance import auto_tier, signals
from .store import Clip

def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    meta = clip.meta()
    ing = clip.stage("ingest")
    trk = clip.stage("track")
    geo = clip.stage("geometry")
    ocr = clip.stage("ocr") or {"present": False, "samples": []}
    det = clip.stage("detect")
    plates = remap_plates((clip.stage("plates") or {}).get("plates", []), trk["actors"])
    reid = clip.stage("reid") or {"suggestions": []}
    mode = geo["calibration"].get("mode", "lanes")
    left_edge = min((l["d"] for l in geo.get("road_lines", [])), default=None)
    motion = clip.stage("motion") or {"samples": [], "intervals": []}

    actors = []
    for a in trk["actors"]:
        ground = geo["actors"].get(a["id"])
        sig = signals(a, ground or [], geo["ego"]["samples"], mode == "monocular")
        opposite = bool(ground) and left_edge is not None and mode == "lanes" and \
            sorted(g["d"] for g in ground)[len(ground) // 2] < left_edge - 0.5
        tier, why = auto_tier(sig, mode, opposite)
        actors.append({
            "tier": a.get("user_tier") or tier, "auto_tier": tier, "tier_reason": why,
            "tier_by_user": bool(a.get("user_tier")), "signals": sig,
            "merged_from": a.get("merged_from", []),
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
        # boxes to blur in any view or export (other people's plates are personal data)
        "plates": [{"t": p["t"], "box": p["box"], "actor": p.get("actor")} for p in plates],
        "motion": {"samples": [{"t": m["t"], "state": m["state"]} for m in motion["samples"]],
                   "intervals": motion["intervals"]},
        "quality": geo["quality"] + [{"level": "info", "code": "notes", "message": n} for n in ing.get("notes", [])],
        # same-vehicle suggestions whose two tracks still both exist (accepted ones disappear after the merge)
        "suggestions": [x for x in reid["suggestions"] if x["keep"] in {a["id"] for a in trk["actors"]}
                        and x["absorb"] in {a["id"] for a in trk["actors"]}],
        "stats": {"model_tokens": det.get("usage"), "raw_tracks": trk["raw_tracks"], "auto_merges": trk["auto_merges"],
                  "overrides": trk["overrides"]},
        "summary": f"{len(actors)} actors, geometry {geo['status']}",
    }
