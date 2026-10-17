import type { Plan } from "./types";
export const ingest = (url: string): Promise<Plan> =>
  fetch("/api/ingest", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }) }).then(r => r.json());
export const listPlans = (): Promise<Plan[]> => fetch("/api/plans").then(r => r.json());
export const sessionSocket = (id: string) =>
  new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/session/${id}`);
