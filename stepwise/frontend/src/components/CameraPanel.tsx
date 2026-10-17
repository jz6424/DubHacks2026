import { useCamera } from "../hooks/useCamera";
import type { Box } from "../types";

export function CameraPanel({ onFrame, boxes, verifying, confidence, hint }:
  { onFrame: (b: Blob) => void; boxes: Box[]; verifying: boolean; confidence: number; hint: string }) {
  const ref = useCamera(onFrame);
  return (
    <div className="camera">
      <video ref={ref} autoPlay muted playsInline style={{ transform: "scaleX(-1)" }} />
      {boxes.map((b, i) => (   // grounding boxes from Isaac (mirror x to match the preview)
        <div key={i} className="box" style={{ left: `${(1 - b.x2) * 100}%`, top: `${b.y1 * 100}%`,
          width: `${(b.x2 - b.x1) * 100}%`, height: `${(b.y2 - b.y1) * 100}%` }}><span>{b.label}</span></div>
      ))}
      <div className={`confidence-ring ${verifying ? "on" : ""}`} style={{ ["--p" as any]: confidence }} />
      {hint && <div className="hint-toast">{hint}</div>}
    </div>
  );
}
