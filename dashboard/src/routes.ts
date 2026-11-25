import type { PageId } from "./components/Nav";

export type Route = { page: PageId; tapeId: string | null };

/** Parses `#/monitor`, `#/tapes`, `#/tapes/<id>`, `#/containment`. Unknown hashes fall back to the Lab Monitor. */
export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
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
