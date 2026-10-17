import type { Actor, Box, EgoSample, GroundSample } from "./types";

/** Index of the last sample with t <= time (binary search); -1 if before the first. */
function floorIndex<T extends { t: number }>(xs: T[], time: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (!xs.length || time < xs[0].t) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (xs[mid].t <= time) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

const lerp = (a: number, b: number, w: number) => a + (b - a) * w;

/** Half a frame interval of slack so boxes don't flicker at track ends. */
const EDGE = 0.13;

export function boxAt(actor: Actor, time: number): { box: Box; interp: boolean } | null {
  const xs = actor.boxes;
  if (!xs.length || time < xs[0].t - EDGE || time > xs[xs.length - 1].t + EDGE) return null;
  const i = floorIndex(xs, time);
  if (i < 0) return { box: xs[0].box, interp: xs[0].interp };
  if (i >= xs.length - 1) return { box: xs[xs.length - 1].box, interp: xs[xs.length - 1].interp };
  const a = xs[i];
  const b = xs[i + 1];
  const w = (time - a.t) / (b.t - a.t);
  return { box: a.box.map((v, k) => lerp(v, b.box[k], w)) as Box, interp: a.interp || b.interp };
}

export function groundAt(actor: Actor, time: number): GroundSample | null {
  const xs = actor.ground;
  if (!xs.length || time < xs[0].t - EDGE || time > xs[xs.length - 1].t + EDGE) return null;
  const i = Math.max(0, Math.min(floorIndex(xs, time), xs.length - 2));
  if (xs.length === 1) return xs[0];
  const a = xs[i];
  const b = xs[i + 1];
  const w = Math.max(0, Math.min(1, (time - a.t) / (b.t - a.t)));
  const num = (p: number | null, q: number | null) => (p === null || q === null ? null : lerp(p, q, w));
  return {
    ...a,
    t: time,
    s: lerp(a.s, b.s, w),
    d: lerp(a.d, b.d, w),
    s_sigma: lerp(a.s_sigma, b.s_sigma, w),
    d_sigma: lerp(a.d_sigma, b.d_sigma, w),
    v: num(a.v, b.v),
    v_lo: num(a.v_lo, b.v_lo),
    v_hi: num(a.v_hi, b.v_hi),
    v_rel: lerp(a.v_rel, b.v_rel, w),
    heading_deg: num(a.heading_deg, b.heading_deg),
    dist_m: num(a.dist_m, b.dist_m),
    measured: a.measured || b.measured,
  };
}

export function egoAt(samples: EgoSample[], time: number): EgoSample | null {
  if (!samples.length) return null;
  const i = Math.max(0, Math.min(floorIndex(samples, time), samples.length - 2));
  if (samples.length === 1) return samples[0];
  const a = samples[i];
  const b = samples[i + 1];
  const w = Math.max(0, Math.min(1, (time - a.t) / (b.t - a.t)));
  const num = (p: number | null, q: number | null) => (p === null || q === null ? (p ?? q) : lerp(p, q, w));
  return { t: time, s: lerp(a.s, b.s, w), d: num(a.d, b.d), v: num(a.v, b.v), v_sigma: num(a.v_sigma, b.v_sigma) };
}

export const kmh = (mps: number | null | undefined) => (mps === null || mps === undefined ? null : mps * 3.6);

/** Stable, distinguishable colour per actor id. */
export function actorColor(id: string): string {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${(h * 47) % 360} 85% 60%)`;
}
