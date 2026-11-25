import { fetchJson } from "./client";
import type { SessionDetailResponse, SessionListResponse } from "./types";

export function fetchSessions(
  token: string,
  onUnauthorized: () => void,
  { limit, offset }: { limit: number; offset: number },
): Promise<SessionListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return fetchJson<SessionListResponse>(`/api/sessions?${query.toString()}`, token, onUnauthorized);
}

export function fetchSessionDetail(
  token: string,
  onUnauthorized: () => void,
  id: string,
): Promise<SessionDetailResponse> {
  return fetchJson<SessionDetailResponse>(
    `/api/sessions/${encodeURIComponent(id)}`,
    token,
    onUnauthorized,
  );
}
