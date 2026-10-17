import type { DoneHow, Step } from "../types";

interface Props {
  steps: Step[];
  current: number;
  done: Record<number, DoneHow>;
  onJump: (i: number) => void;
}

export function Checklist({ steps, current, done, onJump }: Props) {
  return (
    <ol className="checklist">
      {steps.map((s) => {
        const how = done[s.index];
        const cls = how ? `done ${how}` : s.index === current ? "active" : "";
        return (
          <li key={s.index} className={cls}>
            <button onClick={() => onJump(s.index)}>
              <span className="tick">{how === "skipped" ? "–" : how ? "✓" : s.index + 1}</span>
              <span className="label">
                {s.title}
                {!s.verifiable && <em> · manual</em>}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
