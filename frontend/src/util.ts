import type { Card, ClubStatus, JoinType } from "./types";

/** Some source fields hold a URL plus notes ("https://... (also: aruw.org/apply ...)"): take the first URL. */
export function firstUrl(s: string | undefined | null): string | null {
  if (!s) return null;
  const m = s.match(/https?:\/\/[^\s)"']+/);
  if (m) return m[0].replace(/[.,;]+$/, "");
  const bare = s.match(/\b[a-z0-9-]+(\.[a-z0-9-]+)+(\/[^\s)"']*)?/i);
  return bare ? `https://${bare[0]}` : null;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Fields the researchers couldn't confirm read like "couldn't confirm" / "unknown": dim them, don't hide them. */
export const unconfirmed = (s: string) => /couldn.?t confirm|unknown|not listed/i.test(s);

export const STATUS: Record<ClubStatus, { icon: string; label: string; tone: string }> = {
  active: { icon: "🟢", label: "Active", tone: "good" },
  unverified: { icon: "⚪", label: "Activity unverified", tone: "muted" },
  may_be_inactive: { icon: "⚠️", label: "May be inactive", tone: "warn" },
};

export const JOIN: Record<JoinType, string> = {
  open: "Open: just show up",
  application: "Application",
  tryout: "Tryout",
  interview: "Interview",
  unknown: "couldn't confirm",
};

export const TIER: Record<string, string> = {
  casual: "🌱 Casual",
  regular: "🌿 Regular",
  committed: "🌳 Committed",
  all_in: "🔥 All-in",
};

/** Where a link sits in the preferred order: official website, Instagram, HuskyLink (RSO directory), then the rest. */
function linkRank(url: string, c: Card): number {
  const site = firstUrl(c.links.website);
  const host = hostOf(url);
  if (site && host === hostOf(site)) return 0;
  if (/(^|\.)instagram\.com$/.test(host)) return 1;
  if (/^huskylink\./.test(host)) return 2;
  return 3;
}

/** The club's best link for the card front: its website, else Instagram, else HuskyLink, else the best other source. */
export function primaryLink(c: Card): { label: string; url: string } | null {
  const site = firstUrl(c.links.website);
  if (site) return { label: hostOf(site), url: site };
  const ig = firstUrl(c.links.instagram);
  if (ig) return { label: "Instagram", url: ig };
  const hl = firstUrl(c.links.huskylink);
  if (hl) return { label: "HuskyLink", url: hl };
  const other = sortedSources(c)[0]?.url ?? firstUrl(c.last_active.source);
  return other ? { label: hostOf(other), url: other } : null;
}

/** Sources in the preferred order (stable within each rank). */
export function sortedSources(c: Card): { url: string; checked: string }[] {
  return c.sources
    .map((s) => ({ url: firstUrl(s.url), checked: s.checked }))
    .filter((s): s is { url: string; checked: string } => !!s.url)
    .map((s, i) => ({ s, i, r: linkRank(s.url, c) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.s);
}

/** Short "last active" line for the card front. */
export function lastActive(c: Card): string {
  const d = c.last_active.date;
  if (!d || /unknown/i.test(d)) return `${STATUS[c.status].icon} ${STATUS[c.status].label}`;
  return `${STATUS[c.status].icon} Last active ${formatDate(d)}`;
}

export function formatDate(d: string): string {
  const t = Date.parse(d);
  if (Number.isNaN(t)) return d;
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** First sentence-ish, for a card front that reads in ~10 seconds. */
export function short(s: string, max = 140): string {
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "));
  return (stop > 60 ? cut.slice(0, stop + 1) : cut.replace(/\s+\S*$/, "")) + "…";
}

/** Local persistence (per job): survives refreshes, never required for the app to work. */
export const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const v = localStorage.getItem(key);
      return v ? (JSON.parse(v) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private mode etc. */
    }
  },
  del(key: string) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};
