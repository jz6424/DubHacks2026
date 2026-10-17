"""Is the recording vehicle moving? Background image motion, measured away from every tracked road user.

Sparse optical flow (Lucas-Kanade) between consecutive video frames on features outside dilated actor boxes and
outside the recording vehicle's own body/overlay (pixels that never change during the clip). The median feature
displacement per frame is near zero when the camera is stationary. When road users cover most of the frame there is
too little background left, and the state is reported as unknown rather than guessed.
"""
from typing import Callable

import cv2
import numpy as np

from .store import Clip

STILL_PX = 0.06  # median background motion per frame below this: stationary
MOVING_PX = 0.3  # above this: moving
MIN_FEATURES = 40


def _actor_boxes(actors: list[dict], t: float, W: int, H: int) -> list[tuple[int, int, int, int]]:
    out = []
    for a in actors:
        s = min(a["samples"], key=lambda s: abs(s["t"] - t))
        if abs(s["t"] - t) <= 0.2:
            x0, y0, x1, y1 = s["box"][0] * W, s["box"][1] * H, s["box"][2] * W, s["box"][3] * H
            m = max(12.0, 0.15 * max(x1 - x0, y1 - y0))  # generous: growing/shrinking boxes drag edge features
            out.append((int(x0 - m), int(y0 - m), int(x1 + m), int(y1 + m)))
    return out


def _own_body_mask(path: str, n_frames: int) -> np.ndarray | None:
    """Pixels that never change over the clip (hood, pillars, burned-in text) — but only if the camera ever moved;
    for a camera parked the whole time everything is static and this cannot separate the car from the scene."""
    cap = cv2.VideoCapture(path)
    samples = []
    for i in np.linspace(0, max(n_frames - 1, 0), 16).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok:
            samples.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release()
    if len(samples) < 8:
        return None
    std = np.stack(samples).std(axis=0)
    static = cv2.GaussianBlur((std < 4).astype(np.float32), (0, 0), 3) > 0.8
    return static if 0.02 < static.mean() < 0.6 else None


def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    ing = clip.stage("ingest")
    W, H, vfps = ing["video"]["width"], ing["video"]["height"], ing["video"]["fps"]
    actors = clip.stage("track")["actors"]
    cap = cv2.VideoCapture(str(clip.video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    body = _own_body_mask(str(clip.video), n)
    per_frame: list[tuple[float, float, int]] = []  # (t, median px/frame, features)
    prev = None  # (gray, mask, frame index)
    duplicates = 0
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = np.full(g.shape, 255, np.uint8)
        if body is not None:
            mask[body] = 0
        for x0, y0, x1, y1 in _actor_boxes(actors, i / vfps, W, H):
            mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 0
        if prev is not None and float(np.abs(g.astype(np.int16) - prev[0]).mean()) < 0.3:
            duplicates += 1  # repeated frame (frame-rate conversion): it carries no motion information
            i += 1
            continue
        if prev is not None:
            gap = i - prev[2]
            pts = cv2.goodFeaturesToTrack(prev[0], 300, 0.01, 8, mask=prev[1])
            if pts is not None and len(pts) >= MIN_FEATURES:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev[0], g, pts, None)
                good = st[:, 0] == 1
                d = (nxt - pts)[good].reshape(-1, 2)
                per_frame.append((i / vfps, float(np.median(np.hypot(d[:, 0], d[:, 1]))) / gap, int(good.sum())))
            else:
                per_frame.append((i / vfps, float("nan"), 0 if pts is None else len(pts)))
        prev = (g, mask, i)
        i += 1
        if i % 30 == 0:
            progress(i / max(n, 1), "measuring background motion")
    cap.release()

    arr = np.array(per_frame) if per_frame else np.zeros((0, 3))
    samples = []
    for f in ing["frames"]:  # summarize per analysis frame (0.25 s windows)
        sel = (arr[:, 0] >= f["t"] - 0.125) & (arr[:, 0] < f["t"] + 0.125) if len(arr) else np.zeros(0, bool)
        vals = arr[sel, 1] if sel.any() else np.array([])
        vals = vals[~np.isnan(vals)]
        if len(vals) < max(2, sel.sum() // 2):
            state, px = "unknown", None
        else:
            px = float(np.median(vals))
            state = "stationary" if px < STILL_PX else ("moving" if px > MOVING_PX else "creeping")
        samples.append({"t": f["t"], "bg_px_per_frame": None if px is None else round(px, 3), "state": state})

    # Merge into intervals; tiny gaps of another state inside a long interval are kept as-is (reported, not hidden).
    intervals: list[dict] = []
    for s in samples:
        if intervals and intervals[-1]["state"] == s["state"]:
            intervals[-1]["t_end"] = s["t"]
        else:
            intervals.append({"state": s["state"], "t_start": s["t"], "t_end": s["t"]})
    counts = {k: sum(1 for s in samples if s["state"] == k) for k in ("stationary", "creeping", "moving", "unknown")}
    return {"samples": samples, "intervals": intervals, "own_body_masked": body is not None,
            "duplicate_frames": duplicates,
            "thresholds_px_per_frame": {"stationary_below": STILL_PX, "moving_above": MOVING_PX},
            "summary": ", ".join(f"{k} {100 * v / max(len(samples), 1):.0f}%" for k, v in counts.items() if v)}
