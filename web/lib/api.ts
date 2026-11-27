import type { ModelCheck, Plan } from "./types";
import type { TeamSettings } from "./settings";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** Read a team ID from what someone typed: "1234567" or a link containing /entry/1234567/. */
export function parseTeamId(text: string): number | null {
  const s = text.trim();
  const m = s.match(/\/entry\/(\d+)/) ?? s.match(/^#?(\d+)$/);
  if (!m) return null;
  const id = Number(m[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function planQuery(s: TeamSettings, fresh = false): string {
  const q = new URLSearchParams({
    horizon: String(s.horizon),
    chip: s.chip,
    ft_value: String(s.ftValue),
    bench_weight: String(s.benchWeight),
    consistency: String(s.consistency),
    chase: String(s.chase),
    locked: s.locked.join(","),
    banned: s.banned.join(","),
  });
  if (s.freeTransfers !== null) q.set("free_transfers", String(s.freeTransfers));
  if (s.bank !== null) q.set("bank", String(s.bank));
  if (s.league) q.set("league", String(s.league));
  if (s.rival) q.set("rival", String(s.rival));
  if (fresh) q.set("fresh", "true");
  return q.toString();
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Can't reach the planner right now. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    let detail = `The planner returned an error (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export function fetchPlan(teamId: number, s: TeamSettings, signal?: AbortSignal, fresh = false) {
  return getJson<Plan>(`/api/team/${teamId}/plan?${planQuery(s, fresh)}`, { signal });
}

/** Where the Python planning API lives (server side only). */
export function apiBase(): string {
  return (process.env.FPL_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

/** Server-side fetch of the backtest summary; null when the API is unavailable. */
export async function fetchModelCheck(): Promise<ModelCheck | null> {
  try {
    return await getJson<ModelCheck>(`${apiBase()}/api/model-check`, { next: { revalidate: 21600 } });
  } catch {
    return null;
  }
}
