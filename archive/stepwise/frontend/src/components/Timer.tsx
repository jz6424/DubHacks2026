import { useEffect, useState } from "react";
import { fmt } from "../util";

export function Timer({ seconds, onDone }: { seconds: number; onDone: () => void }) {
  const [left, setLeft] = useState(seconds);
  const [running, setRunning] = useState(false);

  useEffect(() => setLeft(seconds), [seconds]);
  useEffect(() => {
    if (!running) return;
    if (left <= 0) { onDone(); return; }
    const id = setTimeout(() => setLeft((l) => l - 1), 1000);
    return () => clearTimeout(id);
  }, [running, left]);

  return (
    <div className="timer">
      <span className="time">{fmt(left)}</span>
      <button className="ghost" onClick={() => setRunning((r) => !r)}>{running ? "Pause" : "Start timer"}</button>
    </div>
  );
}
