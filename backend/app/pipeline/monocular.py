"""Distances from known object sizes when there are no lane markings to calibrate the road (parking lots, side
streets, close-range incidents).

    distance Z = f * real_size / size_in_pixels,   lateral X = (x - cx) * Z / f,   f from the camera field of view

Size cues, best first: a licence plate (standard 30.5 cm wide in the US/Canada), then the vehicle's width (typical
values by class), then a person's height. Truncated boxes (touching the frame edge) are never used for size.

The field of view is not observable from a single camera without calibration, so f comes from a stated prior
(per-clip `hfov_deg` in meta.json, else 70°) with a stated relative uncertainty. That uncertainty scales every distance
and speed together; time-to-contact (Z / closing speed) does not depend on it at all, so it is the most trustworthy
number in this mode.
"""
from typing import Callable

import numpy as np

DEFAULT_HFOV_DEG = 70.0
DEFAULT_HFOV_REL_SIGMA = 0.2  # relative 1-sigma on f; roughly a 55-90° field of view at 95%
PLATE_WIDTH_M = 0.305
WIDTH_PRIOR_M = {"car": (1.8, 0.12), "truck": (2.5, 0.1), "bus": (2.55, 0.05), "motorcycle": (0.8, 0.15),
                 "bicycle": (0.6, 0.1)}
# Height doesn't depend on viewing angle, so it works for vehicles seen side-on (where box width is their length).
HEIGHT_PRIOR_M = {"car": (1.55, 0.2), "truck": (3.5, 0.5), "bus": (3.2, 0.2), "motorcycle": (1.3, 0.2),
                  "bicycle": (1.7, 0.15)}
# Box width/height at most this when seen from behind or in front; wider boxes are side-on and width means length.
MAX_END_ON_ASPECT = {"car": 1.9, "truck": 1.1, "bus": 1.1, "motorcycle": 0.8, "bicycle": 0.8}
IN_PATH_M = 1.8  # time-to-contact is only meaningful for objects roughly in the camera's path
PERSON_HEIGHT_M = (1.7, 0.1)
EDGE = 0.01


def _touches(box: list[float]) -> dict[str, bool]:
    return {"l": box[0] < EDGE, "r": box[2] > 1 - EDGE, "t": box[1] < EDGE, "b": box[3] > 1 - EDGE}


def _rts_1d_pos_vel(ts: np.ndarray, z: np.ndarray, r: np.ndarray, sigma_a: float):
    """Constant-velocity Kalman + RTS smoother; z/r may contain NaN. Returns (states [n,2], covariances [n,2,2])."""
    n = len(ts)
    first = int(np.argmax(~np.isnan(z)))
    x = np.array([z[first], 0.0])
    P = np.diag([r[first] ** 2, 4.0 ** 2])
    xs, Ps, xp, Pp, Fs = np.zeros((n, 2)), np.zeros((n, 2, 2)), np.zeros((n, 2)), np.zeros((n, 2, 2)), []
    for k in range(n):
        dt = ts[k] - ts[k - 1] if k else 0.0
        F = np.array([[1, dt], [0, 1]])
        Q = sigma_a ** 2 * np.array([[dt ** 4 / 4, dt ** 3 / 2], [dt ** 3 / 2, dt ** 2]])
        if k:
            x, P = F @ x, F @ P @ F.T + Q
        Fs.append(F)
        xp[k], Pp[k] = x, P
        if not np.isnan(z[k]):
            S = P[0, 0] + r[k] ** 2
            g = P[:, 0] / S
            x = x + g * (z[k] - x[0])
            P = P - np.outer(g, P[0, :])
        xs[k], Ps[k] = x, P
    for k in range(n - 2, -1, -1):
        C = Ps[k] @ Fs[k + 1].T @ np.linalg.inv(Pp[k + 1])
        xs[k] = xs[k] + C @ (xs[k + 1] - xp[k + 1])
        Ps[k] = Ps[k] + C @ (Ps[k + 1] - Pp[k + 1]) @ C.T
    return xs, Ps


