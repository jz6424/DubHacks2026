"""Compare native Mk1.5 tracks vs per-frame detection + IoU/Hungarian association; render eyeball sheets."""
import glob
import json
import sys
from collections import defaultdict

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from common import OUT, extract_frames

clip, end = sys.argv[1], float(sys.argv[2])
check_ts = [float(x) for x in sys.argv[3].split(",")]
frames = extract_frames(clip, fps=4, start=0, end=end)
t_of = [t / 1000 for _, t in frames]
W, H = 1280, cv2.imread(str(frames[0][0])).shape[0]


def snap(t):
    return int(np.argmin([abs(t - x) for x in t_of]))


def to_px(b):
    return (b["top_left"]["x"] * W / 1000, b["top_left"]["y"] * H / 1000,
            b["bottom_right"]["x"] * W / 1000, b["bottom_right"]["y"] * H / 1000)


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


# --- native tracks: per window, stitched across windows by IoU at the overlap frame
native = defaultdict(dict)  # track_id -> {frame_idx: (box, cls)}
next_id = 0
for f in sorted(glob.glob(str(OUT / f"track_native_{clip}_4fps_low_w*.json"))):
    rec = json.loads(open(f).read())
    for tr in rec["tracks"]:
        pts = {snap(p["t"]): to_px(p) for p in tr["points"] if p.get("t") is not None}
        if not pts:
            continue
        first = min(pts)
        best, best_iou = None, 0.3
        for tid, d in native.items():
            if first in d and iou(d[first][0], pts[first]) > best_iou:
                best, best_iou = tid, iou(d[first][0], pts[first])
        if best is None:
            best, next_id = next_id, next_id + 1
        for k, v in pts.items():
            native[best][k] = (v, tr.get("mention"))

# --- per-frame detections
dets = []
for i, (_, t) in enumerate(frames):
    p = OUT / f"det_{clip}_{t:06d}_none.json"
    rec = json.loads(p.read_text()) if p.exists() else {"boxes": []}
    dets.append([(to_px(b), b.get("mention")) for b in rec["boxes"]])

# --- IoU + Hungarian tracker with constant-velocity prediction and 2-frame coasting
tracks = {}  # id -> dict(box, vel, miss, hist)
hung = defaultdict(dict)
nid = 0
for i, ds in enumerate(dets):
    ids = list(tracks)
    pred = [np.array(tracks[k]["box"]) + tracks[k]["vel"] for k in ids]
    if ids and ds:
        cost = np.array([[1 - iou(p, d[0]) if (d[1] == tracks[k]["cls"] or {d[1], tracks[k]["cls"]} <= {"car", "truck", "bus"}) else 1
                          for d in ds] for k, p in zip(ids, pred)])
        r, c = linear_sum_assignment(cost)
        pairs = [(ids[a], b) for a, b in zip(r, c) if cost[a, b] < 0.8]
    else:
        pairs = []
    used = {b for _, b in pairs}
    for k, b in pairs:
        nb = np.array(ds[b][0])
        tracks[k]["vel"] = 0.5 * tracks[k]["vel"] + 0.5 * (nb - np.array(tracks[k]["box"]))
        tracks[k]["box"], tracks[k]["miss"] = nb, 0
        hung[k][i] = (tuple(nb), ds[b][1])
    for k in set(ids) - {k for k, _ in pairs}:
        tracks[k]["miss"] += 1
        tracks[k]["box"] = np.array(tracks[k]["box"]) + tracks[k]["vel"]
        if tracks[k]["miss"] > 2:
            del tracks[k]
    for b, d in enumerate(ds):
        if b not in used:
            tracks[nid] = {"box": np.array(d[0]), "vel": np.zeros(4), "miss": 0, "cls": d[1]}
            hung[nid][i] = (d[0], d[1])
            nid += 1


def summarize(name, T):
    long = {k: v for k, v in T.items() if len(v) >= 8}  # >= 2 s
    cover = [len(v) for v in long.values()]
    per_frame = [sum(1 for v in T.values() if i in v) for i in range(len(frames))]
    print(f"{name:9s} ids={len(T):3d} ids>=2s={len(long):3d} median_len={np.median(cover) if cover else 0:.0f}f "
          f"objs/frame median={np.median(per_frame):.0f} frames_with_0={sum(x == 0 for x in per_frame)}")
    return per_frame


print(clip, f"{len(frames)} frames; per-frame dets median={np.median([len(d) for d in dets]):.0f}")
summarize("native", native)
summarize("hungarian", hung)

# --- eyeball sheet: native (top) vs hungarian (bottom) at check timestamps
rng = np.random.default_rng(3)
pal = {}


def color(k):
    if k not in pal:
        pal[k] = tuple(int(x) for x in rng.integers(60, 255, 3))
    return pal[k]


cells = []
for name, T, pre in (("native", native, "N"), ("hungarian", hung, "H")):
    row = []
    for ts in check_ts:
        i = snap(ts)
        img = cv2.imread(str(frames[i][0]))
        for k, d in T.items():
            if i in d:
                x0, y0, x1, y1 = map(int, d[i][0])
                cv2.rectangle(img, (x0, y0), (x1, y1), color((pre, k)), 2)
                cv2.putText(img, f"{pre}{k}:{(d[i][1] or '?')[:5]}", (x0, max(12, y0 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color((pre, k)), 2)
        cv2.putText(img, f"{name} t={t_of[i]:.2f}s", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        row.append(cv2.resize(img, (640, int(H / 2))))
    cells.append(np.hstack(row))
cv2.imwrite(str(OUT / f"eyeball_{clip}.jpg"), np.vstack(cells))
json.dump({"native": {str(k): {str(i): v for i, v in d.items()} for k, d in native.items()},
           "hungarian": {str(k): {str(i): v for i, v in d.items()} for k, d in hung.items()}, "t": t_of},
          open(OUT / f"tracks_{clip}.json", "w"))
