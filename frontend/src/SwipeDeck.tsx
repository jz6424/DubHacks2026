import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ClubCard } from "./ClubCard";
import { MoreSheet } from "./MoreSheet";
import { SearchSheet } from "./SearchSheet";
import type { Card, Swipe, SwipeAction } from "./types";
import { store, unconfirmed } from "./util";

interface Props {
  jobId: string;
  cards: Card[];
  researching: boolean;
  lastAction: string | null;
  swipes: Swipe[];
  onSwipes: (s: Swipe[]) => void;
  penalties: Penalty[];
  onPenalties: (p: Penalty[]) => void;
  onSeeMatches: () => void;
  campus: string;
  /** A club found through search joined this student's list. */
  onAddCard: (c: Card) => void;
}

/** A "show fewer of these" rule the student chose after a run of left swipes. */
export interface Penalty {
  kind: "time" | "cost" | "category" | "selective";
  levels?: string[];
  categories?: string[];
}

const LEVEL_ORDER = ["casual", "regular", "committed", "all_in"];
const THRESHOLD = 110;
const CHECKPOINT = 10;
const WHY_AFTER = 5; // passes in a row before asking what's off

const matches = (p: Penalty, c: Card): boolean => {
  switch (p.kind) {
    case "time": {
      const min = Math.min(...(p.levels ?? []).map((l) => LEVEL_ORDER.indexOf(l)));
      return LEVEL_ORDER.indexOf(c.commitment.level) >= min;
    }
    case "cost":
      return !/free|no (membership |)dues|no dues|\$0|no fee/i.test(c.dues);
    case "category":
      return (p.categories ?? []).some((k) => c.category.toLowerCase().includes(k) || k.includes(c.category.toLowerCase()));
    case "selective":
      return ["application", "tryout", "interview"].includes(c.join_type);
  }
};

const REASONS: { kind: Penalty["kind"] | "other"; label: string; toast: string }[] = [
  { kind: "time", label: "⏱️ Too much time", toast: "showing fewer time-heavy clubs" },
  { kind: "cost", label: "💵 Too expensive", toast: "showing clubs without dues first" },
  { kind: "category", label: "🙅 Not my kind of thing", toast: "showing fewer clubs like those" },
  { kind: "selective", label: "🚪 Too selective", toast: "showing open-membership clubs first" },
  { kind: "other", label: "🤷 Just not feeling them", toast: "" },
];

/** "full" when dues, hours and meeting times are all confirmed; the backend sends it, older cards are worked out here. */
const detailOf = (c: Card): "full" | "partial" =>
  c.detail ?? ([c.dues, c.commitment.hours_per_week, c.meeting_schedule].some((f) => !f?.trim() || unconfirmed(f)) ? "partial" : "full");

const categoryKey = (c: Card) => c.category.toLowerCase().split(/[\/&,–-]/)[0].trim();

