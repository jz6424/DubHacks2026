"""Licence plates on tracked vehicles: a known-size ruler for distance (US/Canada plates are 30.5 x 15.2 cm) and the
regions to blur in any exported image. Only frames where some vehicle is large enough for a plate to be legible are
sent to the model."""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..config import MODEL_CONCURRENCY
from ..model import detect_frame
from .store import Clip

MIN_VEHICLE_HEIGHT_PX = 80


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    ing = clip.stage("ingest")
    H = ing["video"]["height"]
    actors = [a for a in clip.stage("track")["actors"] if a["group"] == "vehicle"]
    frames = {f["i"]: f for f in ing["frames"]}
    wanted = sorted({s["i"] for a in actors for s in a["samples"]
                     if not s["interp"] and (s["box"][3] - s["box"][1]) * H >= MIN_VEHICLE_HEIGHT_PX})
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(MODEL_CONCURRENCY) as ex:
        futs = {i: ex.submit(detect_frame, clip.frames_dir / frames[i]["file"],
                             clip.cache_dir / "plates" / f"{i:05d}.json", ["license plate"]) for i in wanted}
        for n, (i, fut) in enumerate(futs.items(), 1):
            results[i] = fut.result()
            progress(n / max(len(wanted), 1), f"{n}/{len(wanted)} frames")

    out, attached = [], 0
    for i in wanted:
        t = frames[i]["t"]
        for b in results[i]["boxes"]:
            box = [b["x0"] / 1000, b["y0"] / 1000, b["x1"] / 1000, b["y1"] / 1000]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            # attach to the smallest vehicle box containing the plate centre at this frame
            owner, best = None, 9.0
            for a in actors:
                s = next((s for s in a["samples"] if s["i"] == i), None)
                if s and s["box"][0] <= cx <= s["box"][2] and s["box"][1] <= cy <= s["box"][3]:
                    area = (s["box"][2] - s["box"][0]) * (s["box"][3] - s["box"][1])
                    if area < best:
                        owner, best = a["id"], area
            attached += owner is not None
            out.append({"i": i, "t": t, "box": [round(x, 4) for x in box], "actor": owner})
    return {"plates": out, "frames_checked": len(wanted),
            "summary": f"{len(out)} plates in {len(wanted)} frames ({attached} attached to a vehicle)"}
