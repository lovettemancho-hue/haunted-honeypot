import { normalizeStats } from "./adapter";
import { fetchJson } from "./client";
import type { StatsResponse } from "./types";

export function fetchStats(token: string, onUnauthorized: () => void): Promise<StatsResponse> {
  return fetchJson<unknown>("/api/stats", token, onUnauthorized).then(normalizeStats);
}

