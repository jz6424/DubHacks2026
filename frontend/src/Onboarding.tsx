import { useState } from "react";
import type { Budget, Campus, Commitment, Experience, Options, Profile } from "./types";

const YEARS = ["Freshman", "Sophomore", "Junior", "Senior", "Transfer", "Grad student"];
const IDENTITY = "Cultural/identity-based communities";
const MAX_GOALS = 3;

interface Props {
  options: Options;
  profile: Profile;
  onChange: (p: Profile) => void;
  onDone: () => void;
  onBack: () => void;
}

interface ChipsProps<T extends string> {
  items: { value: T; label: string }[];
  selected: T[];
  onToggle: (v: T) => void;
  max?: number;
}

function Chips<T extends string>({ items, selected, onToggle, max }: ChipsProps<T>) {
  return (
    <div className="chips">
      {items.map(({ value, label }) => {
        const on = selected.includes(value);
        const full = !on && max !== undefined && selected.length >= max;
        return (
          <button
            key={value}
            type="button"
            className={`chip ${on ? "on" : ""}`}
            aria-pressed={on}
            disabled={full}
            onClick={() => onToggle(value)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

const one = <T,>(cur: T | null, v: T): T | null => (cur === v ? null : v);
const many = (cur: string[], v: string, max?: number) =>
  cur.includes(v) ? cur.filter((x) => x !== v) : max !== undefined && cur.length >= max ? cur : [...cur, v];
const shortInterest = (s: string) => s.split(" (")[0];

export function Onboarding({ options, profile: p, onChange, onDone, onBack }: Props) {
  const [step, setStep] = useState(0);
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch });

  const steps: { title: string; sub: string; skip: Partial<Profile>; body: JSX.Element }[] = [
    {
      title: "First, the basics",
      sub: "So we only show clubs on your campus.",
      skip: { campus: null, year: null, major: null },
      body: (
        <>
          <label className="q">Campus</label>
          <Chips<Campus>
            items={[
              { value: "seattle", label: "Seattle" },
              { value: "bothell", label: "Bothell" },
              { value: "tacoma", label: "Tacoma" },
            ]}
            selected={p.campus ? [p.campus] : []}
            onToggle={(v) => set({ campus: one(p.campus, v) })}
          />
          <label className="q">Year</label>
          <Chips items={YEARS.map((y) => ({ value: y, label: y }))} selected={p.year ? [p.year] : []} onToggle={(v) => set({ year: one(p.year, v) })} />
          <label className="q" htmlFor="major">
            Major (or intended major)
          </label>
          <input
            id="major"
            className="text"
            placeholder="e.g. Computer Science, undecided…"
            value={p.major ?? ""}
            onChange={(e) => set({ major: e.target.value || null })}
          />
        </>
      ),
    },
    {
      title: "What are you into?",
      sub: "Pick as many as you like.",
      skip: { interests: [] },
      body: (
        <>
          <Chips
            items={options.interests.map((i) => ({ value: i, label: shortInterest(i) }))}
            selected={p.interests}
            onToggle={(v) => set({ interests: many(p.interests, v) })}
          />
          <p className="hint">
            {p.interests.includes(IDENTITY)
              ? "✓ We'll include cultural and identity-based communities."
              : `Cultural and identity-based communities are opt-in: we only show them if you pick "${IDENTITY.split("/")[0]}…".`}
          </p>
        </>
      ),
    },
    {
      title: "Time and goals",
      sub: "How much time a week, and what you want out of it.",
      skip: { commitment: null, goals: [] },
      body: (
        <>
          <label className="q">Commitment</label>
          <Chips<Commitment>
            items={(Object.keys(options.commitment) as Commitment[]).map((k) => ({ value: k, label: options.commitment[k] }))}
            selected={p.commitment ? [p.commitment] : []}
            onToggle={(v) => set({ commitment: one(p.commitment, v) })}
          />
          <label className="q">
            What you want out of it <span className="muted">(up to {MAX_GOALS})</span>
          </label>
          <Chips
            items={options.goals.map((g) => ({ value: g, label: g }))}
            selected={p.goals}
            max={MAX_GOALS}
            onToggle={(v) => set({ goals: many(p.goals, v, MAX_GOALS) })}
          />
        </>
      ),
    },
    {
      title: "Logistics",
      sub: "When you're free, dues, and how selective is OK.",
      skip: { availability: [], budget: null, experience: null },
      body: (
        <>
          <label className="q">When are you free?</label>
          <Chips
            items={options.availability.map((a) => ({ value: a, label: a }))}
            selected={p.availability}
            onToggle={(v) => set({ availability: many(p.availability, v) })}
          />
          <label className="q">Budget for dues</label>
          <Chips<Budget>
            items={(Object.keys(options.budget) as Budget[]).map((k) => ({ value: k, label: options.budget[k] }))}
            selected={p.budget ? [p.budget] : []}
            onToggle={(v) => set({ budget: one(p.budget, v) })}
          />
          <label className="q">Experience</label>
          <Chips<Experience>
            items={[
              { value: "beginners_only", label: "Beginner-friendly only" },
              { value: "open_to_selective", label: "Open to applications & tryouts" },
            ]}
            selected={p.experience ? [p.experience] : []}
            onToggle={(v) => set({ experience: one(p.experience, v) })}
          />
        </>
      ),
    },
    {
      title: "Anything to avoid?",
      sub: "Optional: clubs, vibes or commitments you'd rather skip.",
      skip: { avoid: null },
      body: (
        <textarea
          className="text"
          rows={3}
          maxLength={300}
          placeholder="e.g. no early mornings, nothing with travel…"
          value={p.avoid ?? ""}
          onChange={(e) => set({ avoid: e.target.value || null })}
        />
      ),
    },
  ];

  const s = steps[step];
  const next = () => (step + 1 < steps.length ? setStep(step + 1) : onDone());
  return (
    <section className="screen onboarding">
      <div className="progress" aria-label={`Step ${step + 1} of ${steps.length}`}>
        {steps.map((_, i) => (
          <span key={i} className={i <= step ? "on" : ""} />
        ))}
      </div>
      <h2>{s.title}</h2>
      <p className="sub">{s.sub}</p>
      <div className="step-body">{s.body}</div>
      <div className="nav">
        <button type="button" className="ghost" onClick={() => (step ? setStep(step - 1) : onBack())}>
          ← Back
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            set(s.skip);
            next();
          }}
        >
          Skip / not sure
        </button>
        <button type="button" className="primary" onClick={next}>
          {step + 1 < steps.length ? "Next" : "Review"}
        </button>
      </div>
    </section>
  );
}
