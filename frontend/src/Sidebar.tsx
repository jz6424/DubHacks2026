import { actorColor, egoAt, groundAt, kmh, motionStateAt } from "./interp";
import type { Actor, QualityNote, Scene } from "./types";

interface Props {
  scene: Scene;
  actors: Actor[];
  time: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onSeek: (t: number) => void;
}

/** Clip-level notes first; per-actor notes only for listed actors, with the "distant" ones collapsed into one line. */
function qualityNotes(scene: Scene, actors: Actor[]): QualityNote[] {
  const shown = new Set(actors.map((a) => a.id));
  const clipLevel = scene.quality.filter((q) => !q.actor && (q.level !== "info" || q.code === "assumptions"));
  const perActor = scene.quality.filter((q) => q.actor && shown.has(q.actor));
  const distant = perActor.filter((q) => q.code === "distant").map((q) => q.actor);
  const others = perActor.filter((q) => q.code !== "distant");
  const out = [...clipLevel.filter((q) => q.code !== "assumptions"), ...others];
  if (distant.length)
    out.push({
      level: "warn",
      code: "distant",
      message: `${distant.join(", ")} never come within 50 m, so their speed ranges are wide.`,
    });
  return [...out, ...clipLevel.filter((q) => q.code === "assumptions")];
}

const fmt = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "—" : x.toFixed(digits));

