/**
 * Lab Tapes filters: one plain object, kept in the URL hash query
 * (`#/tapes/<id>?sev=5,3&status=unreviewed`) so links and Back keep them.
 * Only non-default values are written, so the default URL stays `#/tapes`.
 */

export type SeverityCode = "1" | "3" | "5";
export type DateRange = "all" | "24h" | "7d" | "30d" | "custom";
export type ReviewStatus = "all" | "unreviewed" | "reviewed";
export type LoginFilter = "any" | "yes" | "no";
export type SortOrder = "newest" | "oldest";

export interface TapeFilters {
  q: string;
  ip: string;
  severity: SeverityCode[];
  technique: string;
  login: LoginFilter;
  status: ReviewStatus;
  range: DateRange;
  /** yyyy-mm-dd (UTC), used when range is "custom". */
  from: string;
  to: string;
  order: SortOrder;
}

export const DEFAULT_FILTERS: TapeFilters = Object.freeze({
  q: "",
  ip: "",
  severity: [],
  technique: "",
  login: "any",
  status: "all",
  range: "all",
  from: "",
  to: "",
  order: "newest",
}) as TapeFilters;

const SEVERITIES: readonly SeverityCode[] = ["5", "3", "1"];
const RANGES: readonly DateRange[] = ["all", "24h", "7d", "30d", "custom"];
const STATUSES: readonly ReviewStatus[] = ["all", "unreviewed", "reviewed"];
const LOGINS: readonly LoginFilter[] = ["any", "yes", "no"];
const ORDERS: readonly SortOrder[] = ["newest", "oldest"];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_TEXT = 100;

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

const clip = (v: string | null): string => (v ?? "").slice(0, MAX_TEXT);

/** Query part of a hash such as `#/tapes/abc?sev=5` (without the `?`). */
export function hashQuery(hash: string): string {
  const i = hash.indexOf("?");
  return i === -1 ? "" : hash.slice(i + 1);
}

/** Hash without its query: `#/tapes/abc?sev=5` -> `#/tapes/abc`. */
export function hashPath(hash: string): string {
  const i = hash.indexOf("?");
  return i === -1 ? hash : hash.slice(0, i);
}

export function parseFilters(query: string): TapeFilters {
  const p = new URLSearchParams(query);
  const sev = (p.get("sev") ?? "")
    .split(",")
    .filter((s): s is SeverityCode => (SEVERITIES as readonly string[]).includes(s));
  const from = p.get("from") ?? "";
  const to = p.get("to") ?? "";
  return {
    q: clip(p.get("q")),
    ip: clip(p.get("ip")),
    severity: SEVERITIES.filter((s) => sev.includes(s)),
    technique: clip(p.get("tech")),
    login: pick(p.get("login"), LOGINS, "any"),
    status: pick(p.get("status"), STATUSES, "all"),
    range: pick(p.get("range"), RANGES, "all"),
    from: DATE_RE.test(from) ? from : "",
    to: DATE_RE.test(to) ? to : "",
    order: pick(p.get("order"), ORDERS, "newest"),
  };
}

export function serializeFilters(f: TapeFilters): string {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.ip) p.set("ip", f.ip);
  if (f.severity.length) p.set("sev", f.severity.join(","));
  if (f.technique) p.set("tech", f.technique);
  if (f.login !== "any") p.set("login", f.login);
  if (f.status !== "all") p.set("status", f.status);
  if (f.range !== "all") p.set("range", f.range);
  if (f.range === "custom" && f.from) p.set("from", f.from);
  if (f.range === "custom" && f.to) p.set("to", f.to);
  if (f.order !== "newest") p.set("order", f.order);
  return p.toString();
}

const HOUR = 3600_000;

/** Brain query parameters for these filters (no paging). Empty for the defaults. */
export function filtersToApiParams(f: TapeFilters, nowMs: number): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.ip) p.set("ip", f.ip);
  if (f.severity.length) p.set("severity", f.severity.join(","));
  if (f.technique) p.set("technique", f.technique);
  if (f.login !== "any") p.set("logged_in", f.login === "yes" ? "true" : "false");
  if (f.status !== "all") p.set("reviewed", f.status === "reviewed" ? "true" : "false");
  const back = { "24h": 24 * HOUR, "7d": 7 * 24 * HOUR, "30d": 30 * 24 * HOUR } as const;
  if (f.range === "24h" || f.range === "7d" || f.range === "30d") {
    // Round to the minute so polling reuses the same query string.
    const since = Math.floor((nowMs - back[f.range]) / 60_000) * 60_000;
    p.set("since", new Date(since).toISOString());
  } else if (f.range === "custom") {
    if (f.from) p.set("since", `${f.from}T00:00:00Z`);
    if (f.to) {
      const end = Date.parse(`${f.to}T00:00:00Z`) + 24 * HOUR; // "to" day is inclusive
      if (!Number.isNaN(end)) p.set("until", new Date(end).toISOString());
    }
  }
  if (f.order !== "newest") p.set("order", f.order);
  return p;
}

/** Number of filters that differ from the defaults (sort order not counted). */
export function activeFilterCount(f: TapeFilters): number {
  return [
    f.q.trim() !== "",
    f.ip !== "",
    f.severity.length > 0,
    f.technique !== "",
    f.login !== "any",
    f.status !== "all",
    f.range !== "all",
  ].filter(Boolean).length;
}

export function toggleSeverity(list: SeverityCode[], code: SeverityCode): SeverityCode[] {
  const next = list.includes(code) ? list.filter((c) => c !== code) : [...list, code];
  return SEVERITIES.filter((s) => next.includes(s));
}

/** "Today", "Yesterday" or e.g. "Wed 25 Nov 2026", using UTC days like the timestamps. */
export function dayLabel(iso: string, nowMs: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Unknown date";
  const day = Math.floor(t / (24 * HOUR));
  const today = Math.floor(nowMs / (24 * HOUR));
  if (day === today) return "Today";
  if (day === today - 1) return "Yesterday";
  return new Date(t).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "10:59:58" in UTC, for rows that sit under a day heading. */
export function timeOfDay(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "" : new Date(t).toISOString().slice(11, 19);
}
