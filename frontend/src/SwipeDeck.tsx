import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ClubCard } from "./ClubCard";
import { MoreSheet } from "./MoreSheet";
import type { Card, Swipe, SwipeAction } from "./types";

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

const categoryKey = (c: Card) => c.category.toLowerCase().split(/[\/&,–-]/)[0].trim();

export function SwipeDeck({ jobId, cards, researching, lastAction, swipes, onSwipes, penalties, onPenalties, onSeeMatches }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [flying, setFlying] = useState<{ id: string; action: SwipeAction } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [askWhy, setAskWhy] = useState(false);
  const [checkpoint, setCheckpoint] = useState(false);
  const [moreFor, setMoreFor] = useState<Card | null>(null);
  const start = useRef<{ x: number; y: number; id: number } | null>(null);
  const toastTimer = useRef<number | undefined>();

  const swiped = useMemo(() => new Set(swipes.map((s) => s.club_id)), [swipes]);
  // Remaining cards in arrival order, with "show fewer of these" rules pushing matches down the deck.
  const queue = useMemo(() => {
    const rest = cards.map((c, i) => ({ c, i })).filter(({ c }) => !swiped.has(c.club_id));
    const score = (c: Card) => penalties.filter((p) => matches(p, c)).length;
    return rest.sort((a, b) => score(a.c) - score(b.c) || a.i - b.i).map(({ c }) => c);
  }, [cards, swiped, penalties]);
  const top = queue[0];
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
      setExpanded(false);
      window.setTimeout(() => {
        const all = [...swipes, { club_id: top.club_id, action }];
        onSwipes(all);
        setFlying(null);
        setDrag(null);
        if (action === "right") say("Matched! 💜");
        if (action === "super") say("Super-liked! ⭐ Top of your matches");
        const tail = all.slice(-3);
        if (action === "left" && tail.length === 3 && tail.every((s) => s.action === "left")) setAskWhy(true);
        else if (all.length % CHECKPOINT === 0) setCheckpoint(true);
      }, 220);
    },
    [top, flying, swipes, onSwipes, say],
  );

  const undo = useCallback(() => {
    if (!swipes.length || flying) return;
    onSwipes(swipes.slice(0, -1));
    say("Undone ↩︎");
  }, [swipes, flying, onSwipes, say]);

  const chooseReason = (kind: Penalty["kind"] | "other") => {
    setAskWhy(false);
    const lefts = swipes.slice(-3).map((s) => cards.find((c) => c.club_id === s.club_id)).filter((c): c is Card => !!c);
    const r = REASONS.find((x) => x.kind === kind)!;
    if (kind !== "other") {
      const p: Penalty =
        kind === "time"
          ? { kind, levels: lefts.map((c) => c.commitment.level) }
          : kind === "category"
            ? { kind, categories: lefts.map(categoryKey) }
            : { kind };
      onPenalties([...penalties, p]);
      say(`Got it: ${r.toast}.`);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || moreFor || askWhy || checkpoint) return;
      if (e.key === "ArrowRight") decide("right");
      else if (e.key === "ArrowLeft") decide("left");
      else if (e.key === "ArrowUp") decide("super");
      else if (e.key === "?" || e.key === "m") top && setMoreFor(top);
      else if (e.key === "z" || e.key === "Backspace") undo();
      else if (e.key === "Enter") setExpanded((x) => !x);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide, undo, top, moreFor, askWhy, checkpoint]);

  // --- dragging (disabled while the card is expanded so its text can scroll)
  const onPointerDown = (e: React.PointerEvent) => {
    if (expanded || flying) return;
    start.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!start.current || start.current.id !== e.pointerId) return;
    setDrag({ x: e.clientX - start.current.x, y: e.clientY - start.current.y });
  };
  const onPointerUp = () => {
    if (!start.current) return;
    start.current = null;
    if (!drag) return;
    if (drag.y < -THRESHOLD && Math.abs(drag.y) > Math.abs(drag.x)) decide("super");
    else if (drag.x > THRESHOLD) decide("right");
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
        <button type="button" className="ghost small" onClick={onSeeMatches} disabled={!rights}>
          See matches →
        </button>
      </div>

      <div className="deck">
        {next && (
          <div className={`card-slot behind ${fly ? "rising" : ""}`} aria-hidden>
            <ClubCard card={next} expanded={false} onToggle={() => {}} />
          </div>
        )}
        {top ? (
          <div
            className={`card-slot top ${expanded ? "expanded" : ""}`}
            style={style}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            key={top.club_id}
          >
            <span className="stamp join" style={{ opacity: fly === "right" ? 1 : stamp(drag?.x ?? 0) }}>
              JOIN
            </span>
            <span className="stamp pass" style={{ opacity: fly === "left" ? 1 : stamp(-(drag?.x ?? 0)) }}>
              PASS
            </span>
            <span className="stamp super" style={{ opacity: fly === "super" ? 1 : stamp(-(drag?.y ?? 0)) }}>
              SUPER
            </span>
            <ClubCard card={top} expanded={expanded} onToggle={() => setExpanded((x) => !x)} />
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
      <p className="keys muted small">← pass · → join · ↑ super-like · ? more · Z undo</p>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      {askWhy && (
        <div className="sheet-backdrop" onClick={() => setAskWhy(false)}>
          <div className="sheet" role="dialog" aria-label="Why not?" onClick={(e) => e.stopPropagation()}>
            <h3>Three passes in a row. What's off?</h3>
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

      {moreFor && <MoreSheet jobId={jobId} card={moreFor} onClose={() => setMoreFor(null)} onDecide={(a) => { setMoreFor(null); decide(a); }} />}
    </section>
  );
}
