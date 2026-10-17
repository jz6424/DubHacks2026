import type { DoneHow, Plan } from "../types";
import { fmt } from "../util";

interface Props {
  plan: Plan;
  done: Record<number, DoneHow>;
  durations: Record<number, number>;
  onRestart: () => void;
  onExit: () => void;
}

export function Finish({ plan, done, durations, onRestart, onExit }: Props) {
  const total = Object.values(durations).reduce((a, b) => a + b, 0);
  const byVision = Object.values(done).filter((h) => h === "vision").length;
  return (
    <div className="finish">
      <div className="finish-mark">✓</div>
      <h1>{plan.title}: done</h1>
      <p className="lede">
        {plan.steps.length} steps in {fmt(total)} · {byVision} checked off by the camera
      </p>
      <table className="recap">
        <thead><tr><th>Step</th><th>You</th><th>Video</th><th /></tr></thead>
        <tbody>
          {plan.steps.map((s) => (
            <tr key={s.index}>
              <td>{s.title}</td>
              <td>{fmt(durations[s.index])}</td>
              <td className="muted">{s.start != null && s.end != null ? fmt(s.end - s.start) : "–"}</td>
              <td className="muted">{done[s.index] === "vision" ? "camera" : done[s.index] ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row">
        <button onClick={onRestart}>Start over</button>
        <button className="primary" onClick={onExit}>Make something else</button>
      </div>
    </div>
  );
}
