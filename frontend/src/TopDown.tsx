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
const BEHIND = 15; // metres of road shown behind the ego vehicle
const AHEAD = 75;
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
 * Landscape top-down strip: travel direction is to the right, + lateral (right of travel) is down. The view follows
 * the recording vehicle along the road but its lateral framing is fixed for the whole clip, so lane changes show as
 * the ego vehicle moving across the lane lines.
 */
export function TopDown({ scene, actors, time, selected, onSelect }: Props) {
  const { ref, size, ctx } = useCanvas();
  const laneW = scene.geometry.calibration.lane_width_m;
  const period = scene.geometry.calibration.dash_period_m;
  const observed = scene.geometry.road_lines;

  // Lateral extent of our carriageway over the whole clip: observed lines, plus same-side vehicles beyond them.
  const frame = useMemo(() => {
    const lineDs = observed.length ? observed.map((l) => l.d) : [-laneW / 2, laneW / 2];
    const leftEdge = Math.min(...lineDs);
    const rightObserved = Math.max(...lineDs);
    const sameSide = actors.flatMap((a) => a.ground.map((g) => g.d)).filter((d) => d > leftEdge && d < rightObserved + 4 * laneW);
    const egoDs = scene.ego.samples.map((e) => e.d).filter((d): d is number => d !== null);
    const rightEdge = Math.max(rightObserved, ...egoDs.map((d) => d + laneW / 2), ...sameSide.map((d) => d + laneW / 2));
    const lanesRight = Math.ceil((rightEdge - rightObserved) / laneW - 0.05);
    return { lineDs, leftEdge, rightObserved, rightEdge: rightObserved + Math.max(0, lanesRight) * laneW };
  }, [observed, actors, scene.ego.samples, laneW]);

  const view = () => {
    const { w, h } = size;
    const ego = egoAt(scene.ego.samples, time);
    const sEgo = ego?.s ?? 0;
    const span = frame.rightEdge - frame.leftEdge + 3; // a little margin outside the edges
    const scale = Math.min(w / (BEHIND + AHEAD), (h - RULER_PX - 8) / span);
    const dCenter = (frame.leftEdge + frame.rightEdge) / 2;
    const toX = (s: number) => (s - (sEgo - BEHIND)) * scale;
    const toY = (d: number) => RULER_PX + (h - RULER_PX) / 2 + (d - dCenter) * scale;
    return { ego, sEgo, scale, toX, toY };
  };

  useEffect(() => {
    const c = ctx();
    if (!c || !size.w) return;
    const { w, h } = size;
    const { ego, sEgo, scale, toX, toY } = view();
    const sLo = sEgo - BEHIND;
    const sHi = sEgo + AHEAD;
    c.clearRect(0, 0, w, h);
    c.fillStyle = "#14171c";
    c.fillRect(0, 0, w, h);

    // road surface and the lane the recording vehicle is in now
    c.fillStyle = "#1d2229";
    c.fillRect(0, toY(frame.leftEdge), w, (frame.rightEdge - frame.leftEdge) * scale);
    const egoD = ego?.d ?? 0;
    const laneIdx = Math.round(egoD / laneW);
    c.fillStyle = "rgba(90,169,255,0.09)";
    c.fillRect(0, toY(laneIdx * laneW - laneW / 2), w, laneW * scale);

    const drawDashed = (d: number, color: string) => {
      c.fillStyle = color;
      for (let s = Math.floor(sLo / period) * period; s < sHi; s += period) c.fillRect(toX(s), toY(d) - 1, 3.05 * scale, 2);
    };
    const drawSolid = (d: number, color: string) => {
      c.fillStyle = color;
      c.fillRect(0, toY(d) - 1, w, 2);
    };
    if (observed.length) {
      for (const l of observed) (l.kind === "solid" ? drawSolid : drawDashed)(l.d, l.kind === "solid" ? "#c9b98a" : "#8a919b");
    } else {
      frame.lineDs.forEach((d) => drawDashed(d, "#3b414a"));
    }
    // lanes we never saw the markings of, but where vehicles drive: faint, assumed
    for (let d = frame.rightObserved + laneW; d <= frame.rightEdge + 0.01; d += laneW) drawDashed(d, "#353b44");

    // distance ruler along the top, relative to the recording vehicle
    c.font = "11px ui-sans-serif, system-ui";
    c.fillStyle = "#6b7280";
    for (let m = -10; m <= AHEAD; m += 10) {
      const x = toX(sEgo + m);
      c.fillRect(x, 0, 1, 6);
      c.fillText(`${m > 0 ? "+" : ""}${m} m`, x + 3, 13);
    }

    // the recording vehicle's own path on the road, last BEHIND metres
    const past = scene.ego.samples.filter((p) => p.t <= time && p.d !== null && p.s >= sLo);
    if (past.length > 1) {
      c.strokeStyle = "rgba(245,247,250,0.7)";
      c.lineWidth = 2;
      c.setLineDash([5, 4]);
      c.beginPath();
      past.forEach((p, i) => (i ? c.lineTo(toX(p.s), toY(p.d!)) : c.moveTo(toX(p.s), toY(p.d!))));
      c.lineTo(toX(sEgo), toY(egoD));
      c.stroke();
      c.setLineDash([]);
    }

    for (const a of actors) {
      const g = groundAt(a, time);
      // Beyond the leftmost line is the opposite carriageway: those vehicles are far and poorly placed, so they
      // stay in the table but are not drawn here unless selected.
      if (!g || (g.d < frame.leftEdge - 0.5 && selected !== a.id)) continue;
      const col = actorColor(a.id);
      const isSel = selected === a.id;
      const [bw, bl] = SIZE[a.cls] ?? SIZE.car;

      // trail of motion relative to the recording vehicle (absolute trails at freeway speed would span ~60 m)
      const trail = a.ground.filter((p) => p.t <= time && p.t >= time - TRAIL_S);
      if (trail.length > 1) {
        const rel = (p: { t: number; s: number }) => p.s - (egoAt(scene.ego.samples, p.t)?.s ?? 0) + sEgo;
        c.strokeStyle = col;
        c.globalAlpha = 0.45;
        c.lineWidth = 2;
        c.beginPath();
        trail.forEach((p, i) => (i ? c.lineTo(toX(rel(p)), toY(p.d)) : c.moveTo(toX(rel(p)), toY(p.d))));
        c.lineTo(toX(g.s), toY(g.d));
        c.stroke();
        c.globalAlpha = 1;
      }

      // 95% position uncertainty
      c.fillStyle = col;
      c.globalAlpha = isSel ? 0.22 : 0.1;
      c.beginPath();
      c.ellipse(toX(g.s), toY(g.d), Math.max(2, 1.96 * g.s_sigma * scale), Math.max(2, 1.96 * g.d_sigma * scale), 0, 0, Math.PI * 2);
      c.fill();
      c.globalAlpha = 1;

      // the box bottom is the vehicle's rear (it is ahead of us), so the body extends forward from s
      c.save();
      c.translate(toX(g.s + bl / 2), toY(g.d));
      c.rotate(((g.heading_deg ?? 0) * Math.PI) / 180);
      c.fillStyle = col;
      c.globalAlpha = g.measured ? 0.95 : 0.55;
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
      c.fillText(`${a.id}${v !== null ? ` ${v.toFixed(0)}` : ""}`, toX(g.s), toY(g.d) - (bw / 2) * scale - 4);
    }

    // recording vehicle (camera ~2 m behind its front bumper)
    c.fillStyle = "#f5f7fa";
    c.fillRect(toX(sEgo - 2.5), toY(egoD) - 0.9 * scale, 4.5 * scale, 1.8 * scale);
    const ev = kmh(ego?.v);
    c.font = "700 11px ui-sans-serif, system-ui";
    c.fillText(`EGO${ev !== null ? ` ${ev.toFixed(0)}` : ""}`, toX(sEgo - 2.5), toY(egoD) - 0.9 * scale - 4);
  });

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const { toX, toY } = view();
    let best: { id: string; d: number } | null = null;
    for (const a of actors) {
      const g = groundAt(a, time);
      if (!g) continue;
      const dist = Math.hypot(toX(g.s + 2) - (e.clientX - r.left), toY(g.d) - (e.clientY - r.top));
      if (dist < 24 && (!best || dist < best.d)) best = { id: a.id, d: dist };
    }
    onSelect(best ? best.id : null);
  };

  return <canvas ref={ref} className="topdown" onClick={onClick} title="Trails show motion relative to the recording vehicle" />;
}
