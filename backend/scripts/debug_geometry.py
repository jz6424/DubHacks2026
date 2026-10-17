"""Render lane detection for a few timestamps: line mask (left) and chosen VP/boundaries/dash runs (right)."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.geometry import _dash_runs, _find_lanes, _line_mask, _sample_line, _tophat  # noqa: E402
from app.pipeline.store import Clip  # noqa: E402

clip = Clip(sys.argv[1])
times = [float(x) for x in sys.argv[2].split(",")]
out = Path(sys.argv[3])
cap = cv2.VideoCapture(str(clip.video))
fps = cap.get(cv2.CAP_PROP_FPS)
rows = []
for t in times:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
    ok, f = cap.read()
    H, W = f.shape[:2]
    roi = (int(0.40 * H), int(0.96 * H))
    acts = clip.stage("track")["actors"]
    boxes = []
    for a in acts:
        sm = min(a["samples"], key=lambda s: abs(s["t"] - t))
        if abs(sm["t"] - t) <= 0.15:
            b = sm["box"]
            boxes.append((int(b[0] * W), int(b[1] * H), int(b[2] * W), int(b[3] * H)))
    mask = _line_mask(f, boxes, roi)
    res = _find_lanes(mask, None)
    vis = f.copy()
    if res:
        x0, y0 = res["x0"], res["y0"]
        cv2.circle(vis, (int(x0), int(y0)), 7, (0, 255, 0), -1)
        th = _tophat(f)
        thr = max(15.0, float(np.percentile(th[roi[0]:roi[1]], 99.0)) * 0.5)
        for key, col in (("aL", (0, 255, 255)), ("aR", (255, 0, 255))):
            a = res[key]
            if np.isnan(a):
                continue
            cv2.line(vis, (int(x0), int(y0)), (int(x0 + a * (H - y0)), H), col, 2)
            ys = np.arange(int(y0) + 8, roi[1])
            on = _sample_line(th, thr, x0, y0, a, ys)
            for y, v in zip(ys, on):
                if v:
                    cv2.circle(vis, (int(x0 + a * (y - y0)) + 10, int(y)), 1, (0, 0, 255), -1)
            print(f"t={t} {key}={a:+.3f} runs={_dash_runs(on, ys)}")
        print(f"t={t} vp=({x0:.0f},{y0:.0f}) h={3.7 / (res['aR'] - res['aL']):.2f}")
    m = cv2.cvtColor(mask * 255, cv2.COLOR_GRAY2BGR)
    rows.append(np.hstack([cv2.resize(m, (640, 360)), cv2.resize(vis, (640, 360))]))
cv2.imwrite(str(out), np.vstack(rows))
