import { useState, type CSSProperties } from "react";
import type { Card } from "./types";
import { JOIN, TIER, firstUrl, formatDate, hostOf, lastActive, primaryLink, sortedSources, STATUS, unconfirmed } from "./util";

interface Props {
  card: Card;
  /** The top card: its photos can be flipped through and the card scrolls to show the details. */
  active: boolean;
}

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

/** Photos (events, people, builds) and logo. Older catalog entries only have `image`, which is usually a logo. */
export function clubImages(c: Card): { photos: string[]; logo: string } {
  const photos = (c.photos ?? []).filter(Boolean);
  const logo = c.logo ?? (c.photos === undefined ? (c.image ?? "") : "");
  return { photos, logo };
}

/**
 * One club as a Tinder-style profile: photos fill the card (tap left/right to flip through them), with the club's
 * logo as a small badge. Scrolling up reveals the details. Clubs with no usable image open straight on the text.
 */
export function ClubCard({ card: c, active }: Props) {
  const link = primaryLink(c);
  const limited = unknownFacts(c) >= 3;
  const { photos, logo } = clubImages(c);
  // Images show only once they've loaded, so a missing or broken one never leaves an empty frame.
  const [ok, setOk] = useState<Set<string>>(new Set());
  const [bad, setBad] = useState<Set<string>>(new Set());
  const mark = (set: typeof setOk, url: string) => set((s) => (s.has(url) ? s : new Set(s).add(url)));
  const shown = photos.filter((u) => ok.has(u) && !bad.has(u));
  const logoOk = !!logo && ok.has(logo) && !bad.has(logo);
  const hero = shown.length ? shown : logoOk ? [logo] : [];
  const logoOnly = !shown.length && logoOk;
  const [i, setI] = useState(0);
  const at = Math.min(i, Math.max(0, hero.length - 1));
  const flip = (e: React.MouseEvent) => {
    if (!active || hero.length < 2) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const back = e.clientX - r.left < r.width / 3;
    setI((n) => Math.max(0, Math.min(hero.length - 1, Math.min(n, hero.length - 1) + (back ? -1 : 1))));
  };

  const titles = (
    <div className="titles">
      <h3>{c.name}</h3>
      <div className="category">
        {hero.length > 0 && <span aria-hidden>{c.category_emoji} </span>}
        {c.category}
        {c.wildcard && <span className="pill wild">🎲 Wildcard</span>}
        {limited && (
          <span className="pill limited" title="Most details couldn't be confirmed from public sources. Tap ❓ to dig deeper.">
            Limited info
          </span>
        )}
      </div>
    </div>
  );

  return (
    <article
      className={`club-card status-${c.status} ${hero.length ? "has-hero" : ""} ${active ? "active" : ""}`}
      aria-label={c.name}
      style={{ "--h": hueOf(c.category) } as CSSProperties}
    >
      {/* preload every image; each one joins the profile when it arrives */}
      {[...photos, logo].filter((u) => u && !ok.has(u) && !bad.has(u)).map((u) => (
        <img key={u} src={u} alt="" hidden onLoad={() => mark(setOk, u)} onError={() => mark(setBad, u)} />
      ))}

      {hero.length > 0 ? (
        <div className={`hero ${logoOnly ? "logo-only" : ""}`} onClick={flip}>
          <img className="fill" src={hero[at]} alt="" aria-hidden draggable={false} />
          <img className="main" src={hero[at]} alt="" draggable={false} />
          {hero.length > 1 && (
            <div className="bars" aria-hidden>
              {hero.map((u, k) => (
                <span key={u} className={k === at ? "on" : ""} />
              ))}
            </div>
          )}
          <div className="caption">
            {logoOk && !logoOnly && <img className="badge" src={logo} alt="" draggable={false} />}
            {titles}
            <div className="peek" aria-hidden>
              ⌃ Scroll for details
            </div>
          </div>
        </div>
      ) : (
        <header>
          <div className="emoji" aria-hidden>
            {c.category_emoji}
          </div>
          {titles}
        </header>
      )}

      <div className="info">
        <p className="desc">{c.description}</p>

        <dl className="facts">
          <div>
            <dt>⏱️ Time</dt>
            <dd className={unconfirmed(c.commitment.hours_per_week) ? "dim" : ""}>
              {TIER[c.commitment.level]} · {c.commitment.hours_per_week}
              {c.commitment.estimated && <span className="est"> est.</span>}
            </dd>
          </div>
          <div>
            <dt>💵 Dues</dt>
            <dd className={unconfirmed(c.dues) ? "dim" : ""}>{c.dues}</dd>
          </div>
          <div>
            <dt>📅 Meets</dt>
            <dd className={unconfirmed(c.meeting_schedule) ? "dim" : ""}>{c.meeting_schedule}</dd>
          </div>
          <div>
            <dt>🚪 Joining</dt>
            <dd className={c.join_type === "unknown" ? "dim" : ""}>{JOIN[c.join_type]}</dd>
          </div>
        </dl>

        <p className={`status ${STATUS[c.status].tone}`}>
          {lastActive(c)}
          {link && (
            <>
              {" · "}
              <a href={link.url} target="_blank" rel="noreferrer">
                {link.label}
              </a>
            </>
          )}
        </p>

        {c.application.steps.length > 0 && (
          <>
            <h4>How to join</h4>
            <ol>
              {c.application.steps.map((s, k) => (
                <li key={k}>{s}</li>
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
    </article>
  );
}

export function Links({ card: c, apply = true }: { card: Card; apply?: boolean }) {
  const items = [
    ["Website", firstUrl(c.links.website)],
    ["Instagram", firstUrl(c.links.instagram)],
    ["HuskyLink", firstUrl(c.links.huskylink)],
    ["Apply", apply ? firstUrl(c.application.url) : null],
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
  const latest = firstUrl(c.last_active.source);
  const list = sortedSources(c);
  // the page the "last active" date came from always shows, even if it wasn't listed as a source
  if (latest && !list.some((s) => s.url === latest)) list.push({ url: latest, checked: "" });
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
            {s.checked && <span className="muted">checked {formatDate(s.checked)}</span>}
            {s.url === latest && c.last_active.date && !/unknown/i.test(c.last_active.date) && (
              <span className="muted"> · latest activity {formatDate(c.last_active.date)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
