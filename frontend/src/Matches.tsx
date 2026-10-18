import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { Md } from "./Md";
import { Links, Sources } from "./ClubCard";
import type { Card, Profile, Results, Swipe } from "./types";
import { JOIN, TIER, firstUrl, short, unconfirmed } from "./util";

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
  const [more, setMore] = useState<Set<string>>(new Set());
  const [showPlan, setShowPlan] = useState(false);
  const toggleMore = (id: string) =>
    setMore((m) => {
      const n = new Set(m);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
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
        <p className="muted">Checking deadlines and application links for {matchSwipes.length} clubs.</p>
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
  const plan = results.judged.action_plan;

  return (
    <section className="screen matches">
      <h2>
        Your matches <span className="count">{matched.length}</span>
      </h2>

      <div className="match-list">
        {matched.map((c) => {
          const isOpen = open === c.club_id;
          return (
            <article key={c.club_id} className={`match ${isOpen ? "open" : ""}`}>
              <button type="button" className="match-head" onClick={() => setOpen(isOpen ? null : c.club_id)} aria-expanded={isOpen}>
                <span className="emoji">{c.category_emoji}</span>
                <span className="name">
                  {c.name}
                  {supers.has(c.club_id) && <span className="pill super">⭐</span>}
                  <span className="glance">{glance(c)}</span>
                </span>
                <span className="chev">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <MatchBody
                  card={c}
                  tips={judged.get(c.club_id)?.good_to_know ?? []}
                  more={more.has(c.club_id)}
                  onMore={() => toggleMore(c.club_id)}
                  onDraft={() => setDraftFor(c)}
                />
              )}
            </article>
          );
        })}
      </div>

      {plan.length > 0 && (
        <div className="plan">
          <h3>Next steps</h3>
          <ol>
            {(showPlan ? plan : plan.slice(0, 3)).map((a, i) => (
              <li key={i}>
                <span className="when">{a.when}</span> <Md text={a.step} />
              </li>
            ))}
          </ol>
          {plan.length > 3 && (
            <button type="button" className="link" onClick={() => setShowPlan(!showPlan)}>
              {showPlan ? "Show less" : `Show all ${plan.length} steps`}
            </button>
          )}
        </div>
      )}

      <p className={`hours-line small ${h.over ? "over" : ""}`}>
        ⏱️ ~{h.total} hrs/wk total{h.unknown > 0 && ` (+${h.unknown} unknown)`}
        {h.limit !== null && profile.commitment && (h.over ? ` · over your ${COMMIT_LABEL[profile.commitment]} target` : " · within your target ✓")}
      </p>

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

/** The cost as one ledger line: the leading fact, before any notes in brackets or after a semicolon. */
function ledgerCost(d: string): string | null {
  if (!d || /^\s*(couldn.?t confirm|unknown|not listed)/i.test(d)) return null;
  return short(d.split(/\s*[(;]/)[0].replace(/[.,]\s*$/, ""), 48);
}

const known = (s: string | undefined | null) => !!s && !unconfirmed(s) && !/^unknown$/i.test(s.trim());

/** One line under the club name: how you join and the deadline, when we know them. */
function glance(c: Card): string {
  const parts = [];
  if (c.join_type !== "unknown") parts.push(JOIN[c.join_type]);
  if (known(c.application.deadline)) parts.push(`due ${c.application.deadline}`);
  return parts.join(" · ");
}

function MatchBody({ card: c, tips, more, onMore, onDraft }: { card: Card; tips: string[]; more: boolean; onMore: () => void; onDraft: () => void }) {
  const site = firstUrl(c.links.website) ?? firstUrl(c.links.instagram) ?? firstUrl(c.links.huskylink);
  const apply = firstUrl(c.application.url);
  const joinKnown = c.join_type !== "unknown" || c.application.steps.length > 0 || !!apply;
  const deadline = known(c.application.deadline) ? c.application.deadline : null;
  const cost = ledgerCost(c.dues);
  return (
    <div className="match-body">
      <div className="block">
        <h4>🚪 How to join</h4>
        {joinKnown ? (
          <>
            <p className="big-line">{c.join_type !== "unknown" ? JOIN[c.join_type] : "Ask the club how to join"}</p>
            <p className="small">{deadline ? <strong>Deadline: {deadline}</strong> : <span className="muted">No deadline posted</span>}</p>
          </>
        ) : (
          <p className="muted">Couldn't confirm. Check their website for how to join.</p>
        )}
        {(apply || (!joinKnown && site)) && (
          <a className="btn-link apply" href={apply ?? site!} target="_blank" rel="noreferrer">
            {apply ? "Apply ↗" : "Visit their site ↗"}
          </a>
        )}
      </div>

      <div className="block">
        <h4>⏱️ Time commitment</h4>
        <p className="big-line">
          {TIER[c.commitment.level]}
          {known(c.commitment.hours_per_week) && <span className="muted"> · {short(c.commitment.hours_per_week, 30)}</span>}
        </p>
      </div>

      <div className="block ledger">
        <h4>💵 Cost</h4>
        <span className={cost ? "" : "muted"}>{cost ?? "Not listed"}</span>
      </div>

      <Links card={c} apply={false} />

      <button type="button" className="link more-toggle" onClick={onMore} aria-expanded={more}>
        {more ? "Hide more info ▴" : "More info ▾"}
      </button>
      {more && (
        <div className="more-info">
          {c.application.steps.length > 0 && (
            <>
              <h5>Steps</h5>
              <ol>
                {c.application.steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </>
          )}
          {known(c.meeting_schedule) && (
            <>
              <h5>Meets</h5>
              <p>{c.meeting_schedule}</p>
            </>
          )}
          {c.dues && c.dues !== cost && !/^couldn.?t confirm$/i.test(c.dues.trim()) && (
            <>
              <h5>Cost details</h5>
              <p>{c.dues}</p>
            </>
          )}
          {tips.length > 0 && (
            <>
              <h5>Good to know</h5>
              <ul>
                {tips.map((g, i) => (
                  <li key={i}>
                    <Md text={g} />
                  </li>
                ))}
              </ul>
            </>
          )}
          <Sources card={c} />
          <button type="button" className="ghost small" onClick={onDraft}>
            ✉️ Draft a message to them
          </button>
        </div>
      )}
    </div>
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
