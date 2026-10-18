"""(c) Flat-road geometry for tesla_kia from lane lines + US dash spacing; ego speed from dash flow; actor speeds.

Model: pinhole camera, flat road, zero roll. With vanishing row y0 and lines x = a*y + b:
  lateral X = h * (x - x0) / (y - y0)      (h = camera height, from lane width W: h = W / (a_right - a_left))
  depth   Z = K / (y - y0)                 (K = f*h, from dash period P = 12.19 m)
"""
import json

import cv2
import numpy as np
from scipy.signal import savgol_filter

W_LANE, DASH, PERIOD = 3.7, 3.05, 12.19
CLIP = "clips/tesla_kia.webm"


def masks(f):
    # The footage is globally tinted (road itself is H~27,S~28), so use local brightness contrast + relative saturation.
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    tophat = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 3))) > 18
    sat = hsv[..., 1] > np.median(hsv[450:, :, 1]) + 25
    yellow = (tophat & sat).astype(np.uint8)
    white = (tophat & ~sat).astype(np.uint8)
    return yellow, white


def fit_line(ys, xs):
    if len(ys) < 20:
        return None
    a, b = np.polyfit(ys, xs, 1)
    for _ in range(3):  # trim outliers
        r = np.abs(xs - (a * ys + b))
        keep = r < max(3, np.percentile(r, 80))
        a, b = np.polyfit(ys[keep], xs[keep], 1)
    return a, b


def lanes(f, prior_white=(1.05, 276.0), prior_yellow=(-1.48, 1179.0)):
    yellow, white = masks(f)
    ys, xs = [], []
    ya, yb = prior_yellow
    for y in range(450, 715, 2):  # right edge of the double yellow (left boundary of the ego lane)
        c = int(ya * y + yb)
        lo, hi = max(0, c - 40), min(1280, c + 40)
        xx = np.nonzero(yellow[y, lo:hi])[0]
        if len(xx):
            ys.append(y)
            xs.append(lo + xx.max())
    left = fit_line(np.array(ys, float), np.array(xs, float))
    ys, xs = [], []
    a, b = prior_white
    for y in range(430, 715, 1):
        c = int(a * y + b)
        lo, hi = max(0, c - 30), min(1280, c + 30)
        xx = np.nonzero(white[y, lo:hi])[0]
        if len(xx):
            ys.append(y)
            xs.append(lo + np.median(xx))
    right = fit_line(np.array(ys, float), np.array(xs, float))
    return left, right, white


def dashes(white, right, y0, ymax=715):
    """White runs along the dashed line: list of (y_far, y_near)."""
    a, b = right
    on = []
    for y in range(int(y0) + 12, ymax):
        c = int(a * y + b)
        on.append(white[y, max(0, c - 4):c + 5].any() if 0 <= c < 1280 else False)
    segs, start = [], None
    for i, v in enumerate(on + [False]):
        y = int(y0) + 12 + i
        if v and start is None:
            start = y
        if not v and start is not None:
            if y - start >= 3:
                segs.append((start, y - 1))
            start = None
    return segs


cap = cv2.VideoCapture(CLIP)
fps = cap.get(cv2.CAP_PROP_FPS)
rows = []
prior = (1.05, 276.0)
for i in range(int(29 * fps)):
    ok, f = cap.read()
    if not ok:
        break
    t = i / fps
    left, right, white = lanes(f, prior)
    if left is None or right is None or right[0] - left[0] < 1.5 or not (0.7 < right[0] < 1.5) or not (-2.2 < left[0] < -0.9):
        rows.append({"t": t, "ok": False})
        continue
    prior = right
    y0 = (right[1] - left[1]) / (left[0] - right[0])
    x0 = left[0] * y0 + left[1]
    h = W_LANE / (right[0] - left[0])
    rows.append({"t": t, "ok": True, "y0": y0, "x0": x0, "h": h, "left": left, "right": right,
                 "dashes": dashes(white, right, y0)})
    if abs(t - 13.0) < 0.5 / fps:
        dbg = f.copy()
        for (a, b), col in ((left, (0, 255, 255)), (right, (255, 0, 255))):
            cv2.line(dbg, (int(a * (y0 + 5) + b), int(y0 + 5)), (int(a * 719 + b), 719), col, 2)
        for s, e in rows[-1]["dashes"]:
            cv2.line(dbg, (int(right[0] * s + right[1]) + 12, s), (int(right[0] * e + right[1]) + 12, e), (0, 0, 255), 4)
        cv2.circle(dbg, (int(x0), int(y0)), 6, (0, 255, 0), -1)
        cv2.imwrite("out/geom_debug_13s.jpg", dbg)

good = [r for r in rows if r["ok"]]
print(f"fps={fps:.3f} frames={len(rows)} lane fit ok={len(good)} ({100 * len(good) / len(rows):.0f}%)")
pre = [r for r in good if 4 <= r["t"] <= 14.5]  # clean road before the crash
print("y0 median/IQR", np.median([r["y0"] for r in pre]), np.percentile([r["y0"] for r in pre], [25, 75]))
print("camera height h median/IQR", np.median([r["h"] for r in pre]), np.percentile([r["h"] for r in pre], [25, 75]))

