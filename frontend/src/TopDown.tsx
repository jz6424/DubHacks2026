import { useEffect } from "react";
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

interface Props {
  scene: Scene;
  actors: Actor[];
  time: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
}

export function TopDown({ scene, actors, time, selected, onSelect }: Props) {
  const { ref, size, ctx } = useCanvas();
  const laneW = scene.geometry.calibration.lane_width_m;
  const period = scene.geometry.calibration.dash_period_m;

  // View transform: forward (+s) is up; ego sits near the bottom; lateral centre shifted left so the opposite
  // carriageway (negative d) stays visible.
  const view = () => {
    const { w, h } = size;
    const ego = egoAt(scene.ego.samples, time);
    const sEgo = ego?.s ?? 0;
    const scale = Math.min(h / (BEHIND + AHEAD), w / 46);
    const dCenter = -6;
    const toX = (d: number) => w / 2 + (d - dCenter) * scale;
    const toY = (s: number) => h - (s - (sEgo - BEHIND)) * scale;
    return { ego, sEgo, scale, toX, toY };
  };

  useEffect(() => {
    const c = ctx();
    if (!c || !size.w) return;
    const { w, h } = size;
    const { ego, sEgo, scale, toX, toY } = view();
    c.clearRect(0, 0, w, h);
    c.fillStyle = "#14171c";
    c.fillRect(0, 0, w, h);

    // Our carriageway: assumed lanes of the calibrated width, painted dashes moving with the ego vehicle.
    const left = -laneW / 2;
    const nLanes = 4;
    c.fillStyle = "#1d2229";
    c.fillRect(toX(left), 0, nLanes * laneW * scale, h);
    for (let k = 0; k <= nLanes; k++) {
      const x = toX(left + k * laneW);
      if (k === 0 || k === nLanes) {
        c.strokeStyle = k === 0 ? "#c9a227" : "#8a8f98";
        c.lineWidth = 2;
        c.beginPath();
        c.moveTo(x, 0);
        c.lineTo(x, h);
        c.stroke();
        continue;
      }
      c.fillStyle = "#6f7680";
      const first = Math.floor((sEgo - BEHIND) / period) * period;
      for (let s = first; s < sEgo + AHEAD; s += period) {
        c.fillRect(x - 1, toY(s + 3.05), 2, 3.05 * scale);
      }
    }

    // Distance ruler relative to the ego vehicle.
    c.font = "11px ui-sans-serif, system-ui";
    c.fillStyle = "#6b7280";
    c.strokeStyle = "#2a2f37";
    c.lineWidth = 1;
    for (let m = -10; m <= AHEAD; m += 10) {
      const y = toY(sEgo + m);
      c.beginPath();
      c.moveTo(0, y);
      c.lineTo(10, y);
      c.stroke();
      c.fillText(`${m > 0 ? "+" : ""}${m} m`, 14, y + 4);
    }

    for (const a of actors) {
      const g = groundAt(a, time);
      if (!g) continue;
      const col = actorColor(a.id);
      const isSel = selected === a.id;

      // Trail of motion relative to the ego vehicle (absolute trails at freeway speed would stretch ~60 m).
      const trail = a.ground.filter((p) => p.t <= time && p.t >= time - TRAIL_S);
      if (trail.length > 1) {
        const rel = (p: { t: number; s: number }) => p.s - (egoAt(scene.ego.samples, p.t)?.s ?? 0) + sEgo;
        c.strokeStyle = col;
        c.globalAlpha = 0.45;
        c.lineWidth = 2;
        c.beginPath();
        trail.forEach((p, i) => (i ? c.lineTo(toX(p.d), toY(rel(p))) : c.moveTo(toX(p.d), toY(rel(p)))));
        c.lineTo(toX(g.d), toY(g.s));
        c.stroke();
        c.globalAlpha = 1;
      }

      // 95% position uncertainty
      c.fillStyle = col;
      c.globalAlpha = isSel ? 0.22 : 0.1;
      c.beginPath();
      c.ellipse(toX(g.d), toY(g.s), Math.max(2, 1.96 * g.d_sigma * scale), Math.max(2, 1.96 * g.s_sigma * scale), 0, 0, Math.PI * 2);
      c.fill();
      c.globalAlpha = 1;

      const [bw, bl] = SIZE[a.cls] ?? SIZE.car;
      c.save();
      c.translate(toX(g.d), toY(g.s + bl / 2));
      c.rotate(((g.heading_deg ?? 0) * Math.PI) / 180);
      c.fillStyle = col;
      c.globalAlpha = g.measured ? 0.95 : 0.55;
      c.fillRect((-bw / 2) * scale, (-bl / 2) * scale, bw * scale, bl * scale);
      c.globalAlpha = 1;
      if (isSel) {
        c.strokeStyle = "#fff";
        c.lineWidth = 2;
        c.strokeRect((-bw / 2) * scale - 2, (-bl / 2) * scale - 2, bw * scale + 4, bl * scale + 4);
      }
      c.restore();

      const v = kmh(g.v);
      c.font = "600 11px ui-sans-serif, system-ui";
      c.fillStyle = col;
      c.fillText(`${a.id}${v !== null ? ` ${v.toFixed(0)}` : ""}`, toX(g.d) + (bw / 2) * scale + 4, toY(g.s + bl / 2) + 4);
    }

    // ego vehicle (camera ~2 m behind its front bumper)
    const egoD = ego?.d ?? 0;
    c.save();
    c.translate(toX(egoD), toY(sEgo - 0.25));
    c.fillStyle = "#f5f7fa";
    c.fillRect(-0.9 * scale, -2.25 * scale, 1.8 * scale, 4.5 * scale);
    c.restore();
    const ev = kmh(ego?.v);
    c.font = "700 11px ui-sans-serif, system-ui";
    c.fillStyle = "#f5f7fa";
    c.fillText(`EGO${ev !== null ? ` ${ev.toFixed(0)}` : ""}`, toX(egoD) + 1.2 * scale, toY(sEgo) + 4);
  });

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const { toX, toY } = view();
    let best: { id: string; d: number } | null = null;
    for (const a of actors) {
      const g = groundAt(a, time);
      if (!g) continue;
      const dist = Math.hypot(toX(g.d) - (e.clientX - r.left), toY(g.s + 2) - (e.clientY - r.top));
      if (dist < 24 && (!best || dist < best.d)) best = { id: a.id, d: dist };
    }
    onSelect(best ? best.id : null);
  };

  return <canvas ref={ref} className="topdown" onClick={onClick} title="Trails show motion relative to the recording vehicle" />;
}
