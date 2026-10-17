import { useEffect, type RefObject } from "react";
import { actorColor, boxAt, groundAt, kmh } from "./interp";
import type { Actor, Scene } from "./types";
import { useCanvas } from "./useCanvas";

interface Props {
  scene: Scene;
  actors: Actor[];
  time: number;
  videoUrl: string;
  videoRef: RefObject<HTMLVideoElement>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  showLanes: boolean;
}

export function VideoPanel({ scene, actors, time, videoUrl, videoRef, selected, onSelect, showLanes }: Props) {
  const { ref, size, ctx } = useCanvas();
  const { width: W, height: H } = scene.clip;

  useEffect(() => {
    const c = ctx();
    if (!c) return;
    const { w, h } = size;
    c.clearRect(0, 0, w, h);

    if (showLanes) {
      const lane = nearestLane(scene, time);
      if (lane && lane.x0 !== null && lane.y0 !== null) {
        const x0 = lane.x0 * w;
        const y0 = lane.y0 * h;
        const sx = w / W;
        const sy = h / H;
        c.lineWidth = 2;
        for (const [a, col] of [
          [lane.aL, "#ffd54a"],
          [lane.aR, "#ff4fd8"],
        ] as const) {
          if (a === null) continue;
          // a is dx/dy in source pixels; convert to display pixels
          c.strokeStyle = col;
          c.beginPath();
          c.moveTo(x0, y0);
          c.lineTo(x0 + (a * (h - y0) * sx) / sy, h);
          c.stroke();
        }
        c.fillStyle = "#3dff7a";
        c.beginPath();
        c.arc(x0, y0, 5, 0, Math.PI * 2);
        c.fill();
        c.font = "12px ui-sans-serif, system-ui";
        c.fillText("vanishing point", x0 + 8, y0 - 6);
      }
    }

    c.font = "600 12px ui-sans-serif, system-ui";
    for (const a of actors) {
      const b = boxAt(a, time);
      if (!b) continue;
      const [x0, y0, x1, y1] = b.box;
      const col = actorColor(a.id);
      const isSel = selected === a.id;
      c.strokeStyle = col;
      c.lineWidth = isSel ? 3 : 1.75;
      c.setLineDash(b.interp ? [5, 4] : []);
      c.strokeRect(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h);
      c.setLineDash([]);
      const g = groundAt(a, time);
      const v = kmh(g?.v);
      const label = `${a.id}${v !== null ? ` ${v.toFixed(0)} km/h` : ""}`;
      const tw = c.measureText(label).width;
      const ly = Math.max(14, y0 * h - 4);
      c.fillStyle = "rgba(10,12,16,0.75)";
      c.fillRect(x0 * w - 1, ly - 12, tw + 8, 16);
      c.fillStyle = col;
      c.fillText(label, x0 * w + 3, ly);
    }
  }, [scene, actors, time, size, selected, showLanes, W, H, ctx]);

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    let hit: { id: string; area: number } | null = null;
    for (const a of actors) {
      const b = boxAt(a, time);
      if (!b) continue;
      const [x0, y0, x1, y1] = b.box;
      if (px >= x0 && px <= x1 && py >= y0 && py <= y1) {
        const area = (x1 - x0) * (y1 - y0);
        if (!hit || area < hit.area) hit = { id: a.id, area };
      }
    }
    onSelect(hit ? hit.id : null);
  };

  return (
    <div className="video-wrap" style={{ aspectRatio: `${W} / ${H}` }}>
      <video ref={videoRef} src={videoUrl} muted playsInline preload="auto" />
      <canvas ref={ref} className="overlay" onClick={onClick} />
    </div>
  );
}

function nearestLane(scene: Scene, time: number) {
  const ls = scene.geometry.lanes;
  if (!ls.length) return null;
  const i = Math.min(ls.length - 1, Math.max(0, Math.round(time * scene.frame_fps)));
  return ls[i];
}
