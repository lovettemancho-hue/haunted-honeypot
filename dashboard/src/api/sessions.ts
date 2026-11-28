import { normalizeSessionDetail, normalizeSessionList, normalizeSummary } from "./adapter";
import { fetchJson } from "./client";
import type { SessionDetailResponse, SessionListResponse, SessionSummary } from "./types";

/** `filters` are extra Brain query parameters (see lib/tapeFilters). */
export function fetchSessions(
  token: string,
  onUnauthorized: () => void,
  { limit, offset, filters }: { limit: number; offset: number; filters?: URLSearchParams },
): Promise<SessionListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  filters?.forEach((value, key) => query.set(key, value));
  return fetchJson<unknown>(`/api/sessions?${query.toString()}`, token, onUnauthorized).then(
    normalizeSessionList,
  );
}

export function fetchSessionSummary(
  token: string,
  onUnauthorized: () => void,
  filters?: URLSearchParams,
): Promise<SessionSummary> {
  const qs = filters?.toString() ?? "";
  return fetchJson<unknown>(
    `/api/sessions/summary${qs ? `?${qs}` : ""}`,
    token,
    onUnauthorized,
  ).then(normalizeSummary);
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

const JSON_HEADERS = { "Content-Type": "application/json" };

export function setTapeReviewed(
  token: string,
  onUnauthorized: () => void,
  id: string,
  reviewed: boolean,
): Promise<unknown> {
  return fetchJson<unknown>(`/api/sessions/${encodeURIComponent(id)}/review`, token, onUnauthorized, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ reviewed }),
  });
}

/** Marks many tapes at once, 500 per request (the Brain's limit). */
export async function setTapesReviewed(
  token: string,
  onUnauthorized: () => void,
  ids: string[],
  reviewed: boolean,
): Promise<void> {
  for (let i = 0; i < ids.length; i += 500) {
    await fetchJson<unknown>("/api/sessions/review", token, onUnauthorized, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ ids: ids.slice(i, i + 500), reviewed }),
    });
  }
}
