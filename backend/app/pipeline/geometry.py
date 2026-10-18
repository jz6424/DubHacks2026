"""Ground-plane geometry from lane markings, ego speed, and per-actor road positions/speeds with uncertainty.

Camera model: pinhole, flat road, no roll. With vanishing point (x0, y0), a ground line at lateral offset X images as
x = x0 + a*(y - y0) with a = X/h (h = camera height). A ground point at image row y and column x is at
    depth   Z = K / (y - y0)            (K = f*h)
    lateral X = h * (x - x0) / (y - y0)
h comes from the known lane width (W = h*(aR - aL)); K comes from the known dash period along a dashed line.
Ego speed comes from the dashcam overlay if present, else from how fast the dash pattern moves toward the camera.

Positions are in a road-aligned frame: s = distance along the road (m), d = lateral offset from the ego lane centre
(m, + right). This is not GPS/world coordinates.
"""
from typing import Callable

import cv2
import numpy as np

from . import monocular
from .store import Clip

LANE_WIDTH_M = 3.7  # US freeway default; overridable per clip in meta.json
DASH_PERIOD_M = 12.19  # US: 10 ft dash + 30 ft gap
DASH_LENGTH_M = 3.05
MIN_LANE_SLOPE = 0.55  # |a| = |X|/h: a lane boundary is at least ~0.75 m from the camera
Z_MAX = 120.0
HORIZON_SIGMA_PX = 10.0  # horizon/pitch/slope uncertainty for the road-contact cue
OFF_GROUND_LOG = float(np.log(1.5))  # road contact suddenly says >50% further than size does: not on the road


# ----------------------------------------------------------------------------- lane detection (per video frame)

def _tophat(frame: np.ndarray) -> np.ndarray:
    v = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, frame.shape[1] // 60), 3))
    return cv2.morphologyEx(v, cv2.MORPH_TOPHAT, k)


