import { api } from "./api";
import { actorColor } from "./interp";
import type { Actor, Overrides, Scene, Tier } from "./types";

interface Props {
  scene: Scene;
  overrides: Overrides;
  selected: string | null;
  linkFrom: string | null;
  applying: boolean;
  onSave: (ov: Overrides) => void;
  onLinkFrom: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  onSeek: (t: number) => void;
}

const TIER_LABEL: Record<Tier, string> = { involved: "Involved", nearby: "Nearby", background: "Background", hidden: "Hidden" };

/** The clearest (largest, not cut off) view of an actor among its first or last few detections. */
function bestView(a: Actor, which: "first" | "last") {
  const xs = a.boxes.filter((b) => !b.interp);
  const seg = which === "first" ? xs.slice(0, 6) : xs.slice(-6);
  const ok = seg.filter((b) => b.box[0] > 0.005 && b.box[2] < 0.995);
  const pool = ok.length ? ok : seg;
  return pool.reduce((m, b) => ((b.box[2] - b.box[0]) * (b.box[3] - b.box[1]) > (m.box[2] - m.box[0]) * (m.box[3] - m.box[1]) ? b : m), pool[0]);
}

export function mergeInto(ov: Overrides, actors: Actor[], a: string, b: string): Overrides {
  const A = actors.find((x) => x.id === a);
  const B = actors.find((x) => x.id === b);
  if (!A || !B || a === b) return ov;
  const [keep, absorb] = A.t_start <= B.t_start ? [a, b] : [b, a]; // the earlier track keeps its ID
  return { ...ov, merge: [...ov.merge, [keep, absorb]] };
}

export function Corrections({ scene, overrides, selected, linkFrom, applying, onSave, onLinkFrom, onSelect, onSeek }: Props) {
  const clip = scene.clip.id;
  const sel = scene.actors.find((a) => a.id === selected) ?? null;
  const hidden = scene.actors.filter((a) => a.tier === "hidden");
  const frameOf = (t: number) => Math.round(t * scene.frame_fps);

  const setTier = (a: Actor, tier: Tier) => {
    const next = { ...overrides.tier };
    if (tier === a.auto_tier) delete next[a.id];
    else next[a.id] = tier;
    onSave({ ...overrides, tier: next });
  };
  const setLabel = (a: Actor, label: string) => {
    const next = { ...overrides.labels };
    if (label.trim()) next[a.id] = label.trim();
    else delete next[a.id];
    if ((overrides.labels[a.id] ?? "") !== (next[a.id] ?? "")) onSave({ ...overrides, labels: next });
  };
  const split = (keep: string, absorb: string) =>
    onSave({ ...overrides, merge: overrides.merge.filter(([k, x]) => !(k === keep && x === absorb)) });

  return (
    <div className="corrections">
      {applying && <div className="applying">Applying your correction… (recomputing tracks and positions)</div>}

      {sel && (
        <section className="inspector">
          <h3>
            <span className="dot" style={{ background: actorColor(sel.id) }} /> {sel.id}{" "}
            <span className="muted small">
              {sel.cls} · {sel.t_start.toFixed(1)}–{sel.t_end.toFixed(1)} s
            </span>
          </h3>
          <div className="thumbs">
            {(["first", "last"] as const).map((w) => {
              const v = bestView(sel, w);
              return v ? (
                <button key={w} className="thumb" onClick={() => onSeek(v.t)} title={`Jump to ${v.t.toFixed(2)} s`}>
                  <img src={api.cropUrl(clip, frameOf(v.t), v.box)} alt={`${sel.id} ${w} seen`} />
                  <span>
                    {w} seen {v.t.toFixed(1)} s
                  </span>
                </button>
              ) : null;
            })}
          </div>
          <div className="tiers" role="group" aria-label="Relevance">
            {(Object.keys(TIER_LABEL) as Tier[]).map((t) => (
              <button key={t} className={sel.tier === t ? "on" : ""} disabled={applying} onClick={() => setTier(sel, t)}>
                {TIER_LABEL[t]}
                {sel.auto_tier === t && <span className="auto"> auto</span>}
              </button>
            ))}
          </div>
          <div className="muted small">Auto: {sel.tier_reason}.</div>
          <label className="label-edit">
            Label{" "}
            <input
              key={sel.id}
              defaultValue={sel.label ?? ""}
              placeholder="e.g. Kia Soul"
              disabled={applying}
              onBlur={(e) => setLabel(sel, e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            />
          </label>
          <div className="actions">
            {linkFrom === sel.id ? (
              <button onClick={() => onLinkFrom(null)}>Cancel</button>
            ) : (
              <button disabled={applying} onClick={() => onLinkFrom(sel.id)} title="Then click the other track of this same vehicle">
                Same vehicle as…
              </button>
            )}
          </div>
          {sel.merged_from.length > 0 && (
            <div className="small">
              Joined from:{" "}
              {sel.merged_from.map((m) => (
                <span key={m} className="chip">
                  {m}
                  {overrides.merge.some(([k, x]) => k === sel.id && x === m) && (
                    <button title="Split this track back out" disabled={applying} onClick={() => split(sel.id, m)}>
                      ✕
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      {scene.suggestions.length > 0 && (
        <section>
          <h3>Possibly the same vehicle</h3>
          <ul className="suggestions">
            {scene.suggestions.map((s) => (
              <li key={`${s.keep}-${s.absorb}`}>
                <div className="pair">
                  <button className="thumb" onClick={() => { onSelect(s.keep); onSeek(frameTime(scene, s.a_frame)); }}>
                    <img src={api.cropUrl(clip, s.a_frame, s.a_box, 96)} alt={`${s.keep} last seen`} />
                    <span>{s.keep}</span>
                  </button>
                  <span className="arrow">→ {s.gap_s > 0 ? `${s.gap_s.toFixed(1)} s →` : ""}</span>
                  <button className="thumb" onClick={() => { onSelect(s.absorb); onSeek(frameTime(scene, s.b_frame)); }}>
                    <img src={api.cropUrl(clip, s.b_frame, s.b_box, 96)} alt={`${s.absorb} first seen`} />
                    <span>{s.absorb}</span>
                  </button>
                </div>
                <div className="small">
                  <b>{s.verdict === "yes" ? "Model: likely the same" : "Model: unsure"}.</b>{" "}
                  <span className="muted">{s.reason}</span>
                </div>
                <div className="actions">
                  <button disabled={applying} onClick={() => onSave(mergeInto(overrides, scene.actors, s.keep, s.absorb))}>
                    Same vehicle
                  </button>
                  <button
                    disabled={applying}
                    onClick={() => onSave({ ...overrides, rejected_links: [...overrides.rejected_links, [s.keep, s.absorb]] })}
                  >
                    Not the same
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {hidden.length > 0 && (
        <section className="small">
          Hidden:{" "}
          {hidden.map((a) => (
            <span key={a.id} className="chip">
              {a.id}
              <button title="Show again" disabled={applying} onClick={() => setTier(a, a.auto_tier === "hidden" ? "nearby" : a.auto_tier)}>
                ↺
              </button>
            </span>
          ))}
        </section>
      )}
    </div>
  );
}

function frameTime(scene: Scene, frame: number) {
  return scene.frames[frame] ?? frame / scene.frame_fps;
}
