import { useEffect, useRef, useState } from "react";
import type { Step } from "../types";
import { fmt } from "../util";

interface Props {
  src: string;
  steps: Step[];
  step: Step;
  duration: number | null;
  doneSet: Set<number>;
  onJump: (i: number) => void;
}

/** Loops the current step's segment. Timeline shows every step as a band. */
export function StepVideo({ src, steps, step, duration, doneSet, onJump }: Props) {
  const ref = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(duration ?? 0);
  const [loop, setLoop] = useState(true);
  const start = step.start ?? 0;
  const end = step.end ?? dur;

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    v.currentTime = start;
    v.play().catch(() => {});
  }, [step.index, start]);

  function onTime() {
    const v = ref.current!;
    setT(v.currentTime);
    if (loop && end && v.currentTime >= end) v.currentTime = start;
  }

  const activeSub = step.substeps.findIndex(
    (s) => s.start != null && t >= s.start && t < (s.end ?? end),
  );
  const pct = (x: number) => `${dur ? (x / dur) * 100 : 0}%`;

  return (
    <div className="step-video">
      <div className="video-wrap">
        <video
          ref={ref}
          src={src}
          muted
          playsInline
          controls
          onTimeUpdate={onTime}
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
        />
        <span className="seg-badge">{fmt(start)} – {fmt(end)}</span>
      </div>

      <div className="timeline" aria-label="Tutorial timeline">
        {steps.map((s) => s.start != null && (
          <button
            key={s.index}
            title={s.title}
            onClick={() => onJump(s.index)}
            className={`band ${s.index === step.index ? "current" : ""} ${doneSet.has(s.index) ? "done" : ""}`}
            style={{ left: pct(s.start), width: `calc(${pct((s.end ?? dur) - s.start)} - 2px)` }}
          />
        ))}
        <div className="playhead" style={{ left: pct(t) }} />
      </div>

      <div className="video-controls">
        <label className="toggle">
          <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop this step
        </label>
        <button className="ghost" onClick={() => { ref.current!.currentTime = start; ref.current!.play(); }}>
          ↺ Replay
        </button>
      </div>

      {step.substeps.length > 0 && (
        <ul className="substeps">
          {step.substeps.map((s, i) => (
            <li key={i} className={i === activeSub ? "active" : ""}>
              <button onClick={() => { if (s.start != null) { ref.current!.currentTime = s.start; ref.current!.play(); } }}>
                {s.start != null && <time>{fmt(s.start)}</time>}
                <span>{s.text}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
