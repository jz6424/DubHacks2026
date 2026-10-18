import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { ClubCard, clubImages } from "./ClubCard";
import type { Card, Swipe, SwipeAction } from "./types";

interface Props {
  jobId: string;
  campus: string;
  cards: Card[];
  swipes: Swipe[];
  /** Record a decision on a club already in this student's list. */
  onDecide: (club_id: string, action: SwipeAction) => void;
  /** A catalog club joined the list: add it to the job before deciding on it. */
  onAdded: (card: Card) => void;
  onClose: () => void;
}

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
/** Same club-name key as the backend catalog, so "Advanced Robotics at UW (ARUW)" and "…at the University of Washington (ARUW)" match. */
const clubKey = (name: string) =>
  name
    .toLowerCase()
    .replace(/\(.*?\)/g, " ")
    .replace(/\b(uw|university of washington|the|club|association|society|at)\b/g, " ")
    .replace(/[^a-z0-9]+/g, "");
const LABEL: Record<SwipeAction, string> = { right: "💜 Liked", super: "⭐ Super-liked", left: "Passed" };

/** Rank a club against the query: name start, then a word in the name, then anywhere in name/category/description. */
function rank(c: Card, q: string): number {
  const name = norm(c.name);
  if (name.startsWith(q)) return 0;
  if (name.split(" ").some((w) => w.startsWith(q))) return 1;
  if (name.includes(q)) return 2;
  if (norm(`${c.category} ${c.description}`).includes(q)) return 3;
  return -1;
}

/** Search clubs by name or topic: this student's list first, then the shared catalog; tap one to open its card. */
export function SearchSheet({ jobId, campus, cards, swipes, onDecide, onAdded, onClose }: Props) {
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState<Card[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Card | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const nq = norm(q);

  useEffect(() => input.current?.focus(), []);

  const decided = useMemo(() => new Map(swipes.map((s) => [s.club_id, s.action])), [swipes]);
  const mine = useMemo(() => {
    if (nq.length < 2) return [];
    return cards
      .map((c) => ({ c, r: rank(c, nq) }))
      .filter((x) => x.r >= 0)
      .sort((a, b) => a.r - b.r || a.c.name.localeCompare(b.c.name))
      .map((x) => x.c);
  }, [cards, nq]);

  // The catalog search runs after a short pause in typing; clubs already in the list are shown once, from the list.
  useEffect(() => {
    if (nq.length < 2) {
      setRemote([]);
      return;
    }
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      setBusy(true);
      api
        .searchCatalog(q.trim(), campus, ctl.signal)
        .then((r) => setRemote(r.clubs))
        .catch(() => {
          /* offline or aborted: the list results still show */
        })
        .finally(() => setBusy(false));
    }, 250);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [nq, q, campus]);

  const inList = useMemo(() => new Set(cards.flatMap((c) => [c.club_id, clubKey(c.name)])), [cards]);
  const others = remote.filter((c) => !inList.has(c.club_id) && !inList.has(clubKey(c.name)));

  const decide = async (c: Card, action: SwipeAction) => {
    setError(null);
    let id = c.club_id;
    if (!cards.some((x) => x.club_id === id)) {
      setAdding(true);
      try {
        const added = await api.addFromCatalog(jobId, c.club_id);
        onAdded(added);
        id = added.club_id;
      } catch (e) {
        setError(String((e as Error).message ?? e));
        setAdding(false);
        return;
      }
      setAdding(false);
    }
    onDecide(id, action);
    setOpen(null);
  };

  if (open) {
    const state = decided.get(open.club_id);
    return (
      <div className="sheet-backdrop" onClick={() => setOpen(null)}>
        <div className="sheet profile-sheet" role="dialog" aria-label={open.name} onClick={(e) => e.stopPropagation()}>
          <div className="profile-frame">
            <ClubCard card={open} active />
          </div>
          {state && <p className="muted small center">You {LABEL[state].replace(/^\S+ /, "").toLowerCase()} this club. Choose again to change it.</p>}
          {error && <p className="error-text small">{error}</p>}
          <div className="controls">
            <button type="button" className="round undo" onClick={() => setOpen(null)} title="Back to search" aria-label="Back to search">
              ←
            </button>
            <button type="button" className="round pass" onClick={() => decide(open, "left")} disabled={adding} aria-label="Pass">
              ✕
            </button>
            <button type="button" className="round super" onClick={() => decide(open, "super")} disabled={adding} aria-label="Super-like">
              ★
            </button>
            <button type="button" className="round join" onClick={() => decide(open, "right")} disabled={adding} aria-label="Join">
              ♥
            </button>
          </div>
        </div>
      </div>
    );
  }

  const row = (c: Card, where: "mine" | "catalog") => {
    const { photos, logo } = clubImages(c);
    const thumb = logo || photos[0];
    const state = decided.get(c.club_id);
    return (
      <li key={`${where}-${c.club_id}`}>
        <button type="button" className="result" onClick={() => setOpen(c)}>
          {thumb ? <img className="thumb" src={thumb} alt="" /> : <span className="emoji">{c.category_emoji}</span>}
          <span className="name">
            {c.name}
            <span className="glance">{c.category}</span>
          </span>
          <span className="tag-state">{state ? LABEL[state] : where === "mine" && !c.from_search ? "In your deck" : "New"}</span>
        </button>
      </li>
    );
  };

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet search-sheet" role="dialog" aria-label="Search clubs" onClick={(e) => e.stopPropagation()}>
        <div className="search-bar">
          <span aria-hidden>🔍</span>
          <input
            ref={input}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search clubs by name or topic"
            aria-label="Search clubs"
            enterKeyHint="search"
          />
          <button type="button" className="ghost small" onClick={onClose}>
            Done
          </button>
        </div>
        {nq.length < 2 ? (
          <p className="muted small">Type a club's name (like "robotics" or "DubHacks") to pull up its card.</p>
        ) : (
          <>
            {mine.length > 0 && (
              <>
                <h4>In your list</h4>
                <ul className="results">{mine.map((c) => row(c, "mine"))}</ul>
              </>
            )}
            {others.length > 0 && (
              <>
                <h4>More UW clubs</h4>
                <ul className="results">{others.map((c) => row(c, "catalog"))}</ul>
              </>
            )}
            {busy && <p className="muted small">Searching all clubs…</p>}
            {!busy && !mine.length && !others.length && <p className="muted small">No clubs match "{q.trim()}" yet.</p>}
          </>
        )}
      </div>
    </div>
  );
}
