export interface Substep { text: string; start: number | null; end: number | null }

export interface Step {
  index: number;
  title: string;
  start: number | null;
  end: number | null;
  substeps: Substep[];
  visual_check: string;
  verifiable: boolean;
  timer_seconds: number | null;
}

export interface Plan {
  id: string;
  source_url: string;
  kind: "video" | "article";
  title: string;
  ingredients: string[];
  video_url: string | null;
  duration: number | null;
  steps: Step[];
}

export interface PlanSummary { id: string; title: string; kind: string; steps: number }

export type JobStage = "queued" | "fetching" | "watching" | "reading" | "finishing" | "ready" | "error";
export interface Job { job_id: string; stage: JobStage; plan_id: string | null; error?: string | null }

export interface Frame { data_url: string; t_ms: number }
export interface CheckResult {
  step_index: number; done: boolean; confidence: number; hint: string; latency_ms: number;
}

/** How a step got completed — shown as different check marks. */
export type DoneHow = "vision" | "manual" | "skipped";