def range_actors(actors: list[dict], plates: list[dict], Wpx: int, Hpx: int, meta: dict,
                 ego_speed_at: Callable[[float], tuple[float, float]]) -> tuple[dict, dict, list[dict]]:
    hfov = float(meta.get("hfov_deg", DEFAULT_HFOV_DEG))
    f_rel = float(meta.get("hfov_rel_sigma", DEFAULT_HFOV_REL_SIGMA))
    plate_w = float(meta.get("plate_width_m", PLATE_WIDTH_M))
    f = (Wpx / 2) / np.tan(np.radians(hfov / 2))
    cx = Wpx / 2
    plates_by = {}
    for p in plates:
        if p.get("actor"):
            plates_by.setdefault((p["actor"], p["i"]), []).append(p["box"])

    out: dict[str, list[dict]] = {}
    cue_counts = {"plate": 0, "width": 0, "height": 0}
    quality: list[dict] = []
    for a in actors:
        ts, zs, zr, xs, xr, cues = [], [], [], [], [], []
        for s in a["samples"]:
            box = s["box"]
            ts.append(s["t"])
            est = []  # (log Z, sigma of log Z, x_centre_px, cue)
            if not s["interp"]:
                for pb in plates_by.get((a["id"], s["i"]), []):
                    w = (pb[2] - pb[0]) * Wpx
                    if w >= 12 and not any(_touches(pb).values()):
                        # +-2 px box error and ~5% for viewing angle / box looseness
                        est.append((np.log(f * plate_w / w), float(np.hypot(2 / w, 0.05)), (pb[0] + pb[2]) / 2 * Wpx, "plate"))
                tch = _touches(box)
                w = (box[2] - box[0]) * Wpx
                h = (box[3] - box[1]) * Hpx
                cls = a["cls"] if a["cls"] in WIDTH_PRIOR_M else "car"
                end_on = h > 0 and w / h <= MAX_END_ON_ASPECT[cls]
                if a["group"] != "person" and not (tch["l"] or tch["r"]) and w >= 10 and end_on:
                    W, sW = WIDTH_PRIOR_M[cls]
                    est.append((np.log(f * W / w), float(np.hypot(3 / w, sW / W)), (box[0] + box[2]) / 2 * Wpx, "width"))
                if a["group"] != "person" and not (tch["t"] or tch["b"]) and h >= 10:
                    Hm, sH = HEIGHT_PRIOR_M[cls]
                    est.append((np.log(f * Hm / h), float(np.hypot(3 / h, sH / Hm)), (box[0] + box[2]) / 2 * Wpx, "height"))
                if a["group"] == "person" and not (tch["t"] or tch["b"]) and h >= 15:
                    Hm, sH = PERSON_HEIGHT_M
                    est.append((np.log(f * Hm / h), float(np.hypot(3 / h, sH / Hm)), (box[0] + box[2]) / 2 * Wpx, "height"))
            if not est:
                zs.append(np.nan); zr.append(np.nan); xs.append(np.nan); xr.append(np.nan); cues.append(None)
                continue
            wts = np.array([1 / e[1] ** 2 for e in est])
            lz = float(np.sum(wts * np.array([e[0] for e in est])) / wts.sum())
            slz = float(1 / np.sqrt(wts.sum()))
            Z = float(np.exp(lz))
            xc = float(np.sum(wts * np.array([e[2] for e in est])) / wts.sum())
            X = (xc - cx) * Z / f
            zs.append(Z); zr.append(Z * slz)
            xs.append(X); xr.append(float(np.hypot(abs(X) * slz, 3 * Z / f)))
            best = min(est, key=lambda e: e[1])[3]
            cues.append(best)
            cue_counts[best] += 1
        ts, zs, zr, xs, xr = map(np.array, (ts, zs, zr, xs, xr))
        if (~np.isnan(zs)).sum() < 3:
            continue
        S, PS = _rts_1d_pos_vel(ts, zs, zr, 3.0)  # low-speed manoeuvring: modest accelerations
        D, PD = _rts_1d_pos_vel(ts, xs, xr, 1.5)
        rows = []
        for k, t in enumerate(ts):
            Z, vz = float(S[k, 0]), float(S[k, 1])
            X, vx = float(D[k, 0]), float(D[k, 1])
            ego_v, ego_s = ego_speed_at(float(t))
            # f scales distance and speed together; KF covariance holds the measurement noise
            sZ = float(np.hypot(np.sqrt(PS[k, 0, 0]), f_rel * Z))
            svz = float(np.hypot(np.sqrt(PS[k, 1, 1]), f_rel * abs(vz)))
            closing = -vz
            ttc = Z / closing if closing > 0.1 and Z > 0 and abs(X) <= IN_PATH_M else None
            # TTC = Z / (-dZ/dt) is free of the f scale; its spread comes from the measurement noise only
            ttc_sig = None
            if ttc is not None:
                rel = np.hypot(np.sqrt(PS[k, 0, 0]) / Z, np.sqrt(PS[k, 1, 1]) / closing)
                ttc_sig = float(ttc * rel)
            # Absolute speed needs the camera's own speed: 0 when it is standing still, else overlay/lane-flow if known.
            # (Along the camera axis: v_abs = ego + dZ/dt; straight-line approximation, fine at these ranges.)
            v = None
            if ego_v is not None and not np.isnan(ego_v):
                v = float(np.hypot(ego_v + vz, vx))
                svz = float(np.hypot(svz, ego_s or 0.0))
            rows.append({
                "t": round(float(t), 3), "s": round(Z, 2), "d": round(X, 2), "s_sigma": round(sZ, 2),
                "d_sigma": round(float(np.hypot(np.sqrt(PD[k, 0, 0]), f_rel * abs(X))), 2),
                "v": None if v is None else round(v, 2),
                "v_lo": None if v is None else round(max(0.0, v - 1.96 * svz), 2),
                "v_hi": None if v is None else round(v + 1.96 * svz, 2),
                "v_rel": round(vz, 2), "closing_mps": round(closing, 2),
                "ttc_s": None if ttc is None or ttc > 30 else round(ttc, 2),
                "ttc_sigma_s": None if ttc_sig is None or ttc is None or ttc > 30 else round(ttc_sig, 2),
                "heading_deg": None, "measured": not np.isnan(zs[k]), "cue": cues[k],
                "dist_m": round(Z, 2) if not np.isnan(zs[k]) else None})
        out[a["id"]] = rows
        unmeasured = [r["t"] for r in rows if not r["measured"]]
        if unmeasured and any(r["measured"] for r in rows):
            quality.append({"level": "info", "code": "size_unmeasurable", "actor": a["id"],
                            "message": f"{a['id']} is cut off by the frame edge or too close for part of the clip; "
                                       "its distance there is interpolated and shown with a wider range."})
    calib = {"mode": "monocular", "hfov_deg": hfov, "hfov_rel_sigma": f_rel, "focal_px": round(float(f), 1),
             "plate_width_m": plate_w, "size_cues": cue_counts, "hfov_from": "clip setting" if "hfov_deg" in meta else "default prior"}
    quality.append({"level": "warn", "code": "monocular_scale",
                    "message": f"No lane markings to calibrate against. Distances use the licence plate ({plate_w * 100:.1f} cm) "
                               f"or typical vehicle width, with an assumed camera field of view of {hfov:.0f}° "
                               f"(±{f_rel * 100:.0f}%). All distances and speeds share that ±{f_rel * 100:.0f}% scale "
                               "uncertainty; time-to-contact does not depend on it."})
    return out, calib, quality
