import type { ClipSummary, Scene } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  clips: () => fetch("/api/clips").then((r) => json<ClipSummary[]>(r)),
  clip: (id: string) => fetch(`/api/clips/${id}`).then((r) => json<ClipSummary>(r)),
  scene: (id: string) => fetch(`/api/clips/${id}/scene`).then((r) => json<Scene>(r)),
  videoUrl: (id: string) => `/api/clips/${id}/video`,
  rerun: (id: string, fromStage?: string) =>
    fetch(`/api/clips/${id}/run${fromStage ? `?from_stage=${fromStage}` : ""}`, { method: "POST" }).then((r) =>
      json<ClipSummary>(r),
    ),
};