export function SwipeDeck({ jobId, cards, researching, lastAction, swipes, onSwipes, penalties, onPenalties, onSeeMatches, campus, onAddCard }: Props) {
  const [searching, setSearching] = useState(false);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [flying, setFlying] = useState<{ id: string; action: SwipeAction } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [askWhy, setAskWhy] = useState(false);
  const [checkpoint, setCheckpoint] = useState(false);
  const [moreFor, setMoreFor] = useState<Card | null>(null);
  // a press on the card: undecided until it moves; sideways becomes a swipe, up/down is left to the card's scroll
  const start = useRef<{ x: number; y: number; id: number; mode: "?" | "drag" | "scroll" } | null>(null);
  const dragged = useRef(false);
  const slot = useRef<HTMLDivElement>(null);
  const toastTimer = useRef<number | undefined>();

  const swiped = useMemo(() => new Set(swipes.map((s) => s.club_id)), [swipes]);
  // Remaining cards in arrival order, with "show fewer of these" rules pushing matches down the deck.
  // Clubs with real photos come first, then logo-only, then text-only. The card on top stays pinned while it's unswiped:
  // photos arrive in the background, and a re-sort mid-drag would pull the card out from under the student's finger.
  const pinned = useRef<string | null>(null);
  const queue = useMemo(() => {
    // clubs someone else pulled in through search stay out of the deck (students with the same answers share a list)
    const rest = cards.map((c, i) => ({ c, i })).filter(({ c }) => !swiped.has(c.club_id) && !c.from_search);
    const score = (c: Card) => penalties.filter((p) => matches(p, c)).length;
    // Order: images + full details, images + partial details, then no images (full before partial).
    // Among cards with images, real photos beat logo-only.
    const media = (c: Card) => (c.photos?.length ? 0 : c.logo || (c.photos === undefined && c.image) ? 1 : 2);
    const hasImage = (c: Card) => (media(c) < 2 ? 0 : 1);
    const partial = (c: Card) => (detailOf(c) === "full" ? 0 : 1);
    const sorted = rest
      .sort(
        (a, b) =>
          score(a.c) - score(b.c) ||
          hasImage(a.c) - hasImage(b.c) ||
          partial(a.c) - partial(b.c) ||
          media(a.c) - media(b.c) ||
          a.i - b.i,
      )
      .map(({ c }) => c);
    const k = sorted.findIndex((c) => c.club_id === pinned.current);
    if (k > 0) sorted.unshift(...sorted.splice(k, 1));
    return sorted;
  }, [cards, swiped, penalties]);
  const top = queue[0];
  useEffect(() => {
    pinned.current = top?.club_id ?? null;
  }, [top]);
  const next = queue[1];
  const fly = flying && top && flying.id === top.club_id ? flying.action : null;

  // Research may still be running while the student swipes: say when new clubs land in the deck.
  const seen = useRef(cards.length);

  const say = useCallback((text: string) => {
    setToast(text);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1800);
  }, []);

  useEffect(() => {
    const added = cards.length - seen.current;
    seen.current = cards.length;
    if (added > 0 && swipes.length > 0) say(`+${added} new club${added === 1 ? "" : "s"} added to your deck`);
  }, [cards.length, swipes.length, say]);

  const decide = useCallback(
    (action: SwipeAction) => {
      if (!top || flying) return;
      try {
        navigator.vibrate?.(action === "super" ? [12, 40, 12] : 12);
      } catch {
        /* no haptics */
      }
      setFlying({ id: top.club_id, action });
      window.setTimeout(() => {
        const all = [...swipes, { club_id: top.club_id, action }];
        onSwipes(all);
        setFlying(null);
        setDrag(null);
        if (action === "right") say("Matched! 💜");
        if (action === "super") say("Super-liked! ⭐ Top of your matches");
        // ask once per run of passes (exactly the 5th in a row), and never again once they've closed the question
        let streak = 0;
        while (streak < all.length && all[all.length - 1 - streak].action === "left") streak++;
        if (action === "left" && streak === WHY_AFTER && !store.get(`hm.nowhy.${jobId}`, false)) setAskWhy(true);
        else if (all.length % CHECKPOINT === 0) setCheckpoint(true);
      }, 220);
    },
    [top, flying, swipes, onSwipes, say, jobId],
  );

  const undo = useCallback(() => {
    if (!swipes.length || flying) return;
    pinned.current = swipes[swipes.length - 1].club_id;
    onSwipes(swipes.slice(0, -1));
    say("Undone ↩︎");
  }, [swipes, flying, onSwipes, say]);

  const dismissWhy = () => {
    setAskWhy(false);
    store.set(`hm.nowhy.${jobId}`, true);
  };

  const chooseReason = (kind: Penalty["kind"] | "other") => {
    setAskWhy(false);
    const lefts = swipes.slice(-WHY_AFTER).map((s) => cards.find((c) => c.club_id === s.club_id)).filter((c): c is Card => !!c);
    const r = REASONS.find((x) => x.kind === kind)!;
    if (kind !== "other") {
      const p: Penalty =
        kind === "time"
          ? { kind, levels: lefts.map((c) => c.commitment.level) }
          : kind === "category"
            ? { kind, categories: lefts.map(categoryKey) }
            : { kind };
      pinned.current = null;
      onPenalties([...penalties, p]);
      say(`Got it: ${r.toast}.`);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || moreFor || askWhy || checkpoint || searching) return;
      if (e.key === "ArrowRight") decide("right");
      else if (e.key === "ArrowLeft") decide("left");
      else if (e.key === "ArrowUp") decide("super");
      else if (e.key === "?" || e.key === "m") top && setMoreFor(top);
      else if (e.key === "z" || e.key === "Backspace") undo();
      else if (e.key === "/") setSearching(true);
      else if (e.key === "Enter" || e.key === "ArrowDown") {
        // jump between the photos and the details
        const el = slot.current?.querySelector(".club-card");
        if (el) el.scrollTo({ top: el.scrollTop > 0 ? 0 : el.clientHeight * 0.85, behavior: "smooth" });
      }
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide, undo, top, moreFor, askWhy, checkpoint, searching]);

  // A decision made from search: any club, in any order; deciding again replaces the earlier choice.
  const decideFor = (club_id: string, action: SwipeAction) => {
    onSwipes([...swipes.filter((s) => s.club_id !== club_id), { club_id, action }]);
    say(action === "left" ? "Passed" : action === "super" ? "Super-liked! ⭐ Top of your matches" : "Matched! 💜");
  };

  // --- dragging: sideways moves swipe the card; vertical moves scroll the profile (touch-action: pan-y)
  const onPointerDown = (e: React.PointerEvent) => {
    if (flying || (e.target as HTMLElement).closest("a, button")) return;
    start.current = { x: e.clientX, y: e.clientY, id: e.pointerId, mode: "?" };
    dragged.current = false;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const st = start.current;
    if (!st || st.id !== e.pointerId || st.mode === "scroll") return;
    const x = e.clientX - st.x;
    const y = e.clientY - st.y;
    if (st.mode === "?") {
      if (Math.hypot(x, y) < 8) return;
      if (Math.abs(x) < Math.abs(y)) {
        st.mode = "scroll";
        return;
      }
      st.mode = "drag";
      dragged.current = true;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    }
    setDrag({ x, y: y / 4 });
  };
  const onPointerUp = () => {
    const st = start.current;
    start.current = null;
    if (!st || st.mode !== "drag" || !drag) return;
    if (drag.x > THRESHOLD) decide("right");
    else if (drag.x < -THRESHOLD) decide("left");
    else setDrag(null);
  };

  const dx = fly === "right" ? 600 : fly === "left" ? -600 : drag?.x ?? 0;
  const dy = fly === "super" ? -800 : drag?.y ?? 0;
  const style = {
    transform: `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`,
    transition: drag && !fly ? "none" : "transform 220ms ease-out",
  };
  const stamp = (v: number) => Math.max(0, Math.min(1, v / THRESHOLD));

  const rights = swipes.filter((s) => s.action !== "left").length;

  return (
    <section className="screen deck-screen">
      <div className="deck-top">
        <span className="muted">
          {swipes.length} swiped · {rights} match{rights === 1 ? "" : "es"}
          {researching && " · still finding clubs…"}
        </span>
        <span className="deck-actions">
          <button type="button" className="ghost small icon" onClick={() => setSearching(true)} title="Search clubs (/)" aria-label="Search clubs">
            🔍
          </button>
          <button type="button" className="ghost small" onClick={onSeeMatches} disabled={!rights}>
            See matches →
          </button>
        </span>
      </div>

      <div className="deck">
        {next && (
          <div className={`card-slot behind ${fly ? "rising" : ""}`} aria-hidden>
            <ClubCard card={next} active={false} />
          </div>
        )}
        {top ? (
          <div
            ref={slot}
            className="card-slot top"
            style={style}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            // a drag that ends over a photo shouldn't also count as a tap that flips it
            onClickCapture={(e) => {
              if (dragged.current) e.stopPropagation();
              dragged.current = false;
            }}
            key={top.club_id}
          >
            <span className="stamp join" style={{ opacity: fly === "right" ? 1 : stamp(drag?.x ?? 0) }}>
              JOIN
            </span>
            <span className="stamp pass" style={{ opacity: fly === "left" ? 1 : stamp(-(drag?.x ?? 0)) }}>
              PASS
            </span>
            <span className="stamp super" style={{ opacity: fly === "super" ? 1 : 0 }}>
              SUPER
            </span>
            <ClubCard card={top} active />
          </div>
        ) : (
          <div className="deck-empty">
            {researching ? (
              <>
                <div className="spinner" aria-hidden />
                <p>Finding more clubs…</p>
                {lastAction && <p className="muted small">{lastAction}</p>}
              </>
            ) : (
              <>
                <p className="big">That's every club we found! 🎉</p>
                <button type="button" className="primary" onClick={onSeeMatches} disabled={!rights}>
                  {rights ? "See your matches" : "No matches yet"}
                </button>
                {!!swipes.length && (
                  <button type="button" className="ghost" onClick={undo}>
                    ↩︎ Undo last swipe
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="controls" role="group" aria-label="Swipe">
        <button type="button" className="round undo" onClick={undo} disabled={!swipes.length} title="Undo (Z)" aria-label="Undo">
          ↩︎
        </button>
        <button type="button" className="round pass" onClick={() => decide("left")} disabled={!top} title="Pass (←)" aria-label="Pass">
          ✕
        </button>
        <button type="button" className="round more" onClick={() => top && setMoreFor(top)} disabled={!top} title="Tell me more (?)" aria-label="Tell me more">
          ?
        </button>
        <button type="button" className="round super" onClick={() => decide("super")} disabled={!top} title="Super-like (↑)" aria-label="Super-like">
          ★
        </button>
        <button type="button" className="round join" onClick={() => decide("right")} disabled={!top} title="Join (→)" aria-label="Join">
          ♥
        </button>
      </div>
      <p className="keys muted small">← pass · → join · ↑ super · ↓ details · ? more · / search · Z undo</p>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      {askWhy && (
        <div className="sheet-backdrop" onClick={dismissWhy}>
          <div className="sheet" role="dialog" aria-label="Why not?" onClick={(e) => e.stopPropagation()}>
            <h3>Five passes in a row. What's off?</h3>
            <p className="muted">We'll reshuffle the rest of your deck.</p>
            <div className="chips">
              {REASONS.map((r) => (
                <button key={r.kind} type="button" className="chip" onClick={() => chooseReason(r.kind)}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {checkpoint && (
        <div className="sheet-backdrop" onClick={() => setCheckpoint(false)}>
          <div className="sheet" role="dialog" aria-label="Checkpoint" onClick={(e) => e.stopPropagation()}>
            <h3>
              {swipes.length} clubs in: {rights} match{rights === 1 ? "" : "es"}
            </h3>
            <p className="muted">See your matches, or keep swiping?</p>
            <div className="sheet-actions">
              <button type="button" className="ghost" onClick={() => setCheckpoint(false)}>
                Keep swiping
              </button>
              <button type="button" className="primary" onClick={onSeeMatches} disabled={!rights}>
                See my matches
              </button>
            </div>
          </div>
        </div>
      )}

      {searching && (
        <SearchSheet
          jobId={jobId}
          campus={campus}
          cards={cards}
          swipes={swipes}
          onDecide={decideFor}
          onAdded={onAddCard}
          onClose={() => setSearching(false)}
        />
      )}

      {moreFor && <MoreSheet jobId={jobId} card={moreFor} onClose={() => setMoreFor(null)} onDecide={(a) => { setMoreFor(null); decide(a); }} />}
    </section>
  );
}
