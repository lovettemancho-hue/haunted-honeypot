import type { PageId } from "./components/Nav";
import { DEFAULT_FILTERS, serializeFilters, type TapeFilters } from "./lib/tapeFilters";

export type Route = { page: PageId; tapeId: string | null };

/**
 * Parses `#/monitor`, `#/tapes`, `#/tapes/<id>`, `#/containment`, ignoring any
 * `?query` (Lab Tapes keeps its filters there). Unknown hashes fall back to the Lab Monitor.
 */
export function parseHash(hash: string): Route {
  const path = hash.split("?")[0] ?? "";
  const parts = path.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "tapes") {
    let id: string | null = null;
    if (parts[1]) {
      try {
        id = decodeURIComponent(parts[1]);
      } catch {
        id = null;
      }
    }
    return { page: "tapes", tapeId: id };
  }
  if (parts[0] === "containment") return { page: "containment", tapeId: null };
  return { page: "monitor", tapeId: null };
}

export function tapeHref(id: string): string {
  return `#/tapes/${encodeURIComponent(id)}`;
}

/** Lab Tapes with some filters set, e.g. `tapesHref({ technique: "T1110" })`. */
export function tapesHref(filters: Partial<TapeFilters>): string {
  const query = serializeFilters({ ...DEFAULT_FILTERS, ...filters });
  return query ? `#/tapes?${query}` : "#/tapes";
}
