"""Suggest which tracks are the same vehicle across gaps the tracker can't bridge (occlusion, a rollover, leaving and
re-entering view). Suggestions only: the user accepts or rejects them; nothing is merged automatically.

Candidates: track A ends and track B (same kind of road user) starts within MAX_GAP_S, with B's first box within a
generous image distance of A's last box. Mk1.5 compares a crop of each (it handled "same Kia, now overturned" and
"different colour and shape" correctly in testing).
"""
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import cv2
import numpy as np

from ..config import MODEL_CONCURRENCY
from ..model import same_vehicle
from .relevance import auto_tier, signals
from .store import Clip
from .track import load_overrides, remap_ids

MAX_GAP_S = 6.0
MAX_CHECKS = 15
PER_TRACK = 3
MIN_SAMPLES = 4
MIN_HEIGHT_PX = 30


def _best(samples: list[dict], H: int, W: int) -> dict | None:
    """Largest untruncated box among the given samples (the clearest view)."""
    ok = [s for s in samples if not s["interp"] and s["box"][0] > 0.005 and s["box"][2] < 0.995]
    ok = ok or [s for s in samples if not s["interp"]]
    if not ok:
        return None
    return max(ok, key=lambda s: (s["box"][2] - s["box"][0]) * W * (s["box"][3] - s["box"][1]) * H)


def _crop(clip: Clip, frame_file: str, box: list[float], out: Path) -> str:
    img = cv2.imread(str(clip.frames_dir / frame_file))
    H, W = img.shape[:2]
    x0, y0, x1, y1 = box
    pw, ph = (x1 - x0) * 0.15, (y1 - y0) * 0.15
    c = img[max(0, int((y0 - ph) * H)):int((y1 + ph) * H) + 1, max(0, int((x0 - pw) * W)):int((x1 + pw) * W) + 1]
    if c.shape[1] < 160:
        k = 160 / max(c.shape[1], 1)
        c = cv2.resize(c, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    key = hashlib.sha1(f"{frame_file}{box}".encode()).hexdigest()[:12]
    path = out / f"crop_{key}.jpg"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), c)
    return str(path)


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    ing = clip.stage("ingest")
    W, H = ing["video"]["width"], ing["video"]["height"]
    files = {f["i"]: f["file"] for f in ing["frames"]}
    actors = [a for a in clip.stage("track")["actors"]
              if a.get("user_tier") != "hidden" and sum(not s["interp"] for s in a["samples"]) >= MIN_SAMPLES
              and max((s["box"][3] - s["box"][1]) * H for s in a["samples"]) >= MIN_HEIGHT_PX]
    # Only follow road users that matter: a lost background car isn't worth the user's attention.
    geo = clip.stage("geometry")
    mode = geo["calibration"].get("mode", "lanes")
    relevant = set()
    for a in actors:
        g = geo["actors"].get(a["id"], [])
        tier = a.get("user_tier") or auto_tier(signals(a, g, geo["ego"]["samples"], mode == "monocular"), mode, False)[0]
        if tier in ("involved", "nearby"):
            relevant.add(a["id"])
    cands = []
    for a in actors:
        if a["id"] not in relevant:
            continue
        end = _best(a["samples"][-6:], H, W)
        if end is None:
            continue
        ae = a["samples"][-1]["t"]
        ah = (end["box"][3] - end["box"][1])
        ac = ((end["box"][0] + end["box"][2]) / 2, (end["box"][1] + end["box"][3]) / 2)
        for b in actors:
            if b is a or b["group"] != a["group"]:
                continue
            gap = b["samples"][0]["t"] - ae
            if not (-0.25 <= gap <= MAX_GAP_S) or b["samples"][0]["t"] <= a["samples"][0]["t"]:
                continue
            start = _best(b["samples"][:6], H, W)
            if start is None:
                continue
            bc = ((start["box"][0] + start["box"][2]) / 2, (start["box"][1] + start["box"][3]) / 2)
            bh = start["box"][3] - start["box"][1]
            dist = np.hypot(bc[0] - ac[0], bc[1] - ac[1]) / max(ah, bh, 1e-3)
            if dist > 2.0 + 1.5 * max(gap, 0) or not (0.2 < bh / max(ah, 1e-3) < 5):
                continue
            cands.append((max(gap, 0) + dist, a, end, b, start, gap))
    # at most two candidates per ending track, best-scored first, capped overall
    per_a: dict[str, int] = {}
    chosen = []
    for c in sorted(cands, key=lambda c: c[0]):
        if per_a.get(c[1]["id"], 0) < PER_TRACK and len(chosen) < MAX_CHECKS:
            per_a[c[1]["id"]] = per_a.get(c[1]["id"], 0) + 1
            chosen.append(c)

    out_dir = clip.cache_dir / "reid"
    rejected = {tuple(x) for x in remap_ids(load_overrides(clip), clip.stage("track")["actors"])[0].get("rejected_links", [])}
    chosen = [c for c in chosen if (c[1]["id"], c[3]["id"]) not in rejected]

    def check(c):
        _, a, end, b, start, gap = c
        ca = _crop(clip, files[end["i"]], end["box"], out_dir)
        cb = _crop(clip, files[start["i"]], start["box"], out_dir)
        key = hashlib.sha1(f"{ca}|{cb}".encode()).hexdigest()[:16]
        r = same_vehicle(ca, end["t"], cb, start["t"], out_dir / f"q_{key}.json")
        d = r["data"] or {"same_vehicle": "unsure", "reason": ""}
        return {"keep": a["id"], "absorb": b["id"], "verdict": d["same_vehicle"], "reason": d["reason"],
                "gap_s": round(max(gap, 0.0), 2), "a_frame": end["i"], "a_box": end["box"],
                "b_frame": start["i"], "b_box": start["box"]}

    results = []
    with ThreadPoolExecutor(MODEL_CONCURRENCY) as ex:
        for n, r in enumerate(ex.map(check, chosen), 1):
            results.append(r)
            progress(n / max(len(chosen), 1), f"{n}/{len(chosen)} comparisons")
    # One link per track end and per track start: a track can't continue two different vehicles.
    order = {"yes": 0, "unsure": 1}
    score = {(c[1]["id"], c[3]["id"]): c[0] for c in chosen}
    used_a, used_b, suggestions = set(), set(), []
    for r in sorted((r for r in results if r["verdict"] in order),
                    key=lambda r: (order[r["verdict"]], score[(r["keep"], r["absorb"])])):
        if r["keep"] in used_a or r["absorb"] in used_b:
            continue
        used_a.add(r["keep"])
        used_b.add(r["absorb"])
        suggestions.append(r)
    return {"suggestions": suggestions, "checked": len(results), "candidates": len(cands),
            "summary": f"{sum(r['verdict'] == 'yes' for r in results)} likely same-vehicle links in {len(results)} checks"}
