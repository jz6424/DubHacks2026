import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ClubCard, clubImages } from "./ClubCard";
import type { Campus, Card } from "./types";

const CAMPUSES: { value: Campus; label: string }[] = [
  { value: "seattle", label: "Seattle" },
  { value: "bothell", label: "Bothell" },
  { value: "tacoma", label: "Tacoma" },
];

/**
 * Home-page club lookup: search the shared catalog by name or topic and read a club's profile (photos and details).
 * Browsing only: no swiping. `onActive` tells the home page to step aside while results are showing.
 */
export function ClubFinder({ onActive }: { onActive: (active: boolean) => void }) {
  const [q, setQ] = useState("");
  const [campus, setCampus] = useState<Campus>("seattle");
  const [clubs, setClubs] = useState<Card[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<Card | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const query = q.trim();
  const active = query.length >= 2;

  useEffect(() => onActive(active), [active, onActive]);

  useEffect(() => {
    if (!active) {
      setClubs([]);
      return;
    }
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      setBusy(true);
      setFailed(false);
      api
        .searchCatalog(query, campus, ctl.signal)
        .then((r) => setClubs(r.clubs))
        .catch((e) => (e as Error).name !== "AbortError" && setFailed(true))
        .finally(() => setBusy(false));
    }, 250);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [query, campus, active]);

  // Back from a profile (or the phone's back gesture, via Escape on desktop) returns to the results.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const home = () => {
    setOpen(null);
    setQ("");
    input.current?.blur();
  };

  return (
    <div className="finder">
      <form
        className="search-bar"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (clubs.length === 1) setOpen(clubs[0]); // one match: go straight to its profile
        }}
      >
        <span aria-hidden>🔍</span>
        <input
          ref={input}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Look up a club by name"
          aria-label="Look up a club by name"
          enterKeyHint="search"
        />
        {active && (
          <button type="button" className="ghost small" onClick={home}>
            Home
          </button>
        )}
      </form>

      {active && (
        <div className="finder-results">
          <div className="chips campus-chips" role="radiogroup" aria-label="Campus">
            {CAMPUSES.map((c) => (
              <button
                key={c.value}
                type="button"
                role="radio"
                aria-checked={campus === c.value}
                className={`chip small ${campus === c.value ? "on" : ""}`}
                onClick={() => setCampus(c.value)}
              >
                {c.label}
              </button>
            ))}
          </div>
          {clubs.length > 0 && (
            <ul className="results">
              {clubs.map((c) => {
                const { photos, logo } = clubImages(c);
                const thumb = logo || photos[0];
                return (
                  <li key={c.club_id}>
                    <button type="button" className="result" onClick={() => setOpen(c)}>
                      {thumb ? <img className="thumb" src={thumb} alt="" /> : <span className="emoji">{c.category_emoji}</span>}
                      <span className="name">
                        {c.name}
                        <span className="glance">{c.category}</span>
                      </span>
                      <span className="chev" aria-hidden>
                        ›
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {busy && !clubs.length && <p className="muted small">Searching…</p>}
          {failed && <p className="error-text small">Couldn't search right now. Try again in a moment.</p>}
          {!busy && !failed && !clubs.length && (
            <p className="muted small">
              No clubs match "{query}" yet. We only list clubs we've verified; "Get started" researches clubs for you.
            </p>
          )}
          <button type="button" className="ghost" onClick={home}>
            ← Back to home
          </button>
        </div>
      )}

      {open && (
        <div className="finder-profile" role="dialog" aria-label={open.name}>
          <div className="finder-nav">
            <button type="button" className="ghost small" onClick={() => setOpen(null)}>
              ← {clubs.length > 1 ? "Results" : "Back"}
            </button>
            <button type="button" className="ghost small" onClick={home}>
              Home
            </button>
          </div>
          <div className="profile-frame">
            <ClubCard card={open} active />
          </div>
        </div>
      )}
    </div>
  );
}
