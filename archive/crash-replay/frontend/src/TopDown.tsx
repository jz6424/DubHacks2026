import { useEffect, useMemo } from "react";
import { actorColor, egoAt, groundAt, kmh } from "./interp";
import type { Actor, Scene } from "./types";
import { useCanvas } from "./useCanvas";

const SIZE: Record<string, [number, number]> = {
  // [width, length] in metres, typical
  car: [1.8, 4.5],
  truck: [2.6, 16],
  bus: [2.6, 12],
  motorcycle: [0.8, 2.2],
  bicycle: [0.6, 1.8],
  person: [0.6, 0.6],
};
// metres shown behind / ahead of the recording vehicle in lane mode; monocular mode sizes the view to the clip
const LANE_BEHIND = 15;
const LANE_AHEAD = 75;
const TRAIL_S = 2;
const RULER_PX = 18;

interface Props {
  scene: Scene;
  actors: Actor[];
  time: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
}

/**
 * Two layouts over one projection P(s, d) -> pixels (s = metres ahead, d = metres to the right):
 * - lane mode: a wide road strip, travel to the right, following the recording vehicle along the road with fixed
 *   lateral framing, so lane changes show as the vehicle crossing lane lines;
 * - monocular mode (no road model, distances from object sizes): camera at the bottom looking up, with its assumed
 *   field-of-view wedge, framed to the distances that occur in the clip.
 */
