import type { Plan } from "../types";
import { useSession } from "../hooks/useSession";
import { Checklist } from "./Checklist";
import { StepVideo } from "./StepVideo";
import { CameraPanel } from "./CameraPanel";

export function SessionScreen({ plan }: { plan: Plan }) {
  const s = useSession(plan);
  const step = plan.steps[Math.min(s.current, plan.steps.length - 1)];
  if (s.finished) return <div className="finished">🎉 All {plan.steps.length} steps done!</div>; // TODO: recap w/ per-step times
  return (
    <div className="session">
      <aside><h2>{plan.title}</h2><Checklist steps={plan.steps} current={s.current} done={s.done} /></aside>
      <main>
        <header>Step {s.current + 1} of {plan.steps.length} · <b>{step.title}</b></header>
        <div className="stage">
          {plan.youtube_id && <StepVideo videoId={plan.youtube_id} step={step} />}
          <CameraPanel onFrame={s.sendFrame} boxes={s.boxes} verifying={s.verifying}
            confidence={s.confidence} hint={s.hint} />
        </div>
        <footer>
          <button onClick={() => s.act("back")}>← Back</button>
          <button onClick={() => s.act("skip")}>Skip</button>
          <button className="primary" onClick={() => s.act("next")}>Done ✓</button>
        </footer>
      </main>
    </div>
  );
}
