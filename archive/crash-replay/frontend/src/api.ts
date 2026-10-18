import type { Box, ClipSummary, Overrides, Scene } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  clips: () => fetch("/api/clips").then((r) => json<ClipSummary[]>(r)),
  clip: (id: string) => fetch(`/api/clips/${id}`).then((r) => json<ClipSummary>(r)),
  scene: (id: string) => fetch(`/api/clips/${id}/scene`).then((r) => json<Scene>(r)),
  videoUrl: (id: string) => `/api/clips/${id}/video`,
  overrides: (id: string) => fetch(`/api/clips/${id}/overrides`).then((r) => json<Overrides>(r)),
  saveOverrides: (id: string, ov: Overrides) =>
    fetch(`/api/clips/${id}/overrides`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ov),
    }).then((r) => json<ClipSummary>(r)),
  cropUrl: (id: string, frame: number, box: Box, w = 120) =>
    `/api/clips/${id}/crop/${frame}?box=${box.map((v) => Math.min(1, Math.max(0, v)).toFixed(4)).join(",")}&w=${w}`,
  rerun: (id: string, fromStage?: string) =>
    fetch(`/api/clips/${id}/run${fromStage ? `?from_stage=${fromStage}` : ""}`, { method: "POST" }).then((r) =>
      json<ClipSummary>(r),
    ),
};
