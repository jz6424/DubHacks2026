"""Per-frame road-user boxes from Mk1.5. The spike showed native video tracks drift and miss actors, so tracking is
done deterministically in track.py on top of these per-frame detections."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from ..config import MODEL_CONCURRENCY
from ..model import detect_frame
from .store import Clip


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    frames = clip.stage("ingest")["frames"]
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(MODEL_CONCURRENCY) as ex:
        futs = {ex.submit(detect_frame, clip.frames_dir / f["file"], clip.cache_dir / "detect" / f"{f['i']:05d}.json"): f
                for f in frames}
        for n, fut in enumerate(as_completed(futs), 1):
            f = futs[fut]
            results[f["i"]] = fut.result()
            progress(n / len(frames), f"{n}/{len(frames)} frames")

    out, prompt_tok, compl_tok = [], 0, 0
    for f in frames:
        r = results[f["i"]]
        u = r.get("usage") or {}
        prompt_tok += u.get("prompt_tokens", 0)
        compl_tok += u.get("completion_tokens", 0)
        # Model boxes are normalized to 0-1000; store as 0-1 so later stages are resolution-independent.
        boxes = [{"x0": b["x0"] / 1000, "y0": b["y0"] / 1000, "x1": b["x1"] / 1000, "y1": b["y1"] / 1000,
                  "cls": (b.get("label") or "unknown").lower()} for b in r["boxes"]]
        out.append({"i": f["i"], "t": f["t"], "boxes": boxes})
    n_boxes = sum(len(f["boxes"]) for f in out)
    return {"frames": out, "usage": {"prompt_tokens": prompt_tok, "completion_tokens": compl_tok},
            "summary": f"{n_boxes} boxes over {len(out)} frames"}
