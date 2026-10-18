import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { Md } from "./Md";
import { Links, Sources } from "./ClubCard";
import type { Card, Profile, Results, Swipe } from "./types";
import { JOIN, TIER, unconfirmed } from "./util";

interface Props {
  jobId: string;
  cards: Card[];
  swipes: Swipe[];
  profile: Profile;
  onKeepSwiping: () => void;
  onStartOver: () => void;
}

const COMMIT_LABEL: Record<string, string> = {
  casual: "under 2 hrs/wk",
  regular: "2–5 hrs/wk",
  committed: "5–10 hrs/wk",
  all_in: "10+ hrs/wk",
};

export function Matches({ jobId, cards, swipes, profile, onKeepSwiping, onStartOver }: Props) {
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [draftFor, setDraftFor] = useState<Card | null>(null);
  const byId = useMemo(() => new Map(cards.map((c) => [c.club_id, c])), [cards]);
  const matchSwipes = useMemo(() => swipes.filter((s) => s.action !== "left"), [swipes]);
  const supers = useMemo(() => new Set(swipes.filter((s) => s.action === "super").map((s) => s.club_id)), [swipes]);

  useEffect(() => {
    let live = true;
    setResults(null);
    setError(null);
    api
      .results(jobId, matchSwipes)
      .then((r) => {
        if (!live) return;
        setResults(r);
        setOpen(r.order[0] ?? null);
      })
      .catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [jobId, matchSwipes]);

  if (error)
    return (
      <section className="screen matches">
        <h2>Your matches</h2>
        <p className="error-text">Couldn't build your results: {error}</p>
        <button type="button" className="primary" onClick={onKeepSwiping}>
          Back to swiping
        </button>
      </section>
    );

  if (!results)
    return (
      <section className="screen matches center">
        <div className="spinner big" aria-hidden />
        <h2>Putting your plan together…</h2>
        <p className="muted">Checking deadlines, time and your availability for {matchSwipes.length} clubs.</p>
      </section>
    );

  if (!results.order.length)
    return (
      <section className="screen matches center">
        <h2>No matches yet</h2>
        <p className="muted">Swipe right (or ⭐) on clubs you'd like to join and they'll show up here.</p>
        <button type="button" className="primary" onClick={onKeepSwiping}>
          Back to swiping
        </button>
      </section>
    );

  const judged = new Map(results.judged.clubs.map((c) => [c.club_id, c]));
  const matched = results.order.map((id) => byId.get(id)).filter((c): c is Card => !!c);
  const h = results.hours;

  return (
    <section className="screen matches">
      <h2>
        Your matches <span className="count">{matched.length}</span>
      </h2>

      <div className="match-list">
        {matched.map((c) => {
          const j = judged.get(c.club_id);
          const isOpen = open === c.club_id;
          return (
            <article key={c.club_id} className={`match ${isOpen ? "open" : ""}`}>
              <button type="button" className="match-head" onClick={() => setOpen(isOpen ? null : c.club_id)} aria-expanded={isOpen}>
                <span className="emoji">{c.category_emoji}</span>
                <span className="name">
                  {c.name}
                  {supers.has(c.club_id) && <span className="pill super">⭐ Super-like</span>}
                </span>
                <span className="chev">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <div className="match-body">
                  <h4>🚪 How to join</h4>
                  <p>
                    {JOIN[c.join_type]} · Deadline:{" "}
                    <span className={unconfirmed(c.application.deadline) ? "dim" : ""}>{c.application.deadline || "unknown"}</span>
                  </p>
                  {c.application.steps.length > 0 && (
                    <ol>
                      {c.application.steps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                  )}

                  <h4>⏱️ Time</h4>
                  <p>
                    {TIER[c.commitment.level]} · {c.commitment.hours_per_week}
                    {c.commitment.estimated && <span className="est"> (estimated)</span>}
                  </p>
                  <p className={unconfirmed(c.meeting_schedule) ? "dim" : ""}>📅 {c.meeting_schedule}</p>
                  {j && j.availability_conflicts && !/^none\.?$/i.test(j.availability_conflicts.trim()) && (
                    <p className="warn-text">⚠️ {j.availability_conflicts}</p>
                  )}

                  <h4>💵 Cost</h4>
                  <p className={unconfirmed(c.dues) ? "dim" : ""}>{c.dues}</p>

                  <h4>📇 Contact</h4>
                  <Links card={c} />

                  {j && j.good_to_know.length > 0 && (
                    <>
                      <h4>💡 Good to know</h4>
                      <ul>
                        {j.good_to_know.map((g, i) => (
                          <li key={i}>
                            <Md text={g} />
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  <Sources card={c} />
                  <button type="button" className="ghost" onClick={() => setDraftFor(c)}>
                    ✉️ Draft a message to them
                  </button>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {results.judged.action_plan.length > 0 && (
        <div className="plan">
          <h3>Your action plan</h3>
          <ol>
            {results.judged.action_plan.map((a, i) => (
              <li key={i}>
                <span className="when">{a.when}</span> <Md text={a.step} />
                {byId.get(a.club_id) && <span className="muted"> · {byId.get(a.club_id)!.name}</span>}
              </li>
            ))}
          </ol>
          <p className="small muted">Deadlines change. Confirm them with each club directly.</p>
        </div>
      )}

      <div className={`hours ${h.over ? "over" : ""}`}>
        <div>
          <strong>~{h.total} hrs/wk</strong> across your matches
          {h.unknown > 0 && <span className="muted"> (+{h.unknown} with unknown hours)</span>}
        </div>
        {h.limit !== null && profile.commitment && (
          <div className="small">
            {h.over
              ? `⚠️ That's more than your ${TIER[profile.commitment]} target (${COMMIT_LABEL[profile.commitment]}). Consider starting with your top 1–2.`
              : `✓ Within your ${TIER[profile.commitment]} target (${COMMIT_LABEL[profile.commitment]}).`}
          </div>
        )}
      </div>

      <div className="end-actions">
        <button type="button" className="ghost" onClick={onKeepSwiping}>
          ← Keep swiping
        </button>
        <button type="button" className="ghost" onClick={onStartOver}>
          Start over
        </button>
      </div>

      {draftFor && <DraftSheet jobId={jobId} card={draftFor} onClose={() => setDraftFor(null)} />}
    </section>
  );
}

function DraftSheet({ jobId, card, onClose }: { jobId: string; card: Card; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .draft(jobId, card.club_id)
      .then((r) => live && setText(r.text))
      .catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [jobId, card.club_id]);
  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  };
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label={`Message to ${card.name}`} onClick={(e) => e.stopPropagation()}>
        <h3>✉️ Message to {card.name}</h3>
        {!text && !error && (
          <div className="loading">
            <div className="spinner" aria-hidden />
            <span className="muted">Writing a draft…</span>
          </div>
        )}
        {error && <p className="error-text">Couldn't draft a message: {error}</p>}
        {text && <textarea className="text draft" rows={8} value={text} onChange={(e) => setText(e.target.value)} />}
        <div className="sheet-actions">
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
          <button type="button" className="primary" onClick={copy} disabled={!text}>
            {copied ? "Copied ✓" : "Copy"}
          </button>
        </div>
      </div>
    </div>
  );
}
