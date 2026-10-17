export interface Step {
  index: number; title: string; detail: string;
  video_start: number | null; video_end: number | null;
  visual_check: string; verifiable: boolean; timer_seconds: number | null; key_objects: string[];
}
export interface Plan {
  id: string; source_url: string; kind: "youtube" | "video_file" | "article";
  title: string; youtube_id: string | null; duration: number | null; steps: Step[];
}
export interface Box { label: string; x1: number; y1: number; x2: number; y2: number }
export type SessionEvent =
  | { type: "step_active"; step: number }
  | { type: "verifying"; step: number }
  | { type: "step_done"; step: number; how: "vision" | "manual" | "skip" | "inferred" }
  | { type: "check"; step_index: number; done: boolean; confidence: number; hint: string; boxes: Box[] }
  | { type: "hint"; text: string }
  | { type: "finished" };
