import type { CheckResult, Frame, Job, Plan, PlanSummary } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

export const startIngest = (url: string, force = false) =>
  fetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, force }),
  }).then(json<Job>);

export const getJob = (id: string) => fetch(`/api/jobs/${id}`).then(json<Job>);
export const listPlans = () => fetch("/api/plans").then(json<PlanSummary[]>);
export const getPlan = (id: string) => fetch(`/api/plans/${id}`).then(json<Plan>);

export const checkStep = (plan_id: string, step_index: number, frames: Frame[], signal?: AbortSignal) =>
  fetch("/api/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id, step_index, frames }),
    signal,
  }).then(json<CheckResult>);
