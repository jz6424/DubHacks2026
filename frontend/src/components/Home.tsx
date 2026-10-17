import { useEffect, useState } from "react";
import { getJob, listPlans, startIngest } from "../api";
import type { JobStage, PlanSummary } from "../types";

const STAGES: { key: JobStage; label: string }[] = [
  { key: "fetching", label: "Fetching the tutorial" },
  { key: "watching", label: "Watching the video" },
  { key: "finishing", label: "Writing your checklist" },
];

export function Home({ onOpen }: { onOpen: (planId: string) => void }) {
  const [url, setUrl] = useState("");
  const [stage, setStage] = useState<JobStage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<PlanSummary[]>([]);

  useEffect(() => {
    listPlans().then(setRecent).catch(() => {});
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return setError("Paste a link first");
    setError(null);
    try {
      let job = await startIngest(url.trim());
      setStage(job.stage);
      while (job.stage !== "ready" && job.stage !== "error") {
        await new Promise((r) => setTimeout(r, 1200));
        job = await getJob(job.job_id);
        setStage(job.stage);
      }
      if (job.stage === "error" || !job.plan_id) throw new Error(job.error ?? "Something went wrong");
      onOpen(job.plan_id);
    } catch (err: any) {
      setStage(null);
      setError(err.message);
    }
  }

  const busy = stage !== null;
  const activeIdx = STAGES.findIndex((s) => s.key === (stage === "reading" ? "watching" : stage));

  return (
    <div className="home">
      <div className="brand"><span className="logo">✓</span> Stepwise</div>
      <h1>What are we making?</h1>
      <p className="lede">
        Paste a video or recipe link. Stepwise turns it into a checklist, then watches you work and
        checks off each step, with the matching part of the video ready when you need it.
      </p>

      <form onSubmit={submit} className="url-form">
        <input
          value={url}
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          placeholder="https://youtube.com/watch?v=… or a recipe page"
          disabled={busy}
          autoFocus
        />
        <button className="primary" disabled={busy}>{busy ? "Working…" : "Start"}</button>
      </form>
      {error && <p className="form-error">{error}</p>}

      {busy && (
        <ol className="stages">
          {STAGES.map((s, i) => (
            <li key={s.key} className={i < activeIdx ? "done" : i === activeIdx ? "active" : ""}>
              <span className="dot" /> {stage === "reading" && s.key === "watching" ? "Reading the recipe" : s.label}
            </li>
          ))}
        </ol>
      )}

      {!busy && recent.length > 0 && (
        <section className="recent">
          <h3>Ready to go</h3>
          <div className="cards">
            {recent.map((p) => (
              <button key={p.id} className="plan-card" onClick={() => onOpen(p.id)}>
                <span className="kind">{p.kind === "video" ? "▶ Video" : "☰ Recipe"}</span>
                <strong>{p.title}</strong>
                <span className="muted">{p.steps} steps</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
