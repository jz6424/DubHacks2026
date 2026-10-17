import { useEffect, useState } from "react";
import { getPlan } from "./api";
import { Home } from "./components/Home";
import { Session } from "./components/Session";
import type { Plan } from "./types";

/** Tiny hash router: #/ (home) and #/p/<planId> (session). */
export default function App() {
  const [hash, setHash] = useState(location.hash);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const planId = hash.match(/^#\/p\/(\w+)/)?.[1];
  useEffect(() => {
    setPlan(null);
    setError(null);
    if (planId) getPlan(planId).then(setPlan).catch((e) => setError(e.message));
  }, [planId]);

  const goHome = () => { location.hash = "/"; };
  if (!planId) return <Home onOpen={(id) => { location.hash = `/p/${id}`; }} />;
  if (error) return <div className="center"><p>Couldn't load that tutorial.</p><button onClick={goHome}>Back</button></div>;
  if (!plan) return <div className="center muted">Loading…</div>;
  return <Session key={plan.id} plan={plan} onExit={goHome} />;
}
