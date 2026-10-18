import { useEffect, useState } from "react";
import { api } from "./api";
import { Md } from "./Md";
import type { Card, More, SwipeAction } from "./types";
import { hostOf } from "./util";

const cache = new Map<string, More>();

interface Props {
  jobId: string;
  card: Card;
  onClose: () => void;
  onDecide: (a: SwipeAction) => void;
}

/** "❓ Tell me more": 3-5 extra details with their sources, then the swipe options again (spec Phase 3). */
export function MoreSheet({ jobId, card, onClose, onDecide }: Props) {
  const key = `${jobId}/${card.club_id}`;
  const [more, setMore] = useState<More | null>(cache.get(key) ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (more) return;
    let live = true;
    api
      .more(jobId, card.club_id)
      .then((m) => {
        cache.set(key, m);
        if (live) setMore(m);
      })
      .catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [jobId, card.club_id, key, more]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet more" role="dialog" aria-label={`More about ${card.name}`} onClick={(e) => e.stopPropagation()}>
        <h3>
          {card.category_emoji} {card.name}
        </h3>
        {!more && !error && (
          <div className="loading">
            <div className="spinner" aria-hidden />
            <span className="muted">Looking into it (a few seconds)…</span>
          </div>
        )}
        {error && <p className="error-text">Couldn't load more details: {error}</p>}
        {more && (
          <>
            <div className="more-text">
              {more.text.split("\n").map((line, i) =>
                line.trim() ? (
                  <p key={i}>
                    <Md text={line.replace(/^\s*[-*•]\s*/, "• ")} />
                  </p>
                ) : null,
              )}
            </div>
            {more.sources.length > 0 && (
              <div className="sources">
                <h4>Sources</h4>
                <ul>
                  {more.sources.map((s) => (
                    <li key={s.url}>
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.title && s.title !== s.url ? s.title : hostOf(s.url)}
                      </a>{" "}
                      <span className="muted">{hostOf(s.url)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        <div className="sheet-actions">
          <button type="button" className="round pass" onClick={() => onDecide("left")} aria-label="Pass">
            ✕
          </button>
          <button type="button" className="ghost" onClick={onClose}>
            Back to card
          </button>
          <button type="button" className="round super" onClick={() => onDecide("super")} aria-label="Super-like">
            ★
          </button>
          <button type="button" className="round join" onClick={() => onDecide("right")} aria-label="Join">
            ♥
          </button>
        </div>
      </div>
    </div>
  );
}