# K = f*h from consecutive dash far-ends being one PERIOD apart (only complete dashes well clear of the frame edge)
Ks = []
for r in pre:
    d = [s for s in r["dashes"] if s[1] < 700 and s[1] - s[0] >= 4]
    for (s1, _), (s2, _) in zip(d, d[1:]):
        inv = 1 / (s1 - r["y0"]) - 1 / (s2 - r["y0"])
        if inv > 0:
            Ks.append(PERIOD / inv)
Ks = np.array(Ks)
K = float(np.median(Ks)) if len(Ks) else float("nan")
print(f"K=f*h: n={len(Ks)} median={K:.0f} IQR={np.percentile(Ks, [25, 75]) if len(Ks) else None}")
h_med = float(np.median([r["h"] for r in pre]))
print(f"implied focal length f={K / h_med:.0f}px -> horizontal FOV {2 * np.degrees(np.arctan(640 / (K / h_med))):.0f} deg")

# Ego speed: track each dash far-end in ground Z between consecutive frames
ego_t, ego_v = [], []
for r1, r2 in zip(good, good[1:]):
    if r2["t"] > 15 or r1["t"] < 1:
        continue
    z1 = [K / (s - r1["y0"]) for s, e in r1["dashes"] if e < 700 and s - r1["y0"] > 20]
    z2 = [K / (s - r2["y0"]) for s, e in r2["dashes"] if e < 700 and s - r2["y0"] > 20]
    dt = r2["t"] - r1["t"]
    for z in z1:
        if not z2:
            continue
        m = min(z2, key=lambda q: abs(q - (z - 30 * dt)))  # expect ~30 m/s closing
        v = (z - m) / dt
        if 10 < v < 50 and z < 40:
            ego_t.append(r1["t"])
            ego_v.append(v)
ego_t, ego_v = np.array(ego_t), np.array(ego_v)
bins = np.arange(1, 15, 1.0)
ego_series = []
for b0 in bins:
    sel = (ego_t >= b0) & (ego_t < b0 + 1)
    if sel.sum() >= 5:
        ego_series.append((b0 + 0.5, float(np.median(ego_v[sel])), float(np.percentile(ego_v[sel], 25)),
                           float(np.percentile(ego_v[sel], 75)), int(sel.sum())))
print("ego speed per 1s bin (t, km/h median, IQR, n):")
for t, m, lo, hi, n in ego_series:
    print(f"  {t:4.1f}s {m * 3.6:5.0f} km/h [{lo * 3.6:.0f}-{hi * 3.6:.0f}] n={n}")
ego_kmh = float(np.median(ego_v)) * 3.6
print(f"ego overall median {ego_kmh:.0f} km/h")

# Actor speeds from per-frame-detect + Hungarian tracks (4 fps): H38 = white pickup, H80 = Kia (pre-crash)
tr = json.load(open("out/tracks_tesla_kia.json"))
tt = tr["t"]
y0s = {round(r["t"], 2): r for r in good}


def nearest_geom(t):
    r = min(good, key=lambda q: abs(q["t"] - t))
    return r


for tid, label in (("38", "white pickup"), ("80", "Kia (pre-impact)"), ("54", "semi truck")):
    pts = tr["hungarian"][tid]
    ts, zs, xs = [], [], []
    for i, (box, cls) in sorted(pts.items(), key=lambda kv: int(kv[0])):
        t = tt[int(i)]
        g = nearest_geom(t)
        yb, xb = box[3], (box[0] + box[2]) / 2
        if yb - g["y0"] < 8 or t > 15.2:
            continue
        ts.append(t)
        zs.append(K / (yb - g["y0"]))
        xs.append(g["h"] * (xb - g["x0"]) / (yb - g["y0"]))
    ts, zs, xs = map(np.array, (ts, zs, xs))
    if len(ts) < 7:
        print(label, "too few points", len(ts))
        continue
    zs_s = savgol_filter(zs, 7, 2)
    vrel = np.gradient(zs_s, ts)
    v_abs = ego_kmh / 3.6 + vrel
    # uncertainty: +/-2px on box bottom and y0, +/-15% on K
    dz = np.abs(K / (np.maximum(np.array([nearest_geom(t)["y0"] for t in ts]), 0) * 0 + 1))  # placeholder
    print(f"{label:18s} t={ts[0]:.1f}-{ts[-1]:.1f}s  dist ahead {zs_s.min():.0f}-{zs_s.max():.0f} m  lateral {np.median(xs):+.1f} m  "
          f"rel speed median {np.median(vrel) * 3.6:+.0f} km/h  abs speed median {np.median(v_abs) * 3.6:.0f} km/h "
          f"(p10-p90 {np.percentile(v_abs, 10) * 3.6:.0f}-{np.percentile(v_abs, 90) * 3.6:.0f})")
json.dump({"K": K, "h": h_med, "ego_kmh": ego_kmh, "ego_series": ego_series}, open("out/geometry_tesla.json", "w"))
