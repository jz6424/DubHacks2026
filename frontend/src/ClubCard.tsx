import type { CSSProperties } from "react";
import type { Card } from "./types";
import { JOIN, TIER, firstUrl, formatDate, hostOf, lastActive, short, STATUS, unconfirmed } from "./util";

interface Props {
  card: Card;
  expanded: boolean;
  onToggle: () => void;
}

/** One club as a swipe card. Front reads in ~10 s; tapping expands the full text and the sources. */
/** How many of the card's key facts the researchers couldn't confirm. */
export function unknownFacts(c: Card): number {
  return [c.commitment.hours_per_week, c.dues, c.meeting_schedule].filter(unconfirmed).length + (c.join_type === "unknown" ? 1 : 0);
}

/** A stable pastel hue per category, so each kind of club gets its own colour band. */
function hueOf(s: string): number {
  let h = 0;
  for (const ch of s.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export function ClubCard({ card: c, expanded, onToggle }: Props) {
  const lastSrc = firstUrl(c.last_active.source);
  const nSources = c.sources.filter((s) => firstUrl(s.url)).length;
  const limited = unknownFacts(c) >= 3;
  return (
    <article className={`club-card status-${c.status}`} aria-label={c.name} style={{ "--h": hueOf(c.category) } as CSSProperties}>
      <header>
        <div className="emoji" aria-hidden>
          {c.category_emoji}
        </div>
        <div className="titles">
          <h3>{c.name}</h3>
          <div className="category">
            {c.category}
            {c.wildcard && <span className="pill wild">🎲 Wildcard</span>}
            {limited && (
              <span className="pill limited" title="Most details couldn't be confirmed from public sources. Tap ❓ to dig deeper.">
                Limited info
              </span>
            )}
          </div>
        </div>
      </header>

      <p className="desc">{expanded ? c.description : short(c.description, 150)}</p>

      <dl className="facts">
        <div>
          <dt>⏱️ Time</dt>
          <dd className={unconfirmed(c.commitment.hours_per_week) ? "dim" : ""}>
            {TIER[c.commitment.level]} · {expanded ? c.commitment.hours_per_week : short(c.commitment.hours_per_week, 40)}
            {c.commitment.estimated && <span className="est"> est.</span>}
          </dd>
        </div>
        <div>
          <dt>💵 Dues</dt>
          <dd className={unconfirmed(c.dues) ? "dim" : ""}>{expanded ? c.dues : short(c.dues, 44)}</dd>
        </div>
        <div>
          <dt>📅 Meets</dt>
          <dd className={unconfirmed(c.meeting_schedule) ? "dim" : ""}>
            {expanded ? c.meeting_schedule : short(c.meeting_schedule, 44)}
          </dd>
        </div>
        <div>
          <dt>🚪 Joining</dt>
          <dd className={c.join_type === "unknown" ? "dim" : ""}>{JOIN[c.join_type]}</dd>
        </div>
      </dl>

      <div className="fit">
        <span className="fit-label">✨ Why it fits you</span>
        <p>{c.fit_reason}</p>
      </div>

      <footer>
        <span className={`status ${STATUS[c.status].tone}`}>
          {lastActive(c)}
          {lastSrc && (
            <>
              {" · "}
              <a href={lastSrc} target="_blank" rel="noreferrer" onPointerDown={(e) => e.stopPropagation()}>
                {hostOf(lastSrc)}
              </a>
            </>
          )}
        </span>
        <button type="button" className="link" onPointerDown={(e) => e.stopPropagation()} onClick={onToggle}>
          {expanded ? "Less" : `More details · ${nSources} source${nSources === 1 ? "" : "s"}`}
        </button>
      </footer>

      {expanded && (
        <div className="expanded" onPointerDown={(e) => e.stopPropagation()}>
          {c.application.steps.length > 0 && (
            <>
              <h4>How to join</h4>
              <ol>
                {c.application.steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </>
          )}
          <p className="small">
            Deadline: <span className={unconfirmed(c.application.deadline) ? "dim" : ""}>{c.application.deadline || "unknown"}</span>
          </p>
          <Links card={c} />
          <Sources card={c} />
        </div>
      )}
    </article>
  );
}

export function Links({ card: c }: { card: Card }) {
  const items = [
    ["Website", firstUrl(c.links.website)],
    ["HuskyLink", firstUrl(c.links.huskylink)],
    ["Instagram", firstUrl(c.links.instagram)],
    ["Apply", firstUrl(c.application.url)],
  ].filter((x): x is [string, string] => !!x[1]);
  if (!items.length) return null;
  return (
    <div className="links">
      {items.map(([label, url]) => (
        <a key={label} className="btn-link" href={url} target="_blank" rel="noreferrer">
          {label} ↗
        </a>
      ))}
    </div>
  );
}

export function Sources({ card: c }: { card: Card }) {
  const list = c.sources
    .map((s) => ({ url: firstUrl(s.url), checked: s.checked }))
    .filter((s): s is { url: string; checked: string } => !!s.url);
  if (!list.length) return <p className="small dim">No sources recorded.</p>;
  return (
    <div className="sources">
      <h4>Sources</h4>
      <ul>
        {list.map((s, i) => (
          <li key={i}>
            <a href={s.url} target="_blank" rel="noreferrer">
              {hostOf(s.url)}
            </a>{" "}
            <span className="muted">checked {formatDate(s.checked)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
