import { normalizeContainment } from "./adapter";
import { fetchBlob, fetchJson } from "./client";
import type { ContainmentRule } from "./types";

export function fetchContainment(
  token: string,
  onUnauthorized: () => void,
): Promise<ContainmentRule[]> {
  return fetchJson<unknown>("/api/containment", token, onUnauthorized).then(normalizeContainment);
}

export function fetchContainmentScript(token: string, onUnauthorized: () => void): Promise<Blob> {
  return fetchBlob("/api/containment?format=script", token, onUnauthorized);
}
