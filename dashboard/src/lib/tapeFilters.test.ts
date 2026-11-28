import { describe, expect, it } from "vitest";
import fc from "fast-check";
import {
  activeFilterCount,
  DEFAULT_FILTERS,
  dayLabel,
  filtersToApiParams,
  hashPath,
  hashQuery,
  parseFilters,
  serializeFilters,
  toggleSeverity,
} from "./tapeFilters";
import { parseHash, tapesHref } from "../routes";

const NOW = Date.parse("2026-11-28T12:00:00Z");

describe("tape filters", () => {
  it("defaults serialize to nothing and send no API params", () => {
    expect(serializeFilters(DEFAULT_FILTERS)).toBe("");
    expect(filtersToApiParams(DEFAULT_FILTERS, NOW).toString()).toBe("");
    expect(activeFilterCount(DEFAULT_FILTERS)).toBe(0);
  });

  it("round-trips through the URL", () => {
    const f = { ...DEFAULT_FILTERS, q: "203.0", severity: ["5", "3"] as const, status: "unreviewed" as const, technique: "T1110", range: "custom" as const, from: "2026-11-01", to: "2026-11-02", order: "oldest" as const, login: "yes" as const, ip: "198.51.100.8" };
    const back = parseFilters(serializeFilters({ ...f, severity: [...f.severity] }));
    expect(back).toEqual({ ...f, severity: ["5", "3"] });
  });

  it("ignores junk in the URL", () => {
    const f = parseFilters("sev=2,5,x&status=nope&range=1y&from=yesterday&order=random&login=maybe");
    expect(f).toEqual({ ...DEFAULT_FILTERS, severity: ["5"] });
  });

  it("parsing any query never throws and always yields valid values", () => {
    fc.assert(
      fc.property(fc.string(), (q) => {
        const f = parseFilters(q);
        expect(["all", "unreviewed", "reviewed"]).toContain(f.status);
        expect(f.q.length).toBeLessThanOrEqual(100);
        expect(f.severity.every((s) => ["1", "3", "5"].includes(s))).toBe(true);
      }),
    );
  });

  it("maps filters to Brain parameters", () => {
    const p = filtersToApiParams(
      { ...DEFAULT_FILTERS, severity: ["5"], status: "unreviewed", login: "no", range: "24h" },
      NOW,
    );
    expect(p.get("severity")).toBe("5");
    expect(p.get("reviewed")).toBe("false");
    expect(p.get("logged_in")).toBe("false");
    expect(p.get("since")).toBe("2026-11-27T12:00:00.000Z");
    const custom = filtersToApiParams({ ...DEFAULT_FILTERS, range: "custom", from: "2026-11-01", to: "2026-11-02" }, NOW);
    expect(custom.get("since")).toBe("2026-11-01T00:00:00Z");
    expect(custom.get("until")).toBe("2026-11-03T00:00:00.000Z"); // "to" day included
  });

  it("toggles severities in a stable order", () => {
    expect(toggleSeverity([], "1")).toEqual(["1"]);
    expect(toggleSeverity(["1"], "5")).toEqual(["5", "1"]);
    expect(toggleSeverity(["5", "1"], "5")).toEqual(["1"]);
  });

  it("labels days in UTC", () => {
    expect(dayLabel("2026-11-28T00:30:00Z", NOW)).toBe("Today");
    expect(dayLabel("2026-11-27T23:59:00Z", NOW)).toBe("Yesterday");
    expect(dayLabel("2026-11-25T10:00:00Z", NOW)).toContain("25 Nov 2026");
  });

  it("splits hashes and routes ignore the query", () => {
    expect(hashQuery("#/tapes/abc?sev=5")).toBe("sev=5");
    expect(hashPath("#/tapes/abc?sev=5")).toBe("#/tapes/abc");
    expect(parseHash("#/tapes/abc?sev=5")).toEqual({ page: "tapes", tapeId: "abc" });
    expect(parseHash("#/tapes?sev=5")).toEqual({ page: "tapes", tapeId: null });
  });

  it("builds filtered Lab Tapes links with encoded values", () => {
    expect(tapesHref({})).toBe("#/tapes");
    expect(tapesHref({ technique: "T1059.004" })).toBe("#/tapes?tech=T1059.004");
    expect(tapesHref({ q: "a&b=<x>" })).toBe("#/tapes?q=a%26b%3D%3Cx%3E");
  });
});
