"""Deterministic multi-object tracking on per-frame detections.

1. Frame-to-frame association: Hungarian on (1 - IoU) against constant-velocity predictions, with a centre-distance
   fallback for small/fast boxes; tracks coast up to MAX_COAST frames.
2. Repair: rejoin a track that ends with one that starts shortly after, nearby and of a compatible class (the spike
   saw IDs break at occlusions and when a car flipped).
3. Manual overrides (data/clips/<id>/overrides.json: {"merge": [[a, b]], "hide": [id], "labels": {id: "..."}})
   applied last and recorded, so the UI can show which IDs were hand-corrected.
"""
import json
from typing import Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

from .store import Clip

MAX_COAST = 3  # frames (0.75 s at 4 fps)
REPAIR_GAP = 6  # frames (1.5 s)
MIN_ACTOR_FRAMES = 4  # 1 s
MIN_ACTOR_HEIGHT_PX = 24
GROUPS = {"car": "vehicle", "truck": "vehicle", "bus": "vehicle", "van": "vehicle", "suv": "vehicle",
          "motorcycle": "two_wheeler", "bicycle": "two_wheeler", "person": "person"}
PREFIX = {"vehicle": "V", "two_wheeler": "B", "person": "P"}


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _center_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2))


def _diag(a: np.ndarray) -> float:
    return float(np.hypot(a[2] - a[0], a[3] - a[1]))


def _match_cost(pred: np.ndarray, det: np.ndarray) -> float:
    iou = _iou(pred, det)
    if iou > 0.1:
        return 1.0 - iou
    if _center_dist(pred, det) < 0.5 * max(_diag(pred), _diag(det)):
        return 0.95
    return 9.0


def associate(frames: list[dict], W: int, H: int) -> dict[int, dict]:
    tracks: dict[int, dict] = {}  # id -> {box, vel, miss, group, obs: {frame: (box, cls)}}
    live: list[int] = []
    nid = 0
    scale = np.array([W, H, W, H], float)
    for f in frames:
        i = f["i"]
        dets = [(np.array([b["x0"], b["y0"], b["x1"], b["y1"]]) * scale, b["cls"]) for b in f["boxes"]
                if (b["y1"] - b["y0"]) * H >= 6]
        preds = [tracks[k]["box"] + tracks[k]["vel"] for k in live]
        pairs: list[tuple[int, int]] = []
        if live and dets:
            cost = np.array([[_match_cost(p, d[0]) if GROUPS.get(d[1], "vehicle") == tracks[k]["group"] else 9.0
                              for d in dets] for k, p in zip(live, preds)])
            rows, cols = linear_sum_assignment(cost)
            pairs = [(live[r], c) for r, c in zip(rows, cols) if cost[r, c] < 0.96]
        matched_dets = {c for _, c in pairs}
        matched_tracks = {k for k, _ in pairs}
        for k, c in pairs:
            box, cls = dets[c]
            t = tracks[k]
            t["vel"] = 0.5 * t["vel"] + 0.5 * (box - t["box"])
            t["box"], t["miss"] = box, 0
            t["obs"][i] = (box, cls)
        for k in list(live):
            if k in matched_tracks:
                continue
            t = tracks[k]
            t["miss"] += 1
            t["box"] = t["box"] + t["vel"]
            if t["miss"] > MAX_COAST:
                live.remove(k)
        for c, (box, cls) in enumerate(dets):
            if c in matched_dets:
                continue
            tracks[nid] = {"box": box, "vel": np.zeros(4), "miss": 0, "group": GROUPS.get(cls, "vehicle"),
                           "obs": {i: (box, cls)}}
            live.append(nid)
            nid += 1
    return tracks


def _extrapolate(obs: dict[int, tuple], to_frame: int) -> np.ndarray:
    ks = sorted(obs)
    last = obs[ks[-1]][0]
    if len(ks) < 2:
        return last
    prev = obs[ks[-2]][0]
    step = (last - prev) / (ks[-1] - ks[-2])
    return last + step * (to_frame - ks[-1])