export function TopDown({ scene, actors, time, selected, onSelect }: Props) {
  const { ref, size, ctx } = useCanvas();
  const cal = scene.geometry.calibration;
  const laneW = cal.lane_width_m;
  const period = cal.dash_period_m;
  const observed = scene.geometry.road_lines;
  const mono = cal.mode === "monocular";
  const hfov = Number(cal.hfov_deg ?? 70);

  const frame = useMemo(() => {
    if (mono) {
      const dists = actors
        .flatMap((a) => a.ground.filter((g) => g.measured).map((g) => g.s))
        .sort((a, b) => a - b);
      const p90 = dists.length ? dists[Math.floor(0.9 * (dists.length - 1))] : 10;
      const ahead = Math.min(75, Math.max(5, p90 * 1.2));
      return { lineDs: [] as number[], leftEdge: 0, rightObserved: 0, rightEdge: 0, behind: Math.max(0.8, 0.08 * ahead), ahead };
    }
    // Lateral extent of our carriageway over the whole clip: observed lines, plus same-side vehicles beyond them.
    const lineDs = observed.length ? observed.map((l) => l.d) : [-laneW / 2, laneW / 2];
    const leftEdge = Math.min(...lineDs);
    const rightObserved = Math.max(...lineDs);
    const sameSide = actors.flatMap((a) => a.ground.map((g) => g.d)).filter((d) => d > leftEdge && d < rightObserved + 4 * laneW);
    const egoDs = scene.ego.samples.map((e) => e.d).filter((d): d is number => d !== null);
    const rightEdge = Math.max(rightObserved, ...egoDs.map((d) => d + laneW / 2), ...sameSide.map((d) => d + laneW / 2));
    const lanesRight = Math.ceil((rightEdge - rightObserved) / laneW - 0.05);
    return { lineDs, leftEdge, rightObserved, rightEdge: rightObserved + Math.max(0, lanesRight) * laneW, behind: LANE_BEHIND, ahead: LANE_AHEAD };
  }, [observed, actors, scene.ego.samples, laneW, mono]);

  const view = () => {
    const { w, h } = size;
    const ego = egoAt(scene.ego.samples, time);
    const sEgo = mono ? 0 : (ego?.s ?? 0); // monocular positions are already relative to the camera
    let scale: number;
    let P: (s: number, d: number) => [number, number];
    if (mono) {
      scale = (h - RULER_PX - 10) / (frame.behind + frame.ahead);
      P = (s, d) => [w / 2 + d * scale, h - 6 - (s + frame.behind) * scale];
    } else {
      const span = frame.rightEdge - frame.leftEdge + 3;
      scale = Math.min(w / (frame.behind + frame.ahead), (h - RULER_PX - 8) / span);
      const dCenter = (frame.leftEdge + frame.rightEdge) / 2;
      P = (s, d) => [(s - (sEgo - frame.behind)) * scale, RULER_PX + (h - RULER_PX) / 2 + (d - dCenter) * scale];
    }
    // canvas rotation that maps "along +s" onto the screen's travel direction
    const rot = mono ? -Math.PI / 2 : 0;
    return { ego, sEgo, scale, P, rot };
  };

  useEffect(() => {
    const c = ctx();
    if (!c || !size.w) return;
    const { w, h } = size;
    const { ego, sEgo, scale, P, rot } = view();
    const sLo = sEgo - frame.behind;
    const sHi = sEgo + frame.ahead;
    const egoD = mono ? 0 : (ego?.d ?? 0);
    const line = (a: [number, number], b: [number, number]) => {
      c.beginPath();
      c.moveTo(...a);
      c.lineTo(...b);
      c.stroke();
    };
    c.clearRect(0, 0, w, h);
    c.fillStyle = "#14171c";
    c.fillRect(0, 0, w, h);
    c.font = "11px ui-sans-serif, system-ui";

    if (mono) {
      const dMax = w / 2 / scale;
      const step = frame.ahead <= 8 ? 1 : frame.ahead <= 25 ? 2 : frame.ahead <= 50 ? 5 : 10;
      c.strokeStyle = "#20252c";
      c.lineWidth = 1;
      for (let m = 0; m <= sHi; m += step) line(P(m, -dMax), P(m, dMax));
      for (let d = -Math.floor(dMax / step) * step; d <= dMax; d += step) line(P(sLo, d), P(sHi, d));
      // distance labels up the left side
      c.fillStyle = "#6b7280";
      for (let m = step; m <= sHi; m += step) c.fillText(`${m} m`, 8, P(m, 0)[1] + 4);
      // the camera's assumed field of view: the scale of everything here depends on it
      const half = Math.tan(((hfov / 2) * Math.PI) / 180);
      c.fillStyle = "rgba(90,169,255,0.06)";
      c.strokeStyle = "rgba(90,169,255,0.35)";
      c.setLineDash([4, 4]);
      c.beginPath();
      c.moveTo(...P(0, 0));
      c.lineTo(...P(sHi, -half * sHi));
      c.lineTo(...P(sHi, half * sHi));
      c.closePath();
      c.fill();
      c.stroke();
      c.setLineDash([]);
      c.fillStyle = "#6b7280";
      const [lx, ly] = P(sHi * 0.92, half * sHi * 0.92);
      c.fillText(`assumed ${hfov.toFixed(0)}° field of view`, Math.min(lx + 6, w - 160), ly + 4);
    } else {
      // road surface and the lane the recording vehicle is in now
      c.fillStyle = "#1d2229";
      c.fillRect(0, P(0, frame.leftEdge)[1], w, (frame.rightEdge - frame.leftEdge) * scale);
      const laneIdx = Math.round(egoD / laneW);
      c.fillStyle = "rgba(90,169,255,0.09)";
      c.fillRect(0, P(0, laneIdx * laneW - laneW / 2)[1], w, laneW * scale);
      const drawDashed = (d: number, color: string) => {
        c.fillStyle = color;
        for (let s = Math.floor(sLo / period) * period; s < sHi; s += period) c.fillRect(P(s, d)[0], P(s, d)[1] - 1, 3.05 * scale, 2);
      };
      const drawSolid = (d: number, color: string) => {
        c.fillStyle = color;
        c.fillRect(0, P(0, d)[1] - 1, w, 2);
      };
      if (observed.length) {
        for (const l of observed) (l.kind === "solid" ? drawSolid : drawDashed)(l.d, l.kind === "solid" ? "#c9b98a" : "#8a919b");
      } else {
        frame.lineDs.forEach((d) => drawDashed(d, "#3b414a"));
      }
      // lanes we never saw the markings of, but where vehicles drive: faint, assumed
      for (let d = frame.rightObserved + laneW; d <= frame.rightEdge + 0.01; d += laneW) drawDashed(d, "#353b44");

      // distance ruler along the top, relative to the recording vehicle
      c.fillStyle = "#6b7280";
      for (let m = -10; m <= frame.ahead; m += 10) {
        const [x] = P(sEgo + m, 0);
        c.fillRect(x, 0, 1, 6);
        c.fillText(`${m > 0 ? "+" : ""}${m} m`, x + 3, 13);
      }

      // the recording vehicle's own path on the road, last few metres
      const past = scene.ego.samples.filter((p) => p.t <= time && p.d !== null && p.s >= sLo);
      if (past.length > 1) {
        c.strokeStyle = "rgba(245,247,250,0.7)";
        c.lineWidth = 2;
        c.setLineDash([5, 4]);
        c.beginPath();
        past.forEach((p, i) => (i ? c.lineTo(...P(p.s, p.d!)) : c.moveTo(...P(p.s, p.d!))));
        c.lineTo(...P(sEgo, egoD));
        c.stroke();
        c.setLineDash([]);
      }
    }

    for (const a of actors) {
      const g = groundAt(a, time);
      // Beyond the leftmost line is the opposite carriageway: those vehicles are far and poorly placed, so they
      // stay in the table but are not drawn here unless selected.
      if (!g || (!mono && g.d < frame.leftEdge - 0.5 && selected !== a.id)) continue;
      const col = actorColor(a.id);
      const isSel = selected === a.id;
      const [bw, bl] = SIZE[a.cls] ?? SIZE.car;

      // trail: motion relative to the recording vehicle (absolute trails at freeway speed would span ~60 m)
      const trail = a.ground.filter((p) => p.t <= time && p.t >= time - TRAIL_S);
      if (trail.length > 1) {
        const rel = (p: { t: number; s: number }) => (mono ? p.s : p.s - (egoAt(scene.ego.samples, p.t)?.s ?? 0) + sEgo);
        c.strokeStyle = col;
        c.globalAlpha = 0.45;
        c.lineWidth = 2;
        c.beginPath();
        trail.forEach((p, i) => (i ? c.lineTo(...P(rel(p), p.d)) : c.moveTo(...P(rel(p), p.d))));
        c.lineTo(...P(g.s, g.d));
        c.stroke();
        c.globalAlpha = 1;
      }

      // 95% position uncertainty (along / across)
      const [ex, ey] = P(g.s, g.d);
      const rs = Math.max(2, 1.96 * g.s_sigma * scale);
      const rd = Math.max(2, 1.96 * g.d_sigma * scale);
      c.fillStyle = col;
      c.globalAlpha = isSel ? 0.22 : 0.1;
      c.beginPath();
      c.ellipse(ex, ey, mono ? rd : rs, mono ? rs : rd, 0, 0, Math.PI * 2);
      c.fill();
      c.globalAlpha = 1;

      // The box bottom is the face nearest the camera, so the body extends away from it.
      c.save();
      c.translate(...P(g.s + bl / 2, g.d));
      c.rotate(rot + ((g.heading_deg ?? 0) * Math.PI) / 180);
      c.fillStyle = col;
      c.globalAlpha = g.measured ? 0.95 : 0.5;
      c.fillRect((-bl / 2) * scale, (-bw / 2) * scale, bl * scale, bw * scale);
      c.globalAlpha = 1;
      if (isSel) {
        c.strokeStyle = "#fff";
        c.lineWidth = 2;
        c.strokeRect((-bl / 2) * scale - 2, (-bw / 2) * scale - 2, bl * scale + 4, bw * scale + 4);
      }
      c.restore();

      const v = kmh(g.v);
      c.font = "600 11px ui-sans-serif, system-ui";
      c.fillStyle = col;
      const [tx, ty] = mono ? P(g.s, g.d + bw / 2) : P(g.s, g.d - bw / 2);
      c.fillText(`${a.id}${v !== null ? ` ${v.toFixed(0)}` : ""}`, mono ? tx + 4 : tx, mono ? ty + 4 : ty - 4);
    }

    const ev = kmh(ego?.v);
    c.font = "700 11px ui-sans-serif, system-ui";
    c.fillStyle = "#f5f7fa";
    if (mono) {
      // We don't know the recording vehicle's size or where the camera sits on it: draw just the camera, looking up.
      const [x, y] = P(0, 0);
      c.beginPath();
      c.moveTo(x, y - 9);
      c.lineTo(x - 7, y + 6);
      c.lineTo(x + 7, y + 6);
      c.closePath();
      c.fill();
      c.fillText(`CAMERA${ev !== null ? ` ${ev.toFixed(0)} km/h` : ""}`, x + 11, y + 4);
    } else {
      // recording vehicle (camera ~2 m behind its front bumper)
      const [x, y] = P(sEgo - 2.5, egoD);
      c.fillRect(x, y - 0.9 * scale, 4.5 * scale, 1.8 * scale);
      c.fillText(`EGO${ev !== null ? ` ${ev.toFixed(0)}` : ""}`, x, y - 0.9 * scale - 4);
    }
  });

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const { P } = view();
    let best: { id: string; d: number } | null = null;
    for (const a of actors) {
      const g = groundAt(a, time);
      if (!g) continue;
      const [x, y] = P(g.s + 2, g.d);
      const dist = Math.hypot(x - (e.clientX - r.left), y - (e.clientY - r.top));
      if (dist < 24 && (!best || dist < best.d)) best = { id: a.id, d: dist };
    }
    onSelect(best ? best.id : null);
  };

  return <canvas ref={ref} className="topdown" onClick={onClick} title="Trails show motion relative to the recording camera" />;
}