export function Sidebar({ scene, actors, time, selected, onSelect, onSeek }: Props) {
  const ego = egoAt(scene.ego.samples, time);
  const cal = scene.geometry.calibration;
  const egoV = kmh(ego?.v);
  const egoPm = kmh(ego?.v_sigma ? 1.96 * ego.v_sigma : null);
  const motion = motionStateAt(scene, time);
  const mono = cal.mode === "monocular";
  const visible = actors
    .map((a) => ({ a, g: groundAt(a, time) }))
    .filter(({ a, g }) => g || (time >= a.t_start - 0.13 && time <= a.t_end + 0.13))
    .sort((x, y) => (x.g?.dist_m ?? 999) - (y.g?.dist_m ?? 999));

  return (
    <aside className="sidebar">
      <section>
        <h3>Recording camera</h3>
        {egoV !== null ? (
          <div className="ego-speed">
            <span className="big">{fmt(egoV)}</span> km/h
            {egoPm !== null && <span className="muted"> ±{fmt(egoPm)}</span>}
          </div>
        ) : (
          <div className="ego-speed">
            <span className="big-text">{{ stationary: "Standing still", creeping: "Possibly moving", moving: "Moving", unknown: "Can't tell" }[motion]}</span>
            {motion === "moving" && <span className="muted"> · speed unknown</span>}
          </div>
        )}
        <div className="muted small">
          {scene.ego.source === "overlay" && "Read from the dashcam's on-screen speed (OCR)."}
          {scene.ego.source === "lane_flow" && "Estimated from how fast lane dashes pass the camera."}
          {scene.ego.source === "background_motion" &&
            (motion === "unknown"
              ? "The background is hidden (something fills the view), so the camera's motion can't be checked here."
              : motion === "stationary"
                ? "From background motion: the scene behind the road users is not moving."
                : motion === "creeping"
                  ? "Slight background motion: could be the camera moving a little, or edges of nearby vehicles. Uncertain."
                  : "From background motion: the scene is moving; this clip has no way to measure the speed.")}
          {scene.ego.source === "none" && "Unknown: no speed overlay and no usable lane markings."}
        </div>
      </section>

      {!!scene.geometry.calibration.lane_changes?.length && (
        <section>
          <h3>Recording vehicle maneuvers</h3>
          <ul className="maneuvers small">
            {scene.geometry.calibration.lane_changes.map((lc) => (
              <li key={lc.t} className={time >= lc.t_start && time <= lc.t + 1 ? "now" : ""} onClick={() => onSeek(lc.t_start)}>
                <b>Lane change {lc.direction}</b> {lc.t_start.toFixed(1)}–{lc.t.toFixed(1)} s
                <span className="muted"> · from lane-line motion</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>
          Road users now <span className="muted">({visible.length})</span>
        </h3>
        <table className="actors">
          <thead>
            <tr>
              <th />
              <th>ID</th>
              <th title="Speed with 95% range; or closing speed toward the camera when absolute speed is unknown">km/h</th>
              <th title="Distance ahead of the camera">ahead</th>
              {mono ? (
                <th title="Time to contact at the current closing speed (independent of the assumed camera field of view)">TTC</th>
              ) : (
                <th title="Lateral offset from ego-lane centre, + right">lateral</th>
              )}
            </tr>
          </thead>
          <tbody>
            {visible.map(({ a, g }) => (
              <tr key={a.id} className={selected === a.id ? "sel" : ""} onClick={() => onSelect(selected === a.id ? null : a.id)}>
                <td>
                  <span className="dot" style={{ background: actorColor(a.id) }} />
                </td>
                <td>
                  {a.id} <span className="muted small">{a.label ?? a.cls}</span>
                  {a.manual && <span className="badge" title="IDs merged by hand">manual</span>}
                </td>
                <td>
                  {g?.v !== null && g?.v !== undefined ? (
                    <>
                      {fmt(kmh(g.v))} <span className="muted small">({fmt(kmh(g.v_lo))}–{fmt(kmh(g.v_hi))})</span>
                    </>
                  ) : g?.closing_mps !== undefined && Math.abs(g.closing_mps) >= 0.15 ? (
                    <span title="Relative to the camera; absolute speed needs the camera's own speed">
                      {fmt(kmh(Math.abs(g.closing_mps)), 1)} <span className="muted small">{g.closing_mps > 0 ? "closing" : "receding"}</span>
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {g?.dist_m !== null && g?.dist_m !== undefined ? (
                    `${fmt(g.dist_m, g.dist_m < 10 ? 1 : 0)} m`
                  ) : g ? (
                    <span className="muted" title="Not measurable here (cut off by the frame edge or too close); interpolated">
                      ~{fmt(g.s, g.s < 10 ? 1 : 0)} m
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                {mono ? (
                  <td>
                    {g?.ttc_s !== null && g?.ttc_s !== undefined ? (
                      <span className={g.ttc_s < 2 ? "ttc-warn" : ""}>
                        {fmt(g.ttc_s, 1)} s{g.ttc_sigma_s ? <span className="muted small"> ±{fmt(1.96 * g.ttc_sigma_s, 1)}</span> : null}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                ) : (
                  <td>{g ? `${g.d >= 0 ? "+" : ""}${fmt(g.d, 1)} m` : <span className="muted">—</span>}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3>How positions were derived</h3>
        {mono ? (
          <ul className="small derivation">
            <li>No lane markings to calibrate the road, so distances come from objects of known size.</li>
            <li>
              Size cues used: licence plate ({fmt((cal.plate_width_m ?? 0.305) * 100, 1)} cm) in <b>{cal.size_cues?.plate ?? 0}</b> frames,
              vehicle width in <b>{cal.size_cues?.width ?? 0}</b>, person height in <b>{cal.size_cues?.height ?? 0}</b>.
            </li>
            <li>
              Camera field of view <b>{fmt(Number(cal.hfov_deg))}°</b> ({cal.hfov_from}), ±{fmt((cal.hfov_rel_sigma ?? 0) * 100)}%: this
              scales every distance and speed. Time-to-contact doesn't depend on it.
            </li>
            <li>Boxes cut off by the frame edge are never used for size; those moments are interpolated and dimmed. Ranges are 95%.</li>
          </ul>
        ) : scene.geometry.status === "insufficient" || cal.K === undefined ? (
          <p className="small">Not computed for this clip. See data quality below.</p>
        ) : (
          <ul className="small derivation">
            <li>
              Lane lines found in <b>{fmt(cal.lane_frames_pct)}%</b> of frames; vanishing point tracked per frame.
            </li>
            <li>
              Lane width {cal.lane_width_m} m ⇒ camera height <b>{fmt(cal.camera_height_m, 2)} m</b>.
            </li>
            <li>
              Dash spacing {cal.dash_period_m} m over {cal.dash_pairs} dash pairs ⇒ field of view <b>{fmt(cal.hfov_deg)}°</b> (scale ±
              {fmt((cal.K_rel_sigma ?? 0) * 100)}%).
            </li>
            <li>Each road user is placed where its box bottom meets the road, then smoothed (Kalman). Ranges are 95%.</li>
          </ul>
        )}
      </section>

      <section>
        <h3>Data quality</h3>
        <ul className="quality">
          {qualityNotes(scene, actors).map((q, i) => (
            <li key={i} className={q.level}>
              {q.message}
            </li>
          ))}
        </ul>
      </section>

      <section className="muted small">
        Source:{" "}
        {scene.clip.source_url ? (
          <a href={scene.clip.source_url} target="_blank" rel="noreferrer">
            {scene.clip.title}
          </a>
        ) : (
          scene.clip.title
        )}
        {scene.clip.license && <> · {scene.clip.license}</>}
      </section>
    </aside>
  );
}
