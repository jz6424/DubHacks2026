import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCamera } from "../hooks/useCamera";
import { useStepChecker } from "../hooks/useStepChecker";
import type { DoneHow, Plan } from "../types";
import { CameraPanel } from "./CameraPanel";
import { Checklist } from "./Checklist";
import { StepVideo } from "./StepVideo";
import { Timer } from "./Timer";
import { Finish } from "./Finish";

export function Session({ plan, onExit }: { plan: Plan; onExit: () => void }) {
  const [current, setCurrent] = useState(0);
  const [done, setDone] = useState<Record<number, DoneHow>>({});
  const [auto, setAuto] = useState(true);
  const [celebrate, setCelebrate] = useState(false);
  const [showIngredients, setShowIngredients] = useState(false);
  const startedAt = useRef<Record<number, number>>({ 0: Date.now() });
  const durations = useRef<Record<number, number>>({});

  const step = plan.steps[current];
  const finished = current >= plan.steps.length;
  const cam = useCamera();

  const currentRef = useRef(current);
  currentRef.current = current;

  const complete = useCallback((how: DoneHow) => {
    const cur = currentRef.current;
    if (cur >= plan.steps.length) return;
    durations.current[cur] = (Date.now() - (startedAt.current[cur] ?? Date.now())) / 1000;
    startedAt.current[cur + 1] = Date.now();
    setDone((d) => ({ ...d, [cur]: how }));
    setCurrent(cur + 1);
  }, [plan.steps.length]);

  const onVisionComplete = useCallback(() => {
    setCelebrate(true);
    setTimeout(() => { setCelebrate(false); complete("vision"); }, 1100);
  }, [complete]);

  const checker = useStepChecker({
    planId: plan.id,
    step: finished || celebrate ? undefined : step,
    enabled: auto && !celebrate && cam.ready,
    snapshot: cam.snapshot,
    onComplete: onVisionComplete,
  });

  const jump = useCallback((i: number) => {
    setCurrent(i);
    startedAt.current[i] = Date.now();
    setDone((d) => {
      const next = { ...d };
      Object.keys(next).forEach((k) => { if (+k >= i) delete next[+k]; });
      return next;
    });
  }, []);

  // Keyboard: → / Space = done, ← = back, S = skip
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); complete("manual"); }
      if (e.key === "ArrowLeft" && current > 0) jump(current - 1);
      if (e.key.toLowerCase() === "s") complete("skipped");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [complete, jump, current]);

  const doneSet = useMemo(() => new Set(Object.keys(done).map(Number)), [done]);

  if (finished) {
    return <Finish plan={plan} done={done} durations={durations.current} onRestart={() => jump(0)} onExit={onExit} />;
  }

  return (
    <div className="session">
      <aside className="sidebar">
        <button className="back-link" onClick={onExit}>← All tutorials</button>
        <h2>{plan.title}</h2>
        <div className="progress"><div style={{ width: `${(doneSet.size / plan.steps.length) * 100}%` }} /></div>
        <p className="muted small">{doneSet.size} of {plan.steps.length} done</p>

        {plan.ingredients.length > 0 && (
          <div className="ingredients">
            <button className="ghost small" onClick={() => setShowIngredients((s) => !s)}>
              {showIngredients ? "▾" : "▸"} Ingredients ({plan.ingredients.length})
            </button>
            {showIngredients && <ul>{plan.ingredients.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          </div>
        )}

        <Checklist steps={plan.steps} current={current} done={done} onJump={jump} />
      </aside>

      <main className="main">
        <header className="step-header">
          <span className="eyebrow">Step {current + 1} of {plan.steps.length}</span>
          <h1>{step.title}</h1>
          {step.verifiable
            ? <p className="check-line"><span>Done when</span> {step.visual_check}</p>
            : <p className="check-line manual"><span>Manual step</span> Press Done when you've finished.</p>}
          {step.timer_seconds && <Timer seconds={step.timer_seconds} onDone={() => complete("manual")} />}
        </header>

        <div className={`stage ${plan.video_url ? "" : "no-video"}`}>
          {plan.video_url && (
            <StepVideo src={plan.video_url} steps={plan.steps} step={step} duration={plan.duration}
              doneSet={doneSet} onJump={jump} />
          )}
          <CameraPanel
            videoRef={cam.videoRef}
            cameraError={cam.error}
            status={checker.status}
            confidence={checker.last?.confidence ?? null}
            hint={checker.hint}
            checkError={checker.error}
            latencyMs={checker.last?.latency_ms ?? null}
            celebrate={celebrate}
          />
        </div>

        <footer className="actions">
          <label className="toggle">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-check with camera
          </label>
          <div className="spacer" />
          <button onClick={() => current > 0 && jump(current - 1)} disabled={current === 0}>← Back</button>
          <button onClick={() => complete("skipped")}>Skip</button>
          <button className="primary" onClick={() => complete("manual")}>Done ✓</button>
        </footer>
      </main>
    </div>
  );
}
