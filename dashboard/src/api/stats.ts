import { fetchJson } from "./client";
import type { StatsResponse } from "./types";

export function fetchStats(token: string, onUnauthorized: () => void): Promise<StatsResponse> {
  return fetchJson<StatsResponse>("/api/stats", token, onUnauthorized);
}
