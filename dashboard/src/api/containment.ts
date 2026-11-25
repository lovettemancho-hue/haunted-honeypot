import { fetchBlob, fetchJson } from "./client";
import type { ContainmentRule } from "./types";

export function fetchContainment(
  token: string,
  onUnauthorized: () => void,
): Promise<ContainmentRule[]> {
  return fetchJson<ContainmentRule[]>("/api/containment", token, onUnauthorized);
}

export function fetchContainmentScript(token: string, onUnauthorized: () => void): Promise<Blob> {
  return fetchBlob("/api/containment?format=script", token, onUnauthorized);
}
