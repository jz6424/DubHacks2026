import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Matches } from "./Matches";
import { Onboarding } from "./Onboarding";
import { SwipeDeck, type Penalty } from "./SwipeDeck";
import type { Job, Options, Profile, Swipe } from "./types";
import { store } from "./util";

type Screen = "welcome" | "onboarding" | "confirm" | "research" | "swipe" | "matches";

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

  const startResearch = async () => {
    setError(null);
    try {
      const j = await api.startJob(profile);
      setJob(j);
      setJobId(j.id);
      setScreen(j.status === "done" && j.cards.length ? "swipe" : "research");
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const startOver = () => {
    setJobId(null);
    setJob(null);
    setSwipesState([]);
    setPenaltiesState([]);
    setProfile(EMPTY);
    setScreen("welcome");
  };

  const researching = !!job && (job.status === "researching" || job.running);
  const cards = job?.cards ?? [];
  const lastAction = job?.actions.length ? job.actions[job.actions.length - 1] : null;

  return (
    <div className="app">
      <header className="topbar">
        <button type="button" className="brand" onClick={() => setScreen(jobId ? "swipe" : "welcome")}>
          <span aria-hidden>💜</span> HuskyMatch
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
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setJobId(DEMO_JOB);
                setScreen("swipe");
              }}
            >
              Try the demo (CS sophomore)
            </button>
          </section>
        )}

        {screen === "onboarding" && options && (
          <Onboarding options={options} profile={profile} onChange={setProfile} onDone={() => setScreen("confirm")} onBack={() => setScreen("welcome")} />
        )}

        {screen === "confirm" && <Confirm profile={profile} onEdit={() => setScreen("onboarding")} onGo={startResearch} />}

        {screen === "research" && (
          <section className="screen research">
            <h2>{researching ? "Finding your clubs…" : job?.status === "error" ? "Something went wrong" : "Research done"}</h2>
            {job?.summary && <pre className="summary">{job.summary}</pre>}
            {researching && (
              <p className="muted">
                This takes a few minutes: we only show clubs we could verify. You can start swiping once a few are ready.
              </p>
            )}
            {job?.status === "error" && <p className="error-text">{job.error}</p>}
            <div className="found">
              <div className="found-count">
                <strong>{cards.length}</strong> club{cards.length === 1 ? "" : "s"} found
              </div>
              <div className="found-list">
                {cards.map((c) => (
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
              className="primary big"
              disabled={cards.length < Math.min(READY_AT, researching ? READY_AT : 1)}
              onClick={() => setScreen("swipe")}
            >
              {researching
                ? cards.length >= READY_AT
                  ? `Start swiping (${cards.length} ready)`
                  : `Start swiping (${cards.length}/${READY_AT} ready)`
                : "Start swiping"}
            </button>
          </section>
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
