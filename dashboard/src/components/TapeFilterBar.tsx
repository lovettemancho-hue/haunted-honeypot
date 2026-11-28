import { useEffect, useId, useState } from "react";
import type { SessionSummary } from "../api/types";
import {
  activeFilterCount,
  DEFAULT_FILTERS,
  toggleSeverity,
  type DateRange,
  type LoginFilter,
  type ReviewStatus,
  type SeverityCode,
  type SortOrder,
  type TapeFilters,
} from "../lib/tapeFilters";
import { TECHNIQUE_NAMES } from "../lib/techniques";
import { AttackerText } from "./AttackerText";

const SEARCH_DEBOUNCE_MS = 300;

const SEVERITY_BUTTONS: ReadonlyArray<{ code: SeverityCode; label: string; hint: string }> = [
  { code: "5", label: "Class 5", hint: "Got in and tried to install, persist or mine" },
  { code: "3", label: "Class 3", hint: "Got in and looked around" },
  { code: "1", label: "Class 1", hint: "Only guessed passwords" },
];

const STATUS_OPTIONS: ReadonlyArray<{ value: ReviewStatus; label: string }> = [
  { value: "all", label: "All" },
  { value: "unreviewed", label: "To review" },
  { value: "reviewed", label: "Reviewed" },
];


export interface TapeFilterBarProps {
  filters: TapeFilters;
  onChange: (next: TapeFilters) => void;
  summary: SessionSummary | null;
}

export function TapeFilterBar({ filters, onChange, summary }: TapeFilterBarProps) {
  const id = useId();
  const set = (patch: Partial<TapeFilters>): void => onChange({ ...filters, ...patch });

  // Search is typed locally and sent after a short pause.
  const [search, setSearch] = useState(filters.q);
  useEffect(() => setSearch(filters.q), [filters.q]);
  useEffect(() => {
    if (search === filters.q) return undefined;
    const t = setTimeout(() => onChange({ ...filters, q: search }), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [search, filters, onChange]);

  const advanced =
    (filters.technique ? 1 : 0) +
    (filters.login !== "any" ? 1 : 0) +
    (filters.range !== "all" ? 1 : 0) +
    (filters.order !== "newest" ? 1 : 0);
  const [open, setOpen] = useState(advanced > 0);
  const active = activeFilterCount(filters);
  const techniques = summary?.by_technique ?? [];
  const techniqueListed = techniques.some((t) => t.id === filters.technique);

  return (
    <div className="tape-filters" role="search" aria-label="Filter tapes">
      <label className="visually-hidden" htmlFor={`${id}-q`}>
        Search by IP address or username
      </label>
      <input
        id={`${id}-q`}
        className="tape-filters__search"
        type="search"
        placeholder="Search IP or username…"
        value={search}
        maxLength={100}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="tape-filters__row" role="group" aria-label="Severity">
        {SEVERITY_BUTTONS.map((b) => {
          const count = summary?.by_severity[b.label];
          return (
            <button
              key={b.code}
              type="button"
              className={`filter-chip filter-chip--sev${b.code}`}
              aria-pressed={filters.severity.includes(b.code)}
              title={b.hint}
              onClick={() => set({ severity: toggleSeverity(filters.severity, b.code) })}
            >
              {b.label}
              {count !== undefined ? <span className="filter-chip__count">{count}</span> : null}
            </button>
          );
        })}
      </div>

      <div className="tape-filters__row segmented" role="group" aria-label="Review status">
        {STATUS_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            className="segmented__btn"
            aria-pressed={filters.status === o.value}
            onClick={() => set({ status: o.value })}
          >
            {o.label}
          </button>
        ))}
      </div>

      {filters.ip ? (
        <div className="tape-filters__row">
          <span className="filter-pill">
            Specimen <AttackerText value={filters.ip} />
            <button
              type="button"
              className="filter-pill__x"
              aria-label="Remove specimen filter"
              onClick={() => set({ ip: "" })}
            >
              ×
            </button>
          </span>
        </div>
      ) : null}

      <button
        type="button"
        className="tape-filters__more"
        aria-expanded={open}
        aria-controls={`${id}-more`}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▾" : "▸"} More filters{advanced > 0 ? ` (${advanced})` : ""}
      </button>

      <div id={`${id}-more`} className="tape-filters__more-body" hidden={!open}>
        <label className="tape-filters__field">
          <span>When</span>
          <select
            value={filters.range}
            onChange={(e) => set({ range: e.target.value as DateRange })}
          >
            <option value="all">Any time</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="custom">Pick dates…</option>
          </select>
        </label>
        {filters.range === "custom" ? (
          <div className="tape-filters__dates">
            <label className="tape-filters__field">
              <span>From</span>
              <input type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => set({ from: e.target.value })} />
            </label>
            <label className="tape-filters__field">
              <span>To</span>
              <input type="date" value={filters.to} min={filters.from || undefined} onChange={(e) => set({ to: e.target.value })} />
            </label>
            <p className="tape-filters__note">Dates are in UTC, like the tape timestamps.</p>
          </div>
        ) : null}
        <label className="tape-filters__field">
          <span>Technique</span>
          <select value={filters.technique} onChange={(e) => set({ technique: e.target.value })}>
            <option value="">Any technique</option>
            {filters.technique && !techniqueListed ? (
              <option value={filters.technique}>{filters.technique}</option>
            ) : null}
            {techniques.map((t) => (
              <option key={t.id} value={t.id}>
                {t.id}
                {TECHNIQUE_NAMES[t.id] ? ` ${TECHNIQUE_NAMES[t.id]}` : ""} ({t.count})
              </option>
            ))}
          </select>
        </label>
        <label className="tape-filters__field">
          <span>Login</span>
          <select value={filters.login} onChange={(e) => set({ login: e.target.value as LoginFilter })}>
            <option value="any">Any outcome</option>
            <option value="yes">Got in</option>
            <option value="no">Did not get in</option>
          </select>
        </label>
        <label className="tape-filters__field">
          <span>Order</span>
          <select value={filters.order} onChange={(e) => set({ order: e.target.value as SortOrder })}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
      </div>

      <div className="tape-filters__summary" aria-live="polite">
        <span>
          {summary
            ? `${summary.total} ${summary.total === 1 ? "tape" : "tapes"} · ${summary.unreviewed} to review`
            : "Counting tapes…"}
        </span>
        {active > 0 || filters.order !== "newest" ? (
          <button type="button" className="btn--link" onClick={() => onChange(DEFAULT_FILTERS)}>
            Clear filters
          </button>
        ) : null}
      </div>
    </div>
  );
}
