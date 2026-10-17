import { useEffect, useState } from "react";
import { ingest, listPlans } from "../api";
import type { Plan } from "../types";

export function IngestScreen({ onReady }: { onReady: (p: Plan) => void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<Plan[]>([]);
  useEffect(() => { listPlans().then(setRecent).catch(() => {}); }, []);
  // TODO: replace spinner with staged progress (fetching → reading steps → watching video → writing checks)
  //       and stream steps into a preview list as they're discovered
  return (
    <div className="ingest">
      <h1>What are we making?</h1>
      <form onSubmit={async e => { e.preventDefault(); setBusy(true); onReady(await ingest(url)); }}>
        <input value={url} onChange={e => setUrl(e.target.value)} placeholder="Paste a YouTube link or recipe URL" />
        <button disabled={busy || !url}>{busy ? "Watching the tutorial…" : "Start"}</button>
      </form>
      {recent.length > 0 && <section><h3>Ready to go</h3>
        {recent.map(p => <button key={p.id} className="card" onClick={() => fetch(`/api/plans/${p.id}`).then(r => r.json()).then(onReady)}>{p.title}</button>)}
      </section>}
    </div>
  );
}