def repair(tracks: dict[int, dict]) -> list[tuple[int, int]]:
    """Greedily merge track pairs across short gaps. Returns the merges performed (kept_id, absorbed_id)."""
    by_start: dict[int, list[int]] = {}
    for k, t in tracks.items():
        by_start.setdefault(min(t["obs"]), []).append(k)
    candidates = []
    for a, ta in tracks.items():
        if len(ta["obs"]) < 2:
            continue  # single detections are too noisy to extend
        end_a = max(ta["obs"])
        la = ta["obs"][end_a][0]
        for start_b in range(end_a + 1, end_a + REPAIR_GAP + 1):
            for b in by_start.get(start_b, []):
                tb = tracks[b]
                if tb["group"] != ta["group"]:
                    continue
                bb = tb["obs"][start_b][0]
                if not (0.4 < _diag(bb) / max(_diag(la), 1e-6) < 2.5):
                    continue
                pa = _extrapolate(ta["obs"], start_b)
                d = _center_dist(pa, bb) / max(_diag(la), 1.0)
                if d > 1.0 and _iou(pa, bb) < 0.1:
                    continue
                candidates.append((start_b - end_a + 2 * d, a, b))
    # Greedy: each track gets at most one successor and one predecessor; chains resolve through `root`.
    has_succ, has_pred, root, merges = set(), set(), {}, []

    def find(k: int) -> int:
        while k in root:
            k = root[k]
        return k

    for _, a, b in sorted(candidates):
        if a in has_succ or b in has_pred:
            continue
        ra = find(a)
        if ra == find(b):
            continue
        has_succ.add(a)
        has_pred.add(b)
        root[b] = ra
        merges.append((ra, b))
    for keep, absorb in merges:
        k = find(keep)
        if absorb in tracks and k in tracks and k != absorb:
            tracks[k]["obs"].update(tracks.pop(absorb)["obs"])
    return merges


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    ing = clip.stage("ingest")
    W, H = ing["video"]["width"], ing["video"]["height"]
    frames = clip.stage("detect")["frames"]
    t_of = {f["i"]: f["t"] for f in frames}
    progress(0.1, "associating")
    tracks = associate(frames, W, H)
    raw_count = len(tracks)
    progress(0.5, "repairing gaps")
    merges = repair(tracks)

    # Keep tracks that persist and are big enough to matter; renumber by first appearance.
    def is_actor(t: dict) -> bool:
        hs = [o[0][3] - o[0][1] for o in t["obs"].values()]
        return len(t["obs"]) >= MIN_ACTOR_FRAMES and max(hs) >= MIN_ACTOR_HEIGHT_PX

    kept = sorted((t for t in tracks.values() if is_actor(t)), key=lambda t: min(t["obs"]))
    counters: dict[str, int] = {}
    out = []
    for t in kept:
        classes = [o[1] for o in t["obs"].values()]
        cls = max(set(classes), key=classes.count)
        p = PREFIX[t["group"]]
        counters[p] = counters.get(p, 0) + 1
        ks = sorted(t["obs"])
        samples = []
        for a, b in zip(ks, ks[1:] + [None]):
            box = t["obs"][a][0]
            samples.append({"i": a, "t": t_of[a], "box": _norm(box, W, H), "interp": False})
            if b is not None and b - a > 1:  # fill coasted gaps by linear interpolation, flagged
                nb = t["obs"][b][0]
                for j in range(a + 1, b):
                    w = (j - a) / (b - a)
                    samples.append({"i": j, "t": t_of.get(j, j / 4), "box": _norm(box * (1 - w) + nb * w, W, H),
                                    "interp": True})
        out.append({"id": f"{p}{counters[p]}", "cls": cls, "group": t["group"], "samples": samples,
                    "manual": False, "label": None})

    overrides_path = clip.dir / "overrides.json"
    applied = []
    if overrides_path.exists():
        ov = json.loads(overrides_path.read_text())
        by_id = {a["id"]: a for a in out}
        for keep, absorb in ov.get("merge", []):
            if keep in by_id and absorb in by_id:
                seen = {s["i"] for s in by_id[keep]["samples"]}
                by_id[keep]["samples"] = sorted(by_id[keep]["samples"] + [s for s in by_id[absorb]["samples"]
                                                                          if s["i"] not in seen], key=lambda s: s["i"])
                by_id[keep]["manual"] = True
                out.remove(by_id.pop(absorb))
                applied.append(f"merged {absorb} into {keep}")
        for hid in ov.get("hide", []):
            if hid in by_id:
                out.remove(by_id.pop(hid))
                applied.append(f"hid {hid}")
        for aid, label in ov.get("labels", {}).items():
            if aid in by_id:
                by_id[aid]["label"] = label

    return {"actors": out, "raw_tracks": raw_count, "auto_merges": len(merges), "overrides": applied,
            "summary": f"{len(out)} actors ({raw_count} raw tracks, {len(merges)} gap repairs)"}


def _norm(box: np.ndarray, W: int, H: int) -> list[float]:
    return [round(float(box[0]) / W, 4), round(float(box[1]) / H, 4), round(float(box[2]) / W, 4),
            round(float(box[3]) / H, 4)]
