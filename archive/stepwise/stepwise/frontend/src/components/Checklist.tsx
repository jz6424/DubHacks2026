import type { Step } from "../types";

export function Checklist({ steps, current, done }: { steps: Step[]; current: number; done: Record<number, string> }) {
  return (
    <ol className="checklist">
      {steps.map(s => (
        <li key={s.index} className={done[s.index] ? `done ${done[s.index]}` : s.index === current ? "active" : ""}>
          <span className="tick" />
          <div>
            <strong>{s.title}</strong>
            {s.index === current && <p>{s.detail}</p>}
            {!s.verifiable && <em>{s.timer_seconds ? `⏱ ${Math.round(s.timer_seconds / 60)} min timer` : "tap Done when finished"}</em>}
          </div>
        </li>
      ))}
    </ol>
  );
}
