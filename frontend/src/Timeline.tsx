import { actorColor } from "./interp";
import type { Actor, LaneChange } from "./types";

interface Props {
  duration: number;
  time: number;
  playing: boolean;
  rate: number;
  actors: Actor[];
  laneChanges: LaneChange[];
  selected: string | null;
  onSeek: (t: number) => void;
  onTogglePlay: () => void;
  onRate: (r: number) => void;
  onSelect: (id: string) => void;
}

const STEP = 0.25; // one analysis frame at 4 fps

export function Timeline({ duration, time, playing, rate, actors, laneChanges, selected, onSeek, onTogglePlay, onRate, onSelect }: Props) {
  const pct = (t: number) => `${(100 * t) / Math.max(duration, 0.001)}%`;
  return (
    <div className="timeline">
      <div className="transport">
        <button onClick={() => onSeek(Math.max(0, time - STEP))} title="Back one frame (←)">
          ◀︎
        </button>
        <button className="play" onClick={onTogglePlay} title="Play/pause (space)">
          {playing ? "❚❚" : "▶︎"}
        </button>
        <button onClick={() => onSeek(Math.min(duration, time + STEP))} title="Forward one frame (→)">
          ▶︎▶︎
        </button>
        <span className="clock">
          {time.toFixed(2)} s <span className="muted">/ {duration.toFixed(1)} s</span>
        </span>
        <select value={rate} onChange={(e) => onRate(Number(e.target.value))} title="Playback speed">
          {[0.25, 0.5, 1].map((r) => (
            <option key={r} value={r}>
              {r}×
            </option>
          ))}
        </select>
      </div>
      <div className="scrub">
        <div className="markers">
          {laneChanges.map((lc) => (
            <button
              key={lc.t}
              className="marker"
              style={{ left: pct(lc.t_start), width: pct(lc.t - lc.t_start) }}
              onClick={() => onSeek(lc.t_start)}
              title={`Lane change ${lc.direction}: starts ${lc.t_start.toFixed(1)} s, crosses the line at ${lc.t.toFixed(1)} s`}
            >
              {lc.direction === "right" ? "lane change →" : "← lane change"}
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={duration}
          step={0.01}
          value={time}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Time"
        />
        <div className="lanes">
          {actors.map((a) => (
            <div
              key={a.id}
              className={`span ${selected === a.id ? "sel" : ""}`}
              style={{ left: pct(a.t_start), width: pct(a.t_end - a.t_start), background: actorColor(a.id) }}
              onClick={() => onSelect(a.id)}
              title={`${a.id} (${a.cls}) ${a.t_start.toFixed(1)}–${a.t_end.toFixed(1)} s`}
            />
          ))}
          <div className="cursor" style={{ left: pct(time) }} />
        </div>
      </div>
    </div>
  );
}
