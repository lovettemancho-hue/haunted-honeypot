import { normalizeSessionDetail, normalizeSessionList } from "./adapter";
import { fetchJson } from "./client";
import type { SessionDetailResponse, SessionListResponse } from "./types";

export function fetchSessions(
  token: string,
  onUnauthorized: () => void,
  { limit, offset }: { limit: number; offset: number },
): Promise<SessionListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return fetchJson<unknown>(`/api/sessions?${query.toString()}`, token, onUnauthorized).then(
    normalizeSessionList,
  );
}

export function fetchSessionDetail(
  token: string,
  onUnauthorized: () => void,
  id: string,
): Promise<SessionDetailResponse> {
  return fetchJson<unknown>(`/api/sessions/${encodeURIComponent(id)}`, token, onUnauthorized).then(
    normalizeSessionDetail,
  );
}
