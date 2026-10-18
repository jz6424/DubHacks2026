import type { ReactNode } from "react";
import type { Options, Profile } from "./types";

const CAMPUS: Record<string, string> = { seattle: "Seattle", bothell: "Bothell", tacoma: "Tacoma" };
const EXPERIENCE: Record<string, string> = {
  beginners_only: "Beginner-friendly only",
  open_to_selective: "Open to applications & tryouts",
};
const shortInterest = (s: string) => s.split(" (")[0];

/** Before the demo deck: who the demo student is, shown as the answers they gave to each onboarding question. */
export function DemoIntro({
  profile: p,
  options,
  cardCount,
  onStart,
  onBack,
}: {
  profile: Profile | null;
  options: Options | null;
  cardCount: number;
  onStart: () => void;
  onBack: () => void;
}) {
  if (!p) {
    return (
      <section className="screen center">
        <div className="spinner big" aria-hidden />
      </section>
    );
  }
  const none = <span className="dim">Skipped</span>;
  const list = (xs: string[]) => (xs.length ? <Tags items={xs} /> : none);
  const groups: { title: string; rows: [string, ReactNode][] }[] = [
    {
      title: "The basics",
      rows: [
        ["Campus", p.campus ? `UW ${CAMPUS[p.campus] ?? p.campus}` : none],
        ["Year", p.year ?? none],
        ["Major", p.major ?? none],
      ],
    },
    { title: "What they're into", rows: [["Interests", list(p.interests.map(shortInterest))]] },
    {
      title: "Time and goals",
      rows: [
        ["Commitment", p.commitment ? (options?.commitment[p.commitment] ?? p.commitment) : none],
        ["Looking to", list(p.goals)],
      ],
    },
    {
      title: "Logistics",
      rows: [
        ["Free", list(p.availability)],
        ["Dues budget", p.budget ? (options?.budget[p.budget] ?? p.budget) : none],
        ["Experience", p.experience ? EXPERIENCE[p.experience] : none],
      ],
    },
    { title: "Anything to avoid?", rows: [["Avoid", p.avoid ?? <span className="dim">Nothing in particular</span>]] },
  ];

  return (
    <section className="screen demo-intro">
      <p className="eyebrow">Demo</p>
      <h2>Meet the demo student</h2>
      <p className="muted">
        You'll swipe as them. Here's how they answered the questions, and the clubs we found are based on these answers.
      </p>
      <div className="persona">
        <div className="persona-head">
          <span className="persona-emoji" aria-hidden>
            🧑‍💻
          </span>
          <div>
            <strong>
              {p.year ?? "Student"} · {p.major ?? "Undeclared"}
            </strong>
            <div className="muted small">{p.campus ? `UW ${CAMPUS[p.campus] ?? p.campus}` : "UW"}</div>
          </div>
        </div>
        {groups.map((g) => (
          <div key={g.title} className="persona-group">
            <h3>{g.title}</h3>
            <dl>
              {g.rows.map(([q, a]) => (
                <div key={q}>
                  <dt>{q}</dt>
                  <dd>{a}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <div className="nav">
        <button type="button" className="ghost" onClick={onBack}>
          ← Back
        </button>
        <button type="button" className="primary" onClick={onStart} disabled={!cardCount}>
          Start swiping{cardCount ? ` (${cardCount} clubs)` : ""}
        </button>
      </div>
    </section>
  );
}

function Tags({ items }: { items: string[] }) {
  return (
    <span className="tags">
      {items.map((t) => (
        <span key={t} className="tag">
          {t}
        </span>
      ))}
    </span>
  );
}
