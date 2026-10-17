import { useEffect, useRef, useState } from "react";
import { sessionSocket } from "../api";
import type { Box, Plan, SessionEvent } from "../types";

export function useSession(plan: Plan) {
  const ws = useRef<WebSocket>();
  const [current, setCurrent] = useState(0);
  const [done, setDone] = useState<Record<number, string>>({});
  const [verifying, setVerifying] = useState(false);
  const [confidence, setConfidence] = useState(0);
  const [hint, setHint] = useState("");
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [finished, setFinished] = useState(false);

  useEffect(() => {
    const s = (ws.current = sessionSocket(plan.id));
    s.onmessage = m => {
      const e: SessionEvent = JSON.parse(m.data);
      switch (e.type) {
        case "step_active": setCurrent(e.step); setVerifying(false); setHint(""); setBoxes([]); break;
        case "verifying": setVerifying(true); break;
        case "step_done": setDone(d => ({ ...d, [e.step]: e.how })); break;   // UI: check animation + chime
        case "check": setConfidence(e.confidence); setBoxes(e.boxes ?? []); if (!e.done) setVerifying(false); break;
        case "hint": setHint(e.text); break;
        case "finished": setFinished(true); break;
      }
    };
    return () => s.close();
  }, [plan.id]);

  const sendFrame = (b: Blob) => ws.current?.readyState === 1 && ws.current.send(b);
  const act = (action: "next" | "skip" | "back") => ws.current?.send(JSON.stringify({ action }));
  return { current, done, verifying, confidence, hint, boxes, finished, sendFrame, act };
}
