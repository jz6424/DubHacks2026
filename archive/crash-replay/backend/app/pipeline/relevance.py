"""Which road users matter? Signals for an automatic relevance tier; the user can override any of them.

- abrupt: sudden change in image motion or box shape, in box-heights/s^2 (scale-free, so near and far compare
  fairly). Flips, spins and impacts score high; steady traffic scores low.
- path_dist_m: closest distance while roughly in the recording camera's path.
- max_decel: hardest deceleration of the smoothed ground speed, when speeds are known.
"""
import numpy as np


def signals(actor: dict, ground: list[dict], ego_samples: list[dict], mono: bool) -> dict:
    s = [x for x in actor["samples"] if not x["interp"]]
    abrupt = 0.0
    if len(s) >= 4:
        t = np.array([x["t"] for x in s])
        b = np.array([x["box"] for x in s])
        h = np.maximum(b[:, 3] - b[:, 1], 1e-3)
        cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
        aspect = np.log(np.maximum(b[:, 2] - b[:, 0], 1e-3) / h)
        for k in range(1, len(s) - 1):
            dt1, dt2 = t[k] - t[k - 1], t[k + 1] - t[k]
            if dt1 > 0.6 or dt2 > 0.6:
                continue  # don't score across gaps
            hm = h[k]
            v1 = np.hypot(cx[k] - cx[k - 1], cy[k] - cy[k - 1]) / hm / dt1
            v2 = np.hypot(cx[k + 1] - cx[k], cy[k + 1] - cy[k]) / hm / dt2
            acc = abs(v2 - v1) / ((dt1 + dt2) / 2)
            shape = abs(aspect[k + 1] - aspect[k - 1]) / (dt1 + dt2)
            abrupt = max(abrupt, acc + 4 * shape)
    path_dist = None
    if ground:
        ego_d = {round(e["t"], 3): (e["d"] or 0.0) for e in ego_samples}
        lim = 2.0 if mono else 2.6
        near = [g["dist_m"] for g in ground if g.get("dist_m") is not None
                and abs(g["d"] - (0.0 if mono else ego_d.get(round(g["t"], 3), 0.0))) <= lim]
        path_dist = min(near) if near else None
    max_decel = None
    vs = [(g["t"], g["v"]) for g in ground if g.get("v") is not None]
    if len(vs) >= 5:
        tt, vv = np.array(vs).T
        dv = -np.gradient(vv, tt)
        max_decel = float(np.max(dv))
    min_dist = min((g["dist_m"] for g in ground if g.get("dist_m") is not None), default=None)
    return {"abrupt": round(float(abrupt), 2), "path_dist_m": path_dist, "min_dist_m": min_dist,
            "max_decel_mps2": None if max_decel is None else round(max_decel, 1)}


# Automatic relevance tiers (the user's marks always win). Lane mode uses road distances; monocular (close-range)
# clips use camera distances.
INVOLVED_PATH_M = {"lanes": 20.0, "monocular": 3.0}
NEARBY_M = {"lanes": 40.0, "monocular": 10.0}
HARD_BRAKE_MPS2 = 4.0


def auto_tier(sig: dict, mode: str, opposite_side: bool) -> tuple[str, str]:
    if opposite_side:
        return "background", "on the other side of the road"
    if sig["path_dist_m"] is not None and sig["path_dist_m"] <= INVOLVED_PATH_M[mode]:
        return "involved", f"came within {sig['path_dist_m']:.0f} m in the camera's path" if sig["path_dist_m"] >= 2 \
            else f"came within {sig['path_dist_m']:.1f} m in the camera's path"
    if sig["max_decel_mps2"] is not None and sig["max_decel_mps2"] >= HARD_BRAKE_MPS2 and \
            sig["min_dist_m"] is not None and sig["min_dist_m"] <= 40:
        return "involved", f"decelerated hard ({sig['max_decel_mps2']:.0f} m/s²) nearby"
    if sig["min_dist_m"] is not None and sig["min_dist_m"] <= NEARBY_M[mode]:
        return "nearby", f"came within {sig['min_dist_m']:.0f} m"
    return "background", "never close to the camera" if sig["min_dist_m"] is not None else "never placed on the road"
