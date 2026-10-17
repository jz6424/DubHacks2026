export type StageState = "pending" | "running" | "done" | "error";

export interface ClipSummary {
  id: string;
  title: string;
  curated: boolean;
  license: string | null;
  source_url: string | null;
  ready: boolean;
  stages: string[];
  status: {
    state: "idle" | "running" | "done" | "error" | "interrupted";
    error?: string | null;
    stages: Record<string, { state: StageState; progress: number; message: string }>;
  };
}

/** Normalized [x0, y0, x1, y1] in 0..1 of the video frame. */
export type Box = [number, number, number, number];

export interface GroundSample {
  t: number;
  s: number; // metres along the road
  d: number; // metres across the road, + right, 0 = ego lane centre
  s_sigma: number;
  d_sigma: number;
  v: number | null; // m/s
  v_lo: number | null;
  v_hi: number | null;
  v_rel: number;
  heading_deg: number | null;
  measured: boolean;
  dist_m: number | null;
}

export interface Actor {
  id: string;
  cls: string;
  group: "vehicle" | "two_wheeler" | "person";
  label: string | null;
  manual: boolean;
  t_start: number;
  t_end: number;
  boxes: { t: number; box: Box; interp: boolean }[];
  ground: GroundSample[];
}

export interface EgoSample {
  t: number;
  s: number;
  d: number | null;
  v: number | null;
  v_sigma: number | null;
}

export interface QualityNote {
  level: "info" | "warn" | "error";
  code: string;
  message: string;
  actor?: string;
}

export interface LaneChange {
  t: number; // when the car crossed the lane line
  t_start: number; // when the sideways move began
  direction: "left" | "right";
  from_lane: number;
  to_lane: number;
}

export interface RoadLine {
  d: number; // lateral road position, m
  seen_pct: number;
  painted: number | null;
  kind: "solid" | "dashed";
}

export interface LaneSample {
  t: number;
  x0: number | null;
  y0: number | null;
  aL: number | null;
  aR: number | null;
}

export interface Scene {
  clip: {
    id: string;
    title: string;
    source_url: string | null;
    license: string | null;
    attribution: string | null;
    duration: number;
    width: number;
    height: number;
    fps: number;
  };
  frame_fps: number;
  frames: number[];
  actors: Actor[];
  ego: { source: "overlay" | "lane_flow" | "none"; samples: EgoSample[] };
  geometry: {
    status: "ok" | "partial" | "insufficient";
    calibration: Record<string, unknown> & {
      camera_height_m?: number;
      hfov_deg?: number;
      K?: number;
      K_rel_sigma?: number;
      lane_width_m: number;
      dash_period_m: number;
      lane_frames_pct: number;
      dash_pairs?: number;
      lane_changes?: LaneChange[];
    };
    lanes: LaneSample[];
    road_lines: RoadLine[];
  };
  overlay: { present: boolean; samples: { t: number; speed_mps: number; raw: string }[] };
  quality: QualityNote[];
  stats: { model_tokens: { prompt_tokens: number; completion_tokens: number } | null };
}
