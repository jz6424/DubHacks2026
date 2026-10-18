import type { Job, More, Options, Profile, Results, Swipe } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = JSON.parse(detail).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  options: () => fetch("/api/options").then((r) => json<Options>(r)),
  summary: (p: Profile) => post("/api/summary", p).then((r) => json<{ summary: string; key: string }>(r)),
  startJob: (p: Profile) => post("/api/jobs", p).then((r) => json<Job>(r)),
  job: (id: string) => fetch(`/api/jobs/${id}`).then((r) => json<Job>(r)),
  more: (job: string, club: string) => post(`/api/jobs/${job}/cards/${club}/more`).then((r) => json<More>(r)),
  results: (job: string, swipes: Swipe[]) => post(`/api/jobs/${job}/results`, { swipes }).then((r) => json<Results>(r)),
  draft: (job: string, club: string) => post(`/api/jobs/${job}/cards/${club}/draft`).then((r) => json<{ text: string }>(r)),
};
