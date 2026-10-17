import { useState } from "react";
import type { Plan } from "./types";
import { IngestScreen } from "./components/IngestScreen";
import { SessionScreen } from "./components/SessionScreen";
import "./styles.css";

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null);
  // TODO: a "plan review" screen between ingest and session — user can edit/merge steps, preview segments
  return plan ? <SessionScreen plan={plan} /> : <IngestScreen onReady={setPlan} />;
}
