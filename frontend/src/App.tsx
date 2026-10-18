import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api";
import logo from "./assets/logo.png";
import { DemoIntro } from "./DemoIntro";
import { Matches } from "./Matches";
import { Onboarding } from "./Onboarding";
import { SwipeDeck, type Penalty } from "./SwipeDeck";
import type { Job, Options, Profile, Swipe } from "./types";
import { store } from "./util";

type Screen = "welcome" | "onboarding" | "confirm" | "research" | "demo" | "swipe" | "matches";

const EMPTY: Profile = {
  campus: null,
  year: null,
  major: null,
  interests: [],
  commitment: null,
  goals: [],
  availability: [],
  budget: null,
  experience: null,
  avoid: null,
};
const DEMO_JOB = (import.meta.env.VITE_DEMO_JOB as string | undefined) ?? "8aa212374383";
const READY_AT = 5; // cards before "start swiping" unlocks while research continues

export default function App() {
  const [screen, setScreen] = useState<Screen>(() => store.get("hm.screen", "welcome"));
  const [profile, setProfile] = useState<Profile>(() => store.get("hm.profile", EMPTY));
  const [jobId, setJobId] = useState<string | null>(() => store.get("hm.job", null));
  const [job, setJob] = useState<Job | null>(null);
  const [options, setOptions] = useState<Options | null>(null);
  const [swipes, setSwipesState] = useState<Swipe[]>([]);
  const [penalties, setPenaltiesState] = useState<Penalty[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [limited, setLimited] = useState<string | null>(null); // server refused a new search (daily limits)

  useEffect(() => store.set("hm.screen", screen), [screen]);
  useEffect(() => store.set("hm.profile", profile), [profile]);
  useEffect(() => store.set("hm.job", jobId), [jobId]);

  useEffect(() => {
    api.options().then(setOptions).catch((e) => setError(String(e.message ?? e)));
  }, []);

  // Swipes and "show fewer" rules are per job, so a refresh (or reopening on the same device) keeps your place.
  useEffect(() => {
    if (!jobId) return;
    setSwipesState(store.get(`hm.swipes.${jobId}`, []));
    setPenaltiesState(store.get(`hm.penalties.${jobId}`, []));
  }, [jobId]);
  const setSwipes = useCallback(
    (s: Swipe[]) => {
      setSwipesState(s);
      if (jobId) store.set(`hm.swipes.${jobId}`, s);
    },
    [jobId],
  );
  const setPenalties = useCallback(
    (p: Penalty[]) => {
      setPenaltiesState(p);
      if (jobId) store.set(`hm.penalties.${jobId}`, p);
    },
    [jobId],
  );

  // Poll the job while research runs; cards stream in as researchers verify them.
  useEffect(() => {
    if (!jobId) return;
    let live = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (!live) return;
        setJob(j);
        setError(null);
        if (j.status === "researching" || j.running) timer = window.setTimeout(tick, 1500);
      } catch (e) {
        if (!live) return;
        setError(String((e as Error).message ?? e));
        timer = window.setTimeout(tick, 4000);
      }
    };
    tick();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  const startResearch = async (fresh = false) => {
    setError(null);
    try {
      const j = await api.startJob(profile, fresh);
      if (!store.get(`hm.started.${j.id}`, null)) store.set(`hm.started.${j.id}`, Date.now() / 1000);
      setJob(j);
      setJobId(j.id);
      setScreen(j.status === "done" && j.cards.length ? "swipe" : "research");
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setLimited(e.message);
      else setError(String((e as Error).message ?? e));
    }
  };

  const tryDemo = () => {
    setLimited(null);
    setJobId(DEMO_JOB);
    setScreen("demo");
  };

  const startOver = () => {
    if (swipes.length && !window.confirm("Start over? Your swipes on this list will be cleared.")) return;
    if (jobId) {
      store.del(`hm.swipes.${jobId}`);
      store.del(`hm.penalties.${jobId}`);
      store.del(`hm.nowhy.${jobId}`);
    }
    setJobId(null);
    setJob(null);
    setSwipesState([]);
    setPenaltiesState([]);
    setProfile(EMPTY);
    setScreen("welcome");
  };

  const researching = !!job && (job.status === "researching" || job.running);
  const cards = job?.cards ?? [];
  const found = cards.filter((c) => !c.from_search); // research results, without clubs pulled in through search
  const lastAction = job?.actions.length ? job.actions[job.actions.length - 1] : null;

  return (
    <div className="app">
      <div className="backdrop" aria-hidden>
        <i />
        <i />
        <i />
        <i />
        <i />
      </div>
      <header className="topbar">
        <button type="button" className="brand" onClick={() => setScreen(jobId ? "swipe" : "welcome")}>
          <img src={logo} alt="Me&UDub" className="brand-logo" draggable={false} />
        </button>
        {jobId && screen !== "welcome" && (
          <button type="button" className="ghost small" onClick={startOver}>
            Start over
          </button>
        )}
      </header>

      {error && <div className="banner error">{error}</div>}

      <main>
        {screen === "welcome" && (
          <section className="screen welcome">
            <h1>
              Find your people <span className="gold">at UW</span>
            </h1>
            <p className="lede">
              Tell us what you're into. We research real, currently active student clubs, then you swipe: right to join, left to pass.
            </p>
            <ul className="how">
              <li>
                <span>1</span> Answer a few quick questions
              </li>
              <li>
                <span>2</span> We check HuskyLink, club sites and public posts
              </li>
              <li>
                <span>3</span> Swipe, then get how to join, time, cost and contacts
              </li>
            </ul>
            <button type="button" className="primary big" onClick={() => setScreen("onboarding")} disabled={!options}>
              Get started
            </button>
            <button type="button" className="ghost" onClick={tryDemo}>
              Try the demo (CS sophomore)
            </button>
          </section>
        )}

        {screen === "onboarding" && options && (
          <Onboarding options={options} profile={profile} onChange={setProfile} onDone={() => setScreen("confirm")} onBack={() => setScreen("welcome")} />
        )}

        {screen === "confirm" && <Confirm profile={profile} onEdit={() => setScreen("onboarding")} onGo={() => startResearch()} />}
        {screen === "confirm" && limited && (
          <div className="empty-state">
            <p>{limited}</p>
            <button type="button" className="primary" onClick={tryDemo}>
              Try the demo instead
            </button>
          </div>
        )}

        {screen === "research" && (
          <section className="screen research">
            <h2>{researching ? "Finding your clubs…" : job?.status === "error" ? "Something went wrong" : "Research done"}</h2>
            {job?.summary && <pre className="summary">{job.summary}</pre>}
            {researching && (
              <p className="muted">
                This takes a few minutes: we only show clubs we could verify. You can start swiping once a few are ready.
              </p>
            )}
            {researching && job && <Elapsed since={job.created ?? store.get(`hm.started.${job.id}`, Date.now() / 1000)} />}
            {job?.status === "error" && (
              <div className="empty-state">
                <p className="error-text">Research hit a problem: {job.error}</p>
                <div className="nav">
                  <button type="button" className="ghost" onClick={() => setScreen("onboarding")}>
                    ← Edit answers
                  </button>
                  <button type="button" className="primary" onClick={() => startResearch(true)}>
                    Try again
                  </button>
                </div>
              </div>
            )}
            {job?.status === "done" && !researching && found.length === 0 && (
              <div className="empty-state">
                <p>We couldn't verify any active clubs for this exact combination.</p>
                <p className="muted small">Try adding an interest, or relaxing dues or time limits.</p>
                <button type="button" className="primary" onClick={() => setScreen("onboarding")}>
                  Adjust my answers
                </button>
              </div>
            )}
            <div className="found">
              <div className="found-count">
                <strong>{found.length}</strong> club{found.length === 1 ? "" : "s"} found
              </div>
              <div className="found-list">
                {found.map((c) => (
                  <span key={c.club_id} className="found-chip">
                    {c.category_emoji} {c.name}
                  </span>
                ))}
              </div>
            </div>
            <ul className="feed" aria-live="polite">
              {(job?.actions ?? []).slice(-7).map((a, i, arr) => (
                <li key={`${arr.length - i}-${a}`} style={{ opacity: 0.35 + (0.65 * (i + 1)) / arr.length }}>
                  {a}
                </li>
              ))}
              {researching && !job?.actions.length && <li className="muted">Starting researchers…</li>}
            </ul>
            <button
              type="button"
              className="primary big sticky-cta"
              disabled={found.length < Math.min(READY_AT, researching ? READY_AT : 1)}
              onClick={() => setScreen("swipe")}
            >
              {researching
                ? found.length >= READY_AT
                  ? `Start swiping (${found.length} ready)`
                  : `Start swiping (${found.length}/${READY_AT} ready)`
                : "Start swiping"}
            </button>
          </section>
        )}

        {screen === "demo" && (
          <DemoIntro
            profile={job?.id === DEMO_JOB ? job.profile : null}
            options={options}
            cardCount={job?.id === DEMO_JOB ? found.length : 0}
            onStart={() => setScreen("swipe")}
            onBack={() => setScreen("welcome")}
          />
        )}

        {screen === "swipe" && jobId && (
          <>
            {!job ? (
              <section className="screen center">
                <div className="spinner big" aria-hidden />
              </section>
            ) : (
              <SwipeDeck
                jobId={jobId}
                cards={cards}
                researching={researching}
                lastAction={lastAction}
                swipes={swipes}
                onSwipes={setSwipes}
                penalties={penalties}
                onPenalties={setPenalties}
                onSeeMatches={() => setScreen("matches")}
                campus={job.profile.campus ?? "seattle"}
                onAddCard={(c) => setJob((j) => (j && !j.cards.some((x) => x.club_id === c.club_id) ? { ...j, cards: [...j.cards, c] } : j))}
              />
            )}
          </>
        )}

        {screen === "matches" && jobId && job && (
          <Matches
            jobId={jobId}
            cards={cards}
            swipes={swipes}
            profile={job.profile}
            onKeepSwiping={() => setScreen("swipe")}
            onStartOver={startOver}
          />
        )}
      </main>

      <footer className="foot">Student project · Not affiliated with or endorsed by the University of Washington · Info may be out of date: confirm with each club.</footer>
    </div>
  );
}

/** "1:42 · usually 2–4 minutes" while research runs. */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const s = Math.max(0, Math.round(now / 1000 - since));
  return (
    <p className="elapsed muted small">
      ⏱ {Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")} · usually 2–4 minutes
    </p>
  );
}

function Confirm({ profile, onEdit, onGo }: { profile: Profile; onEdit: () => void; onGo: () => Promise<void> }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .summary(profile)
      .then((r) => setSummary(r.summary))
      .catch(() => setSummary(null));
  }, [profile]);
  return (
    <section className="screen confirm">
      <h2>Does this sound like you?</h2>
      <pre className="summary">{summary ?? "…"}</pre>
      <p className="muted small">We'll research clubs that fit. It takes a few minutes, and you can start swiping as soon as a few are ready.</p>
      <div className="nav">
        <button type="button" className="ghost" onClick={onEdit}>
          ← Edit answers
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await onGo();
            setBusy(false);
          }}
        >
          {busy ? "Starting…" : "Find my clubs"}
        </button>
      </div>
    </section>
  );
}
