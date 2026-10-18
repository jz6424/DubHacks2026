export type Campus = "seattle" | "bothell" | "tacoma";
export type Commitment = "casual" | "regular" | "committed" | "all_in";
export type Budget = "free" | "under_50" | "flexible";
export type Experience = "beginners_only" | "open_to_selective";

export interface Profile {
  campus: Campus | null;
  year: string | null;
  major: string | null;
  interests: string[];
  commitment: Commitment | null;
  goals: string[];
  availability: string[];
  budget: Budget | null;
  experience: Experience | null;
  avoid: string | null;
}

export interface Options {
  interests: string[];
  goals: string[];
  commitment: Record<Commitment, string>;
  budget: Record<Budget, string>;
  availability: string[];
}

export type ClubStatus = "active" | "may_be_inactive" | "unverified";
export type JoinType = "open" | "application" | "tryout" | "interview" | "unknown";

export interface Card {
  club_id: string;
  name: string;
  category: string;
  category_emoji: string;
  description: string;
  commitment: { level: Commitment; hours_per_week: string; estimated: boolean };
  dues: string;
  meeting_schedule: string;
  join_type: JoinType;
  fit_reason: string;
  wildcard: boolean;
  status: ClubStatus;
  last_active: { date: string; source: string };
  links: { huskylink: string; website: string; instagram: string };
  application: { deadline: string; url: string; steps: string[] };
  sources: { url: string; checked: string }[];
  interest_areas?: string[];
  image?: string; // same-origin URL of the club's photo/logo from the shared catalog; absent or "" when none
}

export interface Job {
  id: string;
  status: "researching" | "done" | "error";
  summary: string;
  profile: Profile;
  cards: Card[];
  actions: string[];
  usage: Record<string, number>;
  error: string | null;
  running: boolean;
  created?: number; // seconds since epoch; optional until the backend sends it
}

export type SwipeAction = "right" | "left" | "super";
export interface Swipe {
  club_id: string;
  action: SwipeAction;
}

export interface More {
  text: string;
  sources: { url: string; title: string }[];
}

export interface Results {
  order: string[];
  judged: {
    clubs: { club_id: string; availability_conflicts: string; good_to_know: string[] }[];
    action_plan: { when: string; step: string; club_id: string }[];
  };
  hours: { total: number; unknown: number; limit: number | null; over: boolean };
}
