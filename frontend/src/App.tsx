import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Corrections, mergeInto } from "./Corrections";
import { Sidebar } from "./Sidebar";
import { Timeline } from "./Timeline";
import { TopDown } from "./TopDown";
import type { Actor, ClipSummary, Overrides, Scene } from "./types";
import { VideoPanel } from "./VideoPanel";

const EMPTY_OVERRIDES: Overrides = { merge: [], tier: {}, labels: {}, rejected_links: [] };
const TIER_ORDER = { involved: 0, nearby: 1, background: 2, hidden: 3 };

/** Road users to show: involved and nearby by default (background on request); hidden never, unless selected. */
function visibleActors(scene: Scene, showBackground: boolean, selected: string | null): Actor[] {
  return scene.actors
    .filter((a) => a.id === selected || a.tier === "involved" || a.tier === "nearby" || (showBackground && a.tier === "background"))
    .sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || a.t_start - b.t_start);
}

export default function App() {
  const [clips, setClips] = useState<ClipSummary[]>([]);
  const [clipId, setClipId] = useState<string | null>(null);
  const [scene, setScene] = useState<Scene | null>(null);
  const [status, setStatus] = useState<ClipSummary | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(0.5);
  const [selected, setSelected] = useState<string | null>(null);
  const [showLanes, setShowLanes] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [blurPlates, setBlurPlates] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Overrides>(EMPTY_OVERRIDES);
  const [applying, setApplying] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);

  useEffect(() => {
    api
      .clips()
      .then((cs) => {
        setClips(cs);
        const fromHash = window.location.hash.slice(1).split("@")[0];
        setClipId(cs.find((c) => c.id === fromHash)?.id ?? cs.find((c) => c.ready)?.id ?? cs[0]?.id ?? null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Load the scene when ready; otherwise poll pipeline status.
  useEffect(() => {
    if (!clipId) return;
    // Deep link: #<clip>@<seconds> opens the clip at that moment.
    const [hashClip, hashT] = window.location.hash.slice(1).split("@");
    if (hashClip !== clipId) window.location.hash = clipId;
    setScene(null);
    setSelected(null);
    setTime(0);
    let stop = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const s = await api.clip(clipId);
        if (stop) return;
        setStatus(s);
        if (s.ready && s.status.state !== "running") {
          const [sc, ov] = await Promise.all([api.scene(clipId), api.overrides(clipId)]);
          setScene(sc);
          setOverrides({ ...EMPTY_OVERRIDES, ...ov });
          const t0 = hashClip === clipId ? Number(hashT) : NaN;
          if (Number.isFinite(t0)) pendingSeek.current = t0;
        } else {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (e) {
        setError(String(e));
      }
    };
    poll();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [clipId]);

  // One clock: the video element. A rAF loop mirrors its time into React state.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setTime((t) => (Math.abs(t - v.currentTime) > 1e-3 ? v.currentTime : t));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate;
  }, [rate, scene]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v || pendingSeek.current === null) return;
    const t = pendingSeek.current;
    pendingSeek.current = null;
    const go = () => (v.currentTime = t);
    if (v.readyState >= 1) go();
    else v.addEventListener("loadedmetadata", go, { once: true });
  }, [scene]);

  const seek = useCallback((t: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setTime(t);
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (v.ended) v.currentTime = 0;
      v.play();
    } else v.pause();
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const on = () => setPlaying(!v.paused);
    v.addEventListener("play", on);
    v.addEventListener("pause", on);
    v.addEventListener("ended", on);
    return () => {
      v.removeEventListener("play", on);
      v.removeEventListener("pause", on);
      v.removeEventListener("ended", on);
    };
  }, [scene]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "SELECT") return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowLeft") seek(Math.max(0, (videoRef.current?.currentTime ?? 0) - 0.25));
      else if (e.code === "ArrowRight") seek((videoRef.current?.currentTime ?? 0) + 0.25);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seek, togglePlay]);

  const actors = useMemo(() => (scene ? visibleActors(scene, showAll, selected) : []), [scene, showAll, selected]);

  // Save corrections, wait for the identity stages to recompute, reload the scene in place.
  const saveOverrides = useCallback(
    async (ov: Overrides) => {
      if (!clipId) return;
      setApplying(true);
      setOverrides(ov);
      try {
        await api.saveOverrides(clipId, ov);
        for (;;) {
          await new Promise((r) => setTimeout(r, 700));
          const s = await api.clip(clipId);
          if (s.status.state === "error") throw new Error(s.status.error ?? "pipeline error");
          if (s.status.state !== "running") break;
        }
        const sc = await api.scene(clipId);
        setScene(sc);
        // if the selected track was absorbed into another, follow it
        setSelected((cur) => (cur && !sc.actors.some((a) => a.id === cur) ? sc.actors.find((a) => a.merged_from.includes(cur))?.id ?? null : cur));
      } catch (e) {
        setError(String(e));
      } finally {
        setApplying(false);
      }
    },
    [clipId],
  );

  // Clicking a road user anywhere: normally selects it; in "same vehicle as…" mode it links the two tracks.
  const onActorClick = useCallback(
    (id: string | null) => {
      if (linkFrom && id && id !== linkFrom && scene) {
        saveOverrides(mergeInto(overrides, scene.actors, linkFrom, id));
        setLinkFrom(null);
        setSelected(linkFrom);
        return;
      }
      setSelected(id);
    },
    [linkFrom, scene, overrides, saveOverrides],
  );

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setLinkFrom(null);
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, []);

  return (
    <div className="app">
      <header>
        <h1>Crash Replay</h1>
        <select value={clipId ?? ""} onChange={(e) => setClipId(e.target.value)} aria-label="Clip">
          {clips.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <label className="toggle">
          <input type="checkbox" checked={showLanes} onChange={(e) => setShowLanes(e.target.checked)} /> Show lane geometry
        </label>
        <label className="toggle">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show background traffic
        </label>
        <label className="toggle">
          <input type="checkbox" checked={blurPlates} onChange={(e) => setBlurPlates(e.target.checked)} /> Hide licence plates
        </label>
        <span className="disclaimer">AI-generated draft for review. Not a legal determination or professional reconstruction.</span>
      </header>

      {error && <div className="error">{error}</div>}
      {linkFrom && (
        <div className="link-banner">
          Click the other track of the same vehicle as <b>{linkFrom}</b> (in the video, top-down, list or timeline). Esc to
          cancel.
        </div>
      )}

      {!scene && status && <PipelineStatus status={status} />}

      {scene && clipId && (
        <main>
          <div className="stage">
            <VideoPanel
              scene={scene}
              actors={actors}
              time={time}
              videoUrl={api.videoUrl(clipId)}
              videoRef={videoRef}
              selected={selected}
              onSelect={onActorClick}
              showLanes={showLanes}
              blurPlates={blurPlates}
            />
            <div className="topdown-wrap">
              <div className="panel-title">
                {scene.geometry.calibration.mode === "monocular"
                  ? "Top-down · camera-centred · distances from known object sizes"
                  : "Top-down · travel direction → · road-aligned, follows the recording vehicle"}
              </div>
              <TopDown scene={scene} actors={actors} time={time} selected={selected} onSelect={onActorClick} />
              {!scene.actors.some((a) => a.ground.length) && (
                <div className="topdown-empty">
                  Positions of other road users are not available for this clip.
                  <br />
                  <span className="muted">See “Data quality” for why.</span>
                </div>
              )}
            </div>
          <Timeline
            duration={scene.clip.duration}
            time={time}
            playing={playing}
            rate={rate}
            actors={actors}
            laneChanges={scene.geometry.calibration.lane_changes ?? []}
            selected={selected}
            onSeek={seek}
            onTogglePlay={togglePlay}
            onRate={setRate}
            onSelect={onActorClick}
          />
          </div>
          <Sidebar
            scene={scene}
            actors={actors}
            time={time}
            selected={selected}
            onSelect={onActorClick}
            onSeek={seek}
            top={
              <Corrections
                scene={scene}
                overrides={overrides}
                selected={selected}
                linkFrom={linkFrom}
                applying={applying}
                onSave={saveOverrides}
                onLinkFrom={setLinkFrom}
                onSelect={setSelected}
                onSeek={seek}
              />
            }
          />
        </main>
      )}
    </div>
  );
}

function PipelineStatus({ status }: { status: ClipSummary }) {
  return (
    <div className="pipeline">
      <h2>Processing {status.title}</h2>
      {status.stages.map((name) => {
        const s = status.status.stages[name] ?? { state: "pending", progress: 0, message: "" };
        return (
          <div key={name} className={`stage ${s.state}`}>
            <span className="name">{name}</span>
            <div className="bar">
              <div style={{ width: `${Math.round(100 * (s.state === "done" ? 1 : s.progress))}%` }} />
            </div>
            <span className="msg">{s.state === "error" ? `error: ${s.message}` : s.message}</span>
          </div>
        );
      })}
      {(status.status.state === "error" || status.status.state === "interrupted") && (
        <button onClick={() => api.rerun(status.id).then(() => window.location.reload())}>Resume</button>
      )}
    </div>
  );
}