def _line_mask(frame: np.ndarray, boxes_px: list[tuple[int, int, int, int]], roi: tuple[int, int]) -> np.ndarray:
    th = _tophat(frame)
    y_lo, y_hi = roi
    band = th[y_lo:y_hi]
    thr = max(15.0, float(np.percentile(band, 99.0)) * 0.5)
    mask = (th > thr).astype(np.uint8)
    mask[:y_lo] = 0
    mask[y_hi:] = 0
    for x0, y0, x1, y1 in boxes_px:  # vehicles are not lane markings
        mask[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = 0
    return mask


def _find_lanes(mask: np.ndarray, prev_vp: tuple[float, float] | None) -> dict | None:
    H, W = mask.shape
    segs = cv2.HoughLinesP(mask * 255, 1, np.pi / 180, threshold=15, minLineLength=max(12, H // 50), maxLineGap=8)
    if segs is None:
        return None
    lines = []  # (a, b, length, xm, ym) with x = a*y + b
    for x1, y1, x2, y2 in segs.reshape(-1, 4):  # OpenCV 4 returns (N,1,4), 5 returns (N,4)
        if y2 < y1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        dy = y2 - y1
        if dy < 8:
            continue
        a = (x2 - x1) / dy
        if abs(a) > 4:
            continue
        lines.append((a, x1 - a * y1, float(np.hypot(x2 - x1, dy)), (x1 + x2) / 2, (y1 + y2) / 2))
    if len(lines) < 2:
        return None
    lines.sort(key=lambda l: -l[2])
    lines = lines[:80]
    A = np.array([l[0] for l in lines])
    B = np.array([l[1] for l in lines])
    L = np.array([l[2] for l in lines])
    tol = 6 + 0.008 * W

    # Vanishing point: candidate intersections of opposite-slope pairs (plus last frame's VP), scored by support.
    cands = [prev_vp] if prev_vp else []
    for i in range(min(len(lines), 25)):
        for j in range(i + 1, min(len(lines), 25)):
            if A[i] * A[j] >= 0 or abs(A[i] - A[j]) < 0.2:
                continue
            y = (B[j] - B[i]) / (A[i] - A[j])
            if 0.15 * H < y < 0.75 * H:
                cands.append((A[i] * y + B[i], y))
    if not cands:
        return None
    best, best_score = None, 0.0
    for x, y in cands:
        score = float(L[np.abs(A * y + B - x) < tol].sum())
        if prev_vp and np.hypot(x - prev_vp[0], y - prev_vp[1]) > 0.06 * W:
            score *= 0.4  # the VP moves slowly; big jumps are usually clutter (vehicles, poles, trees)
        if score > best_score:
            best, best_score = (x, y), score
    if best is None:
        return None
    x0, y0 = best
    inl = np.abs(A * y0 + B - x0) < tol
    # Slope relative to the VP through each segment's midpoint: a' = X/h, sign gives side of the camera.
    rel = []
    for (a, b, ln, xm, ym), ok in zip(lines, inl):
        if ok and ym - y0 > 5:
            rel.append(((xm - x0) / (ym - y0), ln))
    rel.sort()
    clusters: list[list[tuple[float, float]]] = []
    for r in rel:
        if clusters and r[0] - clusters[-1][-1][0] < 0.12:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    min_support = 0.04 * H
    cl = [(float(np.average([c[0] for c in g], weights=[c[1] for c in g])), sum(c[1] for c in g)) for g in clusters]
    left = [c for c in cl if c[0] <= -MIN_LANE_SLOPE and c[1] >= min_support]
    right = [c for c in cl if c[0] >= MIN_LANE_SLOPE and c[1] >= min_support]
    return {"x0": x0, "y0": y0,
            "aL": max(left)[0] if left else np.nan,  # boundary nearest the camera on each side
            "aR": min(right)[0] if right else np.nan,
            # every painted line, including one straight ahead while straddling it during a lane change
            "lines": [(a, sup, _painted_fraction(mask, x0, y0, a)) for a, sup in cl if sup >= min_support and abs(a) < 6],
            "support": best_score}


def _painted_fraction(mask: np.ndarray, x0: float, y0: float, a: float) -> float:
    H, W = mask.shape
    rows = np.nonzero(mask.any(axis=1))[0]
    if not len(rows):
        return 0.0
    ys = np.arange(max(int(y0) + 15, rows.min()), rows.max() + 1)
    on = total = 0
    for y in ys:
        x = int(round(x0 + a * (y - y0)))
        if 0 <= x < W:
            total += 1
            on += bool(mask[y, max(0, x - 3):x + 4].any())
    return on / total if total >= 20 else float("nan")


def _nanmedian_filter(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    r = k // 2
    for i in range(len(x)):
        w = x[max(0, i - r):i + r + 1]
        w = w[~np.isnan(w)]
        if len(w) >= max(2, r // 2):
            out[i] = np.median(w)
    return out


def _fill(x: np.ndarray, max_gap: int) -> np.ndarray:
    """Linear-interpolate NaN gaps up to max_gap samples; extend edges by nearest up to max_gap."""
    x = x.copy()
    idx = np.arange(len(x))
    ok = ~np.isnan(x)
    if ok.sum() < 2:
        return x
    filled = np.interp(idx, idx[ok], x[ok])
    nearest_dist = np.abs(idx[:, None] - idx[ok][None, :]).min(axis=1)
    x[nearest_dist <= max_gap] = filled[nearest_dist <= max_gap]
    return x


FOOTPRINT_M = {"car": (1.8, 4.5), "truck": (2.6, 12.0), "bus": (2.6, 12.0), "motorcycle": (0.8, 2.2),
               "bicycle": (0.6, 1.8), "person": (0.6, 0.6)}


def resolve_overlaps(out_actors: dict[str, list[dict]], actors: list[dict], iterations: int = 4) -> list[dict]:
    """Make the top-down physically possible: two road users can't occupy the same patch of road.

    Where footprints overlap at a moment, push the pair apart just enough to touch, along whichever axis (along or
    across the road) costs least relative to their uncertainty, moving the less certain one more and keeping their
    order. That is the most likely layout consistent with physics. If the push needed exceeds 2 sigma, the two
    measurements genuinely contradict each other, and we say so instead of hiding it. Vehicles flagged as off the
    road (airborne) are exempt: they can pass over others.
    """
    cls = {a["id"]: a["cls"] for a in actors}
    by_t: dict[float, list[dict]] = {}
    for aid, rows in out_actors.items():
        for r in rows:
            if r.get("on_ground") is not False:
                r["_id"] = aid
                by_t.setdefault(r["t"], []).append(r)
    conflicts: dict[tuple[str, str], list[float]] = {}
    for t, rows in by_t.items():
        for _ in range(iterations):
            moved = False
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    A, B = rows[i], rows[j]
                    wa, la = FOOTPRINT_M.get(cls[A["_id"]], FOOTPRINT_M["car"])
                    wb, lb = FOOTPRINT_M.get(cls[B["_id"]], FOOTPRINT_M["car"])
                    ca, cb = A["s"] + la / 2, B["s"] + lb / 2  # s is the face nearest the camera
                    need_s = (la + lb) / 2 - abs(ca - cb)
                    need_d = (wa + wb) / 2 - abs(A["d"] - B["d"])
                    if need_s <= 0 or need_d <= 0:
                        continue
                    vs = A["s_sigma"] ** 2 + B["s_sigma"] ** 2 + 1e-6
                    vd = A["d_sigma"] ** 2 + B["d_sigma"] ** 2 + 1e-6
                    if need_s / np.sqrt(vs) <= need_d / np.sqrt(vd):
                        key, need, var, sign = "s", need_s, vs, (1 if ca >= cb else -1)
                    else:
                        key, need, var, sign = "d", need_d, vd, (1 if A["d"] >= B["d"] else -1)
                    if need > 2 * np.sqrt(var):
                        pair = tuple(sorted((A["_id"], B["_id"])))
                        conflicts.setdefault(pair, [])
                        if t not in conflicts[pair]:
                            conflicts[pair].append(t)
                    sa2 = A[f"{key}_sigma"] ** 2 + 1e-6
                    sb2 = B[f"{key}_sigma"] ** 2 + 1e-6
                    A[key] = round(A[key] + sign * need * sa2 / (sa2 + sb2), 2)
                    B[key] = round(B[key] - sign * need * sb2 / (sa2 + sb2), 2)
                    for R, sh in ((A, need * sa2 / (sa2 + sb2)), (B, need * sb2 / (sa2 + sb2))):
                        R["adjusted_m"] = round(R.get("adjusted_m", 0.0) + sh, 2)
                    moved = True
            if not moved:
                break
    for rows in by_t.values():
        for r in rows:
            r.pop("_id", None)
    notes = []
    for (a, b), ts in conflicts.items():
        if len(ts) >= 2:  # a single frame is within noise
            ts.sort()
            notes.append({"level": "warn", "code": "overlap", "actor": a, "other": b, "times": ts,
                          "message": f"{a} and {b} are measured on the same patch of road at {ts[0]:.1f}–{ts[-1]:.1f} s, "
                                     "which is physically impossible: at least one of their positions is wrong there. "
                                     "They are drawn just touching."})
    return notes


def remap_plates(plates: list[dict], actors: list[dict]) -> list[dict]:
    """Plates were attached to automatic track IDs; follow any user merges to the surviving ID."""
    alias = {m: a["id"] for a in actors for m in a.get("merged_from", [])}
    return [{**p, "actor": alias.get(p.get("actor"), p.get("actor"))} for p in plates]


def _log_mode(x: np.ndarray, half_width: float = 0.15) -> float:
    """Centre (in log space) of the densest +/-half_width window."""
    logs = np.log(x)
    centers = np.linspace(np.percentile(logs, 5), np.percentile(logs, 95), 200)
    counts = [(np.abs(logs - c) < half_width).sum() for c in centers]
    return float(centers[int(np.argmax(counts))])


# ----------------------------------------------------------------------------- lateral position

def _lateral_track(lines_at: list[list[tuple[float, float, float]]], h: float, lane_w: float, vfps: float,
                   t_video: np.ndarray) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Camera lateral position d(t) in a road frame whose lane centres sit at multiples of lane_w.

    A line at camera-relative offset X = h*a' sits at road position L = d + X, and lines lie on L = W/2 + kW, so each
    line gives d modulo W. A weighted circular mean over all lines (including the one straight ahead while straddling
    it) gives d mod W per frame; at video frame rates lateral motion is a few cm per frame, so unwrapping recovers the
    continuous position through lane changes. The starting lane is lane 0.
    """
    n = len(lines_at)
    theta = np.full(n, np.nan)
    for i, ls in enumerate(lines_at):
        if not ls:
            continue
        X = np.array([h * a for a, _, _ in ls])
        w = np.array([sup / (1 + abs(a)) for a, sup, _ in ls])  # far-side lines are less precise
        ph = 2 * np.pi * (lane_w / 2 - X) / lane_w
        for _ in range(2):  # drop lines off the lane grid (shoulder edges, the outer half of a double line)
            m = np.angle(np.sum(w * np.exp(1j * ph)))
            resid = np.abs(np.angle(np.exp(1j * (ph - m)))) * lane_w / (2 * np.pi)
            keep = resid < 0.6
            if keep.sum() == 0:
                break
            ph, w = ph[keep], w[keep]
        theta[i] = np.angle(np.sum(w * np.exp(1j * ph)))
    # Unwrap against the last accepted sample, gating on lateral speed: occluded or misdetected lines can shift the
    # phase abruptly, and accepting that would silently move the car a whole lane. A car moves sideways at most
    # ~2 m/s even in an aggressive lane change, so faster apparent motion is rejected; if the disagreement persists
    # for over 1.5 s we re-anchor on the nearest branch.
    unw = np.full(n, np.nan)
    last = None
    rejected_since = None
    for i in range(n):
        if np.isnan(theta[i]):
            continue
        if last is None:
            unw[i] = theta[i]
            last = i
            continue
        step = np.angle(np.exp(1j * (theta[i] - theta[last]))) * lane_w / (2 * np.pi)
        dt = (i - last) / vfps
        if abs(step) > 0.15 + 3.0 * dt:
            rejected_since = rejected_since if rejected_since is not None else i
            if (i - rejected_since) / vfps < 1.5:
                continue
        rejected_since = None
        unw[i] = unw[last] + step * 2 * np.pi / lane_w
        last = i
    d = _fill(_nanmedian_filter(unw * lane_w / (2 * np.pi), 9), int(vfps))

    # Lane changes: the lane index (nearest lane centre) changes and stays changed for >= 0.5 s.
    changes = []
    idx = np.where(np.isnan(d), np.nan, np.round(d / lane_w))
    hold = int(0.5 * vfps)
    cur = next((x for x in idx if not np.isnan(x)), None)
    for i in range(n):
        if cur is None or np.isnan(idx[i]) or idx[i] == cur:
            continue
        nxt = idx[i:i + hold]
        if np.all((nxt == idx[i]) | np.isnan(nxt)):
            boundary = (cur + idx[i]) / 2 * lane_w
            j = i
            while j > 0 and not np.isnan(d[j - 1]) and (d[j - 1] - boundary) * (d[i] - boundary) > 0:
                j -= 1
            # find the start of the move: when lateral speed first exceeded 0.3 m/s before the crossing
            q = max(1, int(vfps / 2))
            sign = 1 if idx[i] > cur else -1
            k = j
            while k - q >= 0 and not np.isnan(d[k - q]) and sign * (d[k] - d[k - q]) / (q / vfps) > 0.25 and j - k < 6 * vfps:
                k -= 1
            changes.append({"t": round(float(t_video[j]), 2), "t_start": round(float(t_video[k]), 2),
                            "direction": "right" if idx[i] > cur else "left",
                            "from_lane": int(cur), "to_lane": int(idx[i])})
            cur = idx[i]

    # Road lines actually observed, on the lane grid, in road coordinates, typed solid/dashed by painted fraction.
    seen_k: dict[int, list[float]] = {}
    valid = 0
    for i, ls in enumerate(lines_at):
        if np.isnan(d[i]) or not ls:
            continue
        valid += 1
        frame_k: dict[int, float] = {}
        for a, _, frac in ls:
            L = d[i] + h * a - lane_w / 2
            k = int(np.round(L / lane_w))
            if abs(L - k * lane_w) < 0.6:
                frame_k[k] = frac
        for k, frac in frame_k.items():
            seen_k.setdefault(k, []).append(frac)
    road_lines = []
    for k in sorted(seen_k):
        fr = [f for f in seen_k[k] if not np.isnan(f)]
        pct = 100 * len(seen_k[k]) / max(valid, 1)
        if pct < 15:
            continue
        painted = float(np.median(fr)) if fr else float("nan")
        road_lines.append({"d": round(lane_w / 2 + k * lane_w, 3), "seen_pct": round(pct, 1),
                           "painted": None if np.isnan(painted) else round(painted, 2),
                           "kind": "solid" if painted > 0.4 else "dashed"})  # dashed ~0.2, solid >0.5 even with occlusion
    return d, changes, road_lines


# ----------------------------------------------------------------------------- dash pattern helpers

def _sample_line(th: np.ndarray, thr: float, x0: float, y0: float, a: float, ys: np.ndarray) -> np.ndarray:
    H, W = th.shape
    out = np.zeros(len(ys), bool)
    for n, y in enumerate(ys):
        yi = int(round(y))
        if not (0 <= yi < H):
            continue
        xc = int(round(x0 + a * (y - y0)))
        lo, hi = max(0, xc - 3), min(W, xc + 4)
        if lo < hi:
            out[n] = th[yi, lo:hi].max() > thr
    return out


def _dash_runs(on: np.ndarray, ys: np.ndarray, merge_gap: int = 2) -> list[tuple[float, float]]:
    """Complete painted runs along a line as (y_far, y_near); runs split by tiny gaps are merged."""
    runs, start, last_on = [], None, -10
    for n, v in enumerate(list(on) + [False]):
        if v:
            if start is None:
                start = n
            elif n - last_on > merge_gap + 1:  # gap too big: close previous run and start a new one
                runs.append((start, last_on))
                start = n
            last_on = n
    if start is not None:
        runs.append((start, last_on))
    return [(float(ys[a]), float(ys[b])) for a, b in runs if b - a >= 2 and b < len(on) - 3]


def _dash_pairs_K(runs: list[tuple[float, float]], y0: float, period: float, duty: float) -> list[float]:
    """K estimates from consecutive dashes whose painted fraction of the cycle matches the marking standard.

    In u = 1/(y - y0) (proportional to depth), a dash spans u_far - u_near and a cycle spans u_far1 - u_far2; their
    ratio must be ~duty (3.05/12.19 = 0.25 in the US). Solid lines broken by occlusion or dashes split by noise fail it.
    """
    out = []
    for (f1, n1), (f2, _) in zip(runs, runs[1:]):
        u_f1, u_n1, u_f2 = 1 / (f1 - y0), 1 / (n1 - y0), 1 / (f2 - y0)
        cycle, dash = u_f1 - u_f2, u_f1 - u_n1
        if cycle > 0 and 0.5 * duty < dash / cycle < 1.8 * duty:
            out.append(period / cycle)
    return out


# ----------------------------------------------------------------------------- smoothing

def _rts(ts: np.ndarray, z: np.ndarray, r: np.ndarray, sigma_a: float, v0: float, v0_sigma: float):
    """Constant-velocity Kalman filter + RTS smoother. z/r may contain NaN (no measurement)."""
    n = len(ts)
    first = int(np.argmax(~np.isnan(z)))
    x = np.array([z[first], v0])
    P = np.diag([r[first] ** 2, v0_sigma ** 2])
    xs, Ps, xps, Pps, Fs = np.zeros((n, 2)), np.zeros((n, 2, 2)), np.zeros((n, 2)), np.zeros((n, 2, 2)), []
    gated = 0
    for k in range(n):
        dt = ts[k] - ts[k - 1] if k else 0.0
        F = np.array([[1, dt], [0, 1]])
        Q = sigma_a ** 2 * np.array([[dt ** 4 / 4, dt ** 3 / 2], [dt ** 3 / 2, dt ** 2]])
        if k:
            x, P = F @ x, F @ P @ F.T + Q
        Fs.append(F)
        xps[k], Pps[k] = x, P
        if not np.isnan(z[k]) and k > first and gated < 1 and \
                (z[k] - x[0]) ** 2 > monocular.GATE_SIGMA ** 2 * (P[0, 0] + r[k] ** 2):
            gated += 1  # a one-off jump no vehicle can make (detection briefly on another car): ignore it
        elif not np.isnan(z[k]):
            if gated and (z[k] - x[0]) ** 2 > monocular.GATE_SIGMA ** 2 * (P[0, 0] + r[k] ** 2):
                P = P + np.diag([r[k] ** 2, 25.0])  # persistent disagreement: the prediction is wrong, re-anchor
            gated = 0
            S = P[0, 0] + r[k] ** 2
            Kg = P[:, 0] / S
            x = x + Kg * (z[k] - x[0])
            P = P - np.outer(Kg, P[0, :])
        xs[k], Ps[k] = x, P
    for k in range(n - 2, -1, -1):
        F = Fs[k + 1]
        C = Ps[k] @ F.T @ np.linalg.inv(Pps[k + 1])
        xs[k] = xs[k] + C @ (xs[k + 1] - xps[k + 1])
        Ps[k] = Ps[k] + C @ (Ps[k + 1] - Pps[k + 1]) @ C.T
    return xs, Ps


# ----------------------------------------------------------------------------- stage

def run(clip: Clip, progress: Callable[[float, str], None]) -> dict:
    meta = clip.meta()
    lane_w = float(meta.get("lane_width_m", LANE_WIDTH_M))
    period = float(meta.get("dash_period_m", DASH_PERIOD_M))
    duty = float(meta.get("dash_length_m", DASH_LENGTH_M)) / period
    ing = clip.stage("ingest")
    Wpx, Hpx, vfps = ing["video"]["width"], ing["video"]["height"], ing["video"]["fps"]
    actors = clip.stage("track")["actors"]
    ocr = clip.stage("ocr") or {"present": False, "samples": []}
    roi = (int(0.40 * Hpx), int(0.96 * Hpx))
    quality: list[dict] = []

    def boxes_at(t: float) -> list[tuple[int, int, int, int]]:
        out = []
        for a in actors:
            s = min(a["samples"], key=lambda s: abs(s["t"] - t))
            if abs(s["t"] - t) <= 0.15:
                b = s["box"]
                out.append((int(b[0] * Wpx), int(b[1] * Hpx), int(b[2] * Wpx), int(b[3] * Hpx)))
        return out

    # ---- pass 1: lanes per video frame
    cap = cv2.VideoCapture(str(clip.video))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int(ing["video"]["duration"] * vfps)
    raw = {k: np.full(n_frames, np.nan) for k in ("x0", "y0", "aL", "aR")}
    lines_at: list[list[tuple[float, float]]] = [[] for _ in range(n_frames)]
    prev_vp = None
    for i in range(n_frames):
        ok, frame = cap.read()
        if not ok:
            n_frames = i
            break
        # Search only below the horizon once we know where it is: above it there is only clutter.
        roi_i = (int(prev_vp[1]) + 10, roi[1]) if prev_vp else roi
        res = _find_lanes(_line_mask(frame, boxes_at(i / vfps), roi_i), prev_vp)
        if res:
            for k in raw:
                raw[k][i] = res[k]
            lines_at[i] = res["lines"]
            prev_vp = (res["x0"], res["y0"])
        if i % 24 == 0:
            progress(0.5 * i / max(n_frames, 1), "finding lane lines")
    cap.release()
    raw = {k: v[:n_frames] for k, v in raw.items()}
    lines_at = lines_at[:n_frames]
    t_video = np.arange(n_frames) / vfps

    both = ~np.isnan(raw["aL"]) & ~np.isnan(raw["aR"])
    lane_pct = float(both.mean()) if n_frames else 0.0
    result: dict = {"lane_width_m": lane_w, "dash_period_m": period, "lane_frames_pct": round(100 * lane_pct, 1)}

    h = None
    if both.sum() >= max(12, 0.15 * n_frames):
        span = raw["aR"][both] - raw["aL"][both]
        span = span[np.abs(np.log(span) - _log_mode(span)) < 0.25]
        h = lane_w / float(np.median(span))
        h_iqr = [lane_w / float(np.percentile(span, 75)), lane_w / float(np.percentile(span, 25))]
        result["camera_height_m"] = round(h, 3)
        result["camera_height_iqr_m"] = [round(x, 3) for x in h_iqr]
        if not (0.8 <= h <= 3.0):
            quality.append({"level": "error", "code": "implausible_height",
                            "message": f"Lane geometry implies a camera height of {h:.2f} m, which is implausible; "
                                       "lane detection is probably wrong. Positions and speeds are not computed."})
            h = None
    else:
        quality.append({"level": "error", "code": "no_lanes",
                        "message": f"Both ego-lane boundaries were found in only {100 * lane_pct:.0f}% of frames "
                                   "(markings hidden, worn, or absent). Distances and speeds of other road users "
                                   "are not computed."})

    y0s = _fill(_nanmedian_filter(raw["y0"], 9), int(vfps))
    x0s = _fill(_nanmedian_filter(raw["x0"], 9), int(vfps))
    lane_changes: list[dict] = []
    road_lines: list[dict] = []
    if h:
        d_cam, lane_changes, road_lines = _lateral_track(lines_at, h, lane_w, vfps, t_video)
    else:
        d_cam = np.full(n_frames, np.nan)
    result["lane_changes"] = lane_changes

    # ---- pass 2: dash far-ends (for K) and dash-pattern profiles in Z (for ego speed)
    K = None
    flow: list[tuple[float, float]] = []
    if h:
        progress(0.55, "measuring dash spacing")
        cap = cv2.VideoCapture(str(clip.video))
        Ks = {"L": [], "R": []}
        for i in range(n_frames):
            ok, frame = cap.read()
            if not ok:
                break
            if not both[i] or np.isnan(y0s[i]):
                continue
            th = _tophat(frame)
            thr = max(15.0, float(np.percentile(th[roi[0]:roi[1]], 99.0)) * 0.5)
            for b in boxes_at(i / vfps):
                th[max(0, b[1] - 4):b[3] + 4, max(0, b[0] - 4):b[2] + 4] = 0
            ys = np.arange(int(y0s[i]) + 8, roi[1])
            for side in ("L", "R"):
                on = _sample_line(th, thr, x0s[i], y0s[i], raw["a" + side][i], ys)
                Ks[side] += _dash_pairs_K(_dash_runs(on, ys), y0s[i], period, duty)
            if i % 24 == 0:
                progress(0.55 + 0.25 * i / max(n_frames, 1), "measuring dash spacing")
        cap.release()

        def spread(v: list[float]) -> float:
            return float(np.subtract(*np.percentile(v, [75, 25])) / np.median(v)) if len(v) >= 10 else 9.0

        pooled = np.array(Ks["L"] + Ks["R"])
        side = "L" if len(Ks["L"]) >= len(Ks["R"]) else "R"
        mode_K, mode_frac, in_mode = None, 0.0, np.array([])
        if len(pooled) >= 10:
            logs = np.log(pooled)
            # densest +/-15% window in log space: the true scale forms a mode, mismatched pairs scatter
            centers = np.linspace(np.percentile(logs, 5), np.percentile(logs, 95), 200)
            counts = [(np.abs(logs - c) < 0.15).sum() for c in centers]
            c = centers[int(np.argmax(counts))]
            in_mode = pooled[np.abs(logs - c) < 0.15]
            mode_frac = len(in_mode) / len(pooled)
            mode_K = float(np.median(in_mode))
        result["dash_debug"] = {"pairs_left": len(Ks["L"]), "pairs_right": len(Ks["R"]),
                                "mode_fraction": round(mode_frac, 3), "median_all": round(float(np.median(pooled)), 1) if len(pooled) else None}
        if mode_K and len(in_mode) >= 10 and mode_frac >= 0.3:
            K = mode_K
            mad = float(np.median(np.abs(in_mode - K))) * 1.4826
            k_rel = max(0.03, mad / K / np.sqrt(len(in_mode) / 10))  # pairs within a frame are correlated
            f_px = K / h
            hfov = float(np.degrees(2 * np.arctan(Wpx / 2 / f_px)))
            result.update({"K": round(K, 1), "K_rel_sigma": round(k_rel, 3), "focal_px": round(f_px, 1),
                           "hfov_deg": round(hfov, 1), "dash_pairs": int(len(in_mode))})
            if not (25 <= hfov <= 160):
                quality.append({"level": "error", "code": "implausible_fov",
                                "message": f"Dash spacing implies a {hfov:.0f}° field of view, which is implausible."})
                K = None
        else:
            quality.append({"level": "error", "code": "no_dashes",
                            "message": "No regular dashed lane line found, so there is no depth scale. Distances "
                                       "and speeds of other road users are not computed."})

    # Lane-based lateral position is only trustworthy when the lines formed a real lane grid with a dash scale.
    # Without that (parking lots, unmarked roads), stall lines and cracks fit "lanes" and would invent lane changes.
    if not K:
        if lane_changes or road_lines:
            quality.append({"level": "info", "code": "lanes_unverified",
                            "message": "Line-like markings were found but don't form a verified lane pattern, so no "
                                       "lane positions or lane changes are reported."})
        lane_changes, road_lines = [], []
        d_cam = np.full(n_frames, np.nan)
        result["lane_changes"] = []
        result.pop("camera_height_m", None)
        result.pop("camera_height_iqr_m", None)

    # ---- ego speed
    # Sources, best first: the dashcam's own speed overlay; lane-dash flow (needs a verified lane scale); background
    # motion, which can't measure speed but reliably shows when the camera is standing still (0 km/h).
    motion_samples = (clip.stage("motion") or {}).get("samples", [])
    m_t = np.array([m["t"] for m in motion_samples]) if motion_samples else np.array([])

    def motion_state(t: float) -> str:
        if not len(m_t):
            return "unknown"
        return motion_samples[int(np.argmin(np.abs(m_t - t)))]["state"]

    stationary_t = np.array([m["t"] for m in motion_samples if m["state"] == "stationary"])
    ego_src, ego_t, ego_v, ego_sig = "none", np.array([]), np.array([]), np.array([])
    ocr_samples = [s for s in ocr.get("samples", []) if not s.get("suspicious")]
    flow_rows: list[tuple[float, float, float]] = []
    if ocr.get("present") and len(ocr_samples) >= 2:
        ego_src = "overlay"
        ego_t = np.array([s["t"] for s in ocr_samples])
        ego_v = np.array([s["speed_mps"] for s in ocr_samples])
        ego_sig = np.maximum(0.3, 0.02 * ego_v)
    else:
        if K and h:
            progress(0.8, "estimating ego speed from lane flow")
            solid_ds = [l["d"] for l in road_lines if l["kind"] == "solid"]
            flow = _lane_flow(clip, K, x0s, y0s, lines_at, vfps, period, roi, boxes_at, d_cam, h, solid_ds)
            # Background motion vetoes contradictions: ~0 m/s while the scene clearly moves (a solid line or static
            # clutter was matched), or a large speed while the background is perfectly still.
            kept = [f for f in flow if not ((motion_state(f[0]) == "moving" and f[1] < 1.5)
                                            or (motion_state(f[0]) == "stationary" and f[1] > 1.5))]
            result["ego_flow"] = {"samples": len(flow), "vetoed_by_motion": len(flow) - len(kept)}
            if len(kept) >= 10:
                ft = np.array([f[0] for f in kept])
                fv = np.array([f[1] for f in kept])
                for b0 in np.arange(0, t_video[-1] + 0.5, 0.5):
                    sel = (ft >= b0) & (ft < b0 + 0.5)
                    if sel.sum() >= 3:
                        med = float(np.median(fv[sel]))
                        mad = float(np.median(np.abs(fv[sel] - med))) * 1.4826
                        flow_rows.append((b0 + 0.25, med, max(0.4, mad / np.sqrt(sel.sum())) + med * result["K_rel_sigma"]))
        still_rows = [(float(t), 0.0, 0.2) for t in stationary_t]
        if len(flow_rows) >= 3:
            ego_src = "lane_flow"
            rows = sorted(flow_rows + still_rows)
            ego_t = np.arange(0, t_video[-1] + 1e-6, 0.25)
            ego_v, ego_sig, n_out = _smooth_speed(np.array([r[0] for r in rows]), np.array([r[1] for r in rows]),
                                                  np.array([r[2] for r in rows]), ego_t)
            ego_sig = ego_sig + ego_v * result["K_rel_sigma"]  # scale uncertainty applies to all of it
            result["ego_flow"].update({"bins": len(flow_rows), "stationary_samples": len(still_rows), "outlier_bins": n_out})
        elif len(still_rows) >= 4:
            # No way to measure speed here, but we know when the camera is standing still. Elsewhere: unknown.
            ego_src = "background_motion"
            ego_t = np.array([f["t"] for f in ing["frames"]])
            still = np.isin(ego_t, stationary_t)
            ego_v = np.where(still, 0.0, np.nan)
            ego_sig = np.where(still, 0.2, np.nan)
    if ego_src == "none":
        quality.append({"level": "warn", "code": "no_ego_speed",
                        "message": "No speed overlay and no usable lane-flow signal: the recording vehicle's speed "
                                   "is unknown, so only relative motion is shown."})
    elif ego_src == "background_motion":
        quality.append({"level": "info", "code": "ego_stationary_only",
                        "message": "The recording vehicle's speed can't be measured in this clip (no overlay, no lane "
                                   "markings). Background motion shows when it was standing still; at other times its "
                                   "speed is unknown."})

    def ego_at(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if ego_src == "none":
            return np.full_like(t, np.nan), np.full_like(t, np.nan)
        return np.interp(t, ego_t, ego_v), np.interp(t, ego_t, ego_sig)

    # Ego path in the road frame (s by integrating speed on the video timeline).
    ev, es = ego_at(t_video)
    # Unknown speed contributes no distance (positions are then relative to the camera, which is what we report).
    evz = np.nan_to_num(ev)
    s_ego_video = np.concatenate([[0.0], np.cumsum((evz[1:] + evz[:-1]) / 2 * np.diff(t_video))]) if ego_src != "none" else np.zeros(n_frames)

    def at(series: np.ndarray, t: float) -> float:
        return float(np.interp(t, t_video, series))

    t_grid = np.array([f["t"] for f in ing["frames"]])
    ev_g, es_g = ego_at(t_grid)
    ego_samples = [{"t": float(t), "s": round(at(s_ego_video, t), 2), "d": None if np.isnan(at(d_cam, t)) else round(at(d_cam, t), 2),
                    "v": None if np.isnan(v) else round(float(v), 2), "v_sigma": None if np.isnan(sg) else round(float(sg), 2)}
                   for t, v, sg in zip(t_grid, ev_g, es_g)]

    # ---- actors
    out_actors: dict[str, list[dict]] = {}
    if K and h:
        progress(0.9, "projecting actors")
        k_rel = result["K_rel_sigma"]
        f_px = K / h
        frame_boxes = monocular.boxes_by_frame(actors)
        plates_all = remap_plates((clip.stage("plates") or {}).get("plates", []), actors)
        plates_by: dict = {}
        for p in plates_all:
            if p.get("actor"):
                plates_by.setdefault((p["actor"], p["i"]), []).append(p["box"])
        for a in actors:
            ts, zs, zr, xs, xr, on_ground = [], [], [], [], [], []
            large = a["cls"] in ("truck", "bus")
            # Pass 1: cues per detection. Road contact: Z = K / (y_bottom - y0); its error grows with distance and
            # HORIZON_SIGMA_PX covers horizon/pitch error and gentle slopes, which dominate far away.
            cues = []
            for s in a["samples"]:
                t, b = s["t"], s["box"]
                y0, x0 = at(y0s, t), at(x0s, t)
                if s["interp"] or np.isnan(y0):
                    cues.append(None)
                    continue
                yb, xb = b[3] * Hpx, (b[0] + b[2]) / 2 * Wpx
                bh = (b[3] - b[1]) * Hpx
                size_est = monocular.size_cues(a, s, plates_by.get((a["id"], s["i"]), []), f_px, Wpx, Hpx,
                                               occluded=monocular.occluded_by_nearer(a["id"], s["box"], frame_boxes.get(s["i"], [])))
                size = monocular.fuse(size_est) if size_est else None
                ground = None
                if b[3] < 0.97 and yb - y0 > 6:
                    Zg = K / (yb - y0)
                    sg = float(np.hypot(2 + 0.02 * bh, HORIZON_SIGMA_PX) / (yb - y0)) + (2.0 / Zg if large else 0.0)
                    ground = (float(np.log(Zg)), sg, xb, "ground")
                # log(road-contact distance / size distance) and its spread; None if not comparable
                ratio = None
                if size is not None and ground is not None:
                    ratio = (ground[0] - float(np.log(size[0])), float(np.hypot(ground[1], size[1])))
                near_by_size = size is not None and size[0] < 40
                cues.append((size_est, ground, ratio, y0, x0, yb, near_by_size))
            # Size priors and horizon bias make road-contact and size disagree by a roughly constant *ratio* per
            # vehicle (a pickup is ~20% bigger than a generic car). Lift-off is a sudden, large jump in that ratio.
            rs = [c[2][0] for c in cues if c and c[2] is not None]
            typical = float(np.median(rs)) if len(rs) >= 4 else 0.0
            # Pass 2: decide road contact, fuse, place.
            for s, c in zip(a["samples"], cues):
                t, b = s["t"], s["box"]
                ts.append(t)
                if c is None:
                    zs.append(np.nan); zr.append(np.nan); xs.append(np.nan); xr.append(np.nan); on_ground.append(None)
                    continue
                size_est, ground, ratio, y0, x0, yb, near_by_size = c
                grounded = None
                if near_by_size and yb - y0 <= 6:
                    grounded = False  # bottom at/above the horizon yet close by size: certainly not on the road
                elif ratio is not None:
                    jump = ratio[0] - typical
                    grounded = not (jump > OFF_GROUND_LOG and jump > 3 * ratio[1])
                est = list(size_est) + ([ground] if ground and grounded is not False else [])
                if not est:
                    zs.append(np.nan); zr.append(np.nan); xs.append(np.nan); xr.append(np.nan); on_ground.append(grounded)
                    continue
                Z, slz, xc, _ = monocular.fuse(est)
                if Z > Z_MAX:
                    zs.append(np.nan); zr.append(np.nan); xs.append(np.nan); xr.append(np.nan); on_ground.append(grounded)
                    continue
                bw = (b[2] - b[0]) * Wpx
                X = (xc - x0) * Z / f_px
                sx = (2 + 0.1 * bw) * (4 if (b[0] < 0.005 or b[2] > 0.995) else 1)
                zs.append(at(s_ego_video, t) + Z); zr.append(Z * slz)
                xs.append(at(d_cam, t) + X if not np.isnan(at(d_cam, t)) else X)
                xr.append(float(np.hypot(sx * Z / f_px, abs(X) * slz)))
                on_ground.append(grounded)
            ts, zs, zr, xs, xr = map(np.array, (ts, zs, zr, xs, xr))
            if (~np.isnan(zs)).sum() < 3:
                continue
            v0 = float(np.nanmedian(ev_g)) if ego_src != "none" else 0.0
            S, PS = monocular.segmented(ts, zs, zr, lambda t, z, r: _rts(t, z, r, 4.0, v0, 15.0))
            D, PD = monocular.segmented(ts, xs, xr, lambda t, z, r: _rts(t, z, r, 1.5, 0.0, 3.0))
            evs, ess = ego_at(ts)
            rows = []
            for k, t in enumerate(ts):
                if np.isnan(S[k, 0]) or np.isnan(D[k, 0]):
                    continue  # piece of the track too short to place
                vs, vd = S[k, 1], D[k, 1]
                v = float(np.hypot(vs, vd))
                rel = vs - (evs[k] if ego_src == "overlay" else 0.0)
                sig = float(np.sqrt(PS[k, 1, 1] + (0 if np.isnan(ess[k]) else ess[k] ** 2) + (k_rel * rel) ** 2))
                measured = not np.isnan(zs[k])
                rows.append({"t": round(float(t), 3), "s": round(float(S[k, 0]), 2), "d": round(float(D[k, 0]), 2),
                             "s_sigma": round(float(np.sqrt(PS[k, 0, 0])), 2), "d_sigma": round(float(np.sqrt(PD[k, 0, 0])), 2),
                             "v": round(v, 2) if ego_src != "none" else None,
                             "v_lo": round(max(0.0, v - 1.96 * sig), 2) if ego_src != "none" else None,
                             "v_hi": round(v + 1.96 * sig, 2) if ego_src != "none" else None,
                             "v_rel": round(float(vs - (evs[k] if ego_src != "none" else 0.0)), 2) if ego_src != "none" else round(float(vs), 2),
                             "heading_deg": round(float(np.degrees(np.arctan2(vd, vs))), 1) if v > 2 else None,
                             "measured": measured, "on_ground": on_ground[k],
                             "dist_m": round(float(zs[k] - at(s_ego_video, t)), 1) if measured else None})
            out_actors[a["id"]] = rows
            if large:
                quality.append({"level": "info", "code": "large_vehicle", "actor": a["id"],
                                "message": f"{a['id']} is a {a['cls']}: its box bottom may not be where it touches "
                                           "the road, so its position has an extra ±2 m allowance."})
            near = [r["dist_m"] for r in rows if r["dist_m"] is not None]
            if near and min(near) > 50:
                quality.append({"level": "warn", "code": "distant", "actor": a["id"],
                                "message": f"{a['id']} never comes closer than {min(near):.0f} m; its speed range is wide."})

    mode = "lanes" if (K and h) else "monocular"
    if mode == "monocular":
        progress(0.9, "ranging from known object sizes")
        plates = remap_plates((clip.stage("plates") or {}).get("plates", []), actors)

        def ego_speed_at(t: float) -> tuple[float | None, float | None]:
            if ego_src == "none":
                return None, None
            v, sg = ego_at(np.array([t]))
            return (None if np.isnan(v[0]) else float(v[0])), (None if np.isnan(sg[0]) else float(sg[0]))

        out_actors, mono_cal, mono_q = monocular.range_actors(actors, plates, Wpx, Hpx, meta, ego_speed_at)
        result.update(mono_cal)
        quality.extend(mono_q)
        status = "partial" if out_actors else "insufficient"
    else:
        status = "ok" if ego_src != "none" else "partial"
        quality.append({"level": "info", "code": "assumptions",
                        "message": f"Assumes a flat road, lane width {lane_w} m and dash period {period} m"
                                   f"{' (US freeway standard)' if (lane_w, period) == (LANE_WIDTH_M, DASH_PERIOD_M) else ' (set for this clip)'}. "
                                   "Positions are along/across the road, not GPS."})
    result["mode"] = mode
    quality.extend(resolve_overlaps(out_actors, actors))
    if mode == "monocular":  # lane-mode failures are no longer the last word: say what we fell back to
        for q in quality:
            if q["code"] in ("no_lanes", "no_dashes", "implausible_height"):
                q["level"] = "info"
                for tail in (" Distances and speeds of other road users are not computed.",
                             " Positions and speeds are not computed."):
                    q["message"] = q["message"].replace(tail, " Using known object sizes instead.")
    # Per analysis frame lane overlay for the UI (how the geometry was derived).
    lanes_ui = [{"t": float(t), "x0": None if np.isnan(at(x0s, t)) else round(at(x0s, t) / Wpx, 4),
                 "y0": None if np.isnan(at(y0s, t)) else round(at(y0s, t) / Hpx, 4),
                 "aL": _nearest(raw["aL"], t, vfps), "aR": _nearest(raw["aR"], t, vfps)} for t in t_grid]
    n_actors = len(out_actors)
    return {"status": status, "calibration": result, "ego": {"source": ego_src, "samples": ego_samples},
            "actors": out_actors, "lanes": lanes_ui, "road_lines": road_lines, "quality": quality,
            "summary": f"{status}: {n_actors} actors positioned, ego speed from {ego_src}"}


def _nearest(series: np.ndarray, t: float, vfps: float) -> float | None:
    i = int(round(t * vfps))
    for d in range(0, int(vfps // 4) + 1):
        for j in (i - d, i + d):
            if 0 <= j < len(series) and not np.isnan(series[j]):
                return round(float(series[j]), 4)
    return None


def _lane_flow(clip, K, x0s, y0s, lines_at, vfps, period, roi, boxes_at, d_cam, h, solid_ds,
               lag: int = 2) -> list[tuple[float, float, float]]:
    """Ego speed from the dash pattern's shift toward the camera between frames `lag` apart, measured in metres.

    Uses every dashed-looking line in the frame, including the one directly ahead while straddling it in a lane
    change. Returns (t, speed m/s, correlation).
    """
    zgrid = np.arange(6.0, 40.0, 0.05)
    cap = cv2.VideoCapture(str(clip.video))
    profiles: dict[int, list[tuple[float, np.ndarray]]] = {}
    out = []
    shifts = np.arange(-0.5, period / 2 - 0.2, 0.05)
    prev_gray = None
    for i in range(len(y0s)):
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.int16)
        repeated = prev_gray is not None and float(np.abs(gray - prev_gray).mean()) < 0.3
        prev_gray = gray
        if repeated:
            continue  # a repeated frame would read as zero shift
        # Lines the whole clip classifies as solid don't move along themselves and would vote 0 m/s.
        dashed = [a for a, _, frac in lines_at[i] if not np.isnan(frac) and 0.08 < frac < 0.5
                  and not any(abs(d_cam[i] + h * a - sd) < 0.6 for sd in solid_ds)]
        if not dashed or np.isnan(y0s[i]):
            continue
        th = _tophat(frame)
        thr = max(15.0, float(np.percentile(th[roi[0]:roi[1]], 99.0)) * 0.5)
        for b in boxes_at(i / vfps):
            th[max(0, b[1] - 4):b[3] + 4, max(0, b[0] - 4):b[2] + 4] = 0
        ys = y0s[i] + K / zgrid
        inside = ys < roi[1]
        profiles[i] = [(a, np.where(inside, _sample_line(th, thr, x0s[i], y0s[i], a, ys).astype(float), np.nan))
                       for a in dashed]
        j = i - lag
        for old in [k for k in profiles if k < j]:
            del profiles[old]
        if j not in profiles:
            continue
        cands = []
        for a_new, p_new in profiles[i]:
            match = min(profiles[j], key=lambda q: abs(q[0] - a_new))
            if abs(match[0] - a_new) > 0.15:
                continue
            p_old = match[1]
            on_frac = np.nanmean(p_new)
            if not (0.08 < on_frac < 0.6) or not _looks_dashed(p_new, zgrid, period):
                continue  # solid lines (even broken up by masked vehicles) don't move and would vote for 0 m/s
            best, best_c = None, -1.0
            for sft in shifts:
                # ground features move toward the camera: p_new(z) ~ p_old(z + v*dt)
                shifted = np.interp(zgrid + sft, zgrid, p_old, left=np.nan, right=np.nan)
                m = ~np.isnan(shifted) & ~np.isnan(p_new)
                if m.sum() < 100:
                    continue
                x, y = p_new[m] - p_new[m].mean(), shifted[m] - shifted[m].mean()
                den = np.sqrt((x * x).sum() * (y * y).sum())
                if den == 0:
                    continue
                c = float((x * y).sum() / den)
                if c > best_c:
                    best, best_c = sft, c
            if best is not None and best_c > 0.5:
                cands.append((best_c, best))
        if cands:
            best_c, best = max(cands)
            out.append(((i - lag / 2) / vfps, best / (lag / vfps), best_c))
    cap.release()
    return out


def _looks_dashed(profile: np.ndarray, zgrid: np.ndarray, period: float) -> bool:
    """At least two painted runs, all of dash-like length (well under the gap), along a profile sampled in metres."""
    on = np.nan_to_num(profile) > 0.5
    runs, start = [], None
    for k, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = k
        elif not v and start is not None:
            runs.append(zgrid[k - 1] - zgrid[start])
            start = None
    return len(runs) >= 2 and max(runs) < 0.5 * period


def _smooth_speed(ts: np.ndarray, v: np.ndarray, sig: np.ndarray, t_out: np.ndarray, sigma_a: float = 4.0):
    """1-D random-walk Kalman + RTS smoother on speed, with outlier rejection against the smoothed curve.

    sigma_a (m/s^2) allows hard braking while rejecting jumps no car can make. Gaps widen the output sigma.
    """
    keep = np.ones(len(ts), bool)
    for _ in range(3):
        tk, vk, sk = ts[keep], v[keep], sig[keep]
        grid = np.union1d(tk, t_out)
        z = np.full(len(grid), np.nan)
        r = np.full(len(grid), np.nan)
        idx = np.searchsorted(grid, tk)
        z[idx], r[idx] = vk, sk
        n = len(grid)
        xs, Ps, xp, Pp = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
        x, P = float(np.median(vk)), 20.0 ** 2
        for k in range(n):
            if k:
                dt = grid[k] - grid[k - 1]
                P = P + (sigma_a * dt) ** 2
            xp[k], Pp[k] = x, P
            if not np.isnan(z[k]):
                g = P / (P + r[k] ** 2)
                x, P = x + g * (z[k] - x), (1 - g) * P
            xs[k], Ps[k] = x, P
        for k in range(n - 2, -1, -1):
            c = Ps[k] / Pp[k + 1]
            xs[k] = xs[k] + c * (xs[k + 1] - xp[k + 1])
            Ps[k] = Ps[k] + c * c * (Ps[k + 1] - Pp[k + 1])
        fit = np.interp(ts, grid, xs)
        new_keep = np.abs(v - fit) < 3 * np.sqrt(sig ** 2 + np.interp(ts, grid, Ps))
        if (new_keep == keep).all():
            break
        keep = new_keep
    return np.interp(t_out, grid, xs), np.sqrt(np.interp(t_out, grid, Ps)), int((~keep).sum())
