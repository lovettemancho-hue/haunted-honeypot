import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSessionSummary, setTapeReviewed, setTapesReviewed } from "../api/sessions";
import type { SessionListItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AttackerText } from "../components/AttackerText";
import { EmptyState } from "../components/EmptyState";
import { TapeFilterBar } from "../components/TapeFilterBar";
import { usePoller } from "../hooks/usePoller";
import {
  activeFilterCount,
  filtersToApiParams,
  hashPath,
  hashQuery,
  parseFilters,
  serializeFilters,
  type TapeFilters,
} from "../lib/tapeFilters";
import { formatTimestamp } from "../lib/timestamp";
import { TapeList, tapeHash } from "./TapeList";
import { TapeReplay } from "./TapeReplay";
import "../styles/lab-tapes.css";

const SUMMARY_POLL_MS = 10000;

function idFromHash(hash: string): string | null {
  const m = /^#\/tapes\/([^/]+)/.exec(hashPath(hash));
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)
  );
}

/** Tapes seen from one specimen IP: count and first/last visit. */
function SpecimenHistory({ ip, onShowAll }: { ip: string; onShowAll: () => void }) {
  const { token, onUnauthorized } = useAuth();
  const fetchFn = useCallback(
    () => fetchSessionSummary(token ?? "", onUnauthorized, new URLSearchParams({ ip })),
    [token, onUnauthorized, ip],
  );
  const { data } = usePoller(fetchFn, { intervalMs: 30000, enabled: true });
  if (!data || data.total < 2) return null;
  return (
    <p className="specimen-history">
      <span>
        This specimen (<AttackerText value={ip} />) has{" "}
        <strong>{data.total} tapes</strong>
        {data.first_seen && data.last_seen
          ? `, first seen ${formatTimestamp(data.first_seen)}, last seen ${formatTimestamp(data.last_seen)}`
          : ""}
        .
      </span>
      <button type="button" className="btn--link" onClick={onShowAll}>
        Show all its tapes
      </button>
    </p>
  );
}

/**
 * Lab Tapes page. `tapeId` (optional) selects a tape; when the prop is
 * omitted the selection follows `#/tapes/<id>` in the URL hash. Filters live
 * in the hash query (`#/tapes/<id>?sev=5`).
 */
export function LabTapes({ tapeId }: { tapeId?: string | null } = {}) {
  const { token, onUnauthorized } = useAuth();
  const [hashId, setHashId] = useState<string | null>(() => idFromHash(window.location.hash));
  const [filters, setFilters] = useState<TapeFilters>(() =>
    parseFilters(hashQuery(window.location.hash)),
  );
  useEffect(() => {
    const onChange = () => {
      setHashId(idFromHash(window.location.hash));
      const fromUrl = parseFilters(hashQuery(window.location.hash));
      setFilters((prev) => (serializeFilters(prev) === serializeFilters(fromUrl) ? prev : fromUrl));
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const selected = tapeId !== undefined ? tapeId : hashId;

  // Write filter changes back to the URL without adding history entries.
  const changeFilters = useCallback((next: TapeFilters) => {
    setFilters(next);
    const query = serializeFilters(next);
    const path = hashPath(window.location.hash) || "#/tapes";
    const target = `${path.startsWith("#/tapes") ? path : "#/tapes"}${query ? `?${query}` : ""}`;
    if (target !== window.location.hash) window.history.replaceState(null, "", target);
  }, []);
  const clearFilters = useCallback(() => changeFilters(parseFilters("")), [changeFilters]);

  // The minute-rounded "since" keeps the query stable between polls.
  const [nowMinute, setNowMinute] = useState(() => Math.floor(Date.now() / 60000));
  useEffect(() => {
    const t = setInterval(() => setNowMinute(Math.floor(Date.now() / 60000)), 60000);
    return () => clearInterval(t);
  }, []);
  const apiParams = useMemo(
    () => filtersToApiParams(filters, nowMinute * 60000),
    [filters, nowMinute],
  );
  const apiQuery = apiParams.toString();
  const listQuery = useMemo(() => {
    const p = new URLSearchParams(apiQuery);
    p.delete("order"); // order is applied by the list itself
    if (filters.order === "oldest") p.set("order", "oldest");
    return p.toString();
  }, [apiQuery, filters.order]);

  const summaryFetch = useCallback(
    () => fetchSessionSummary(token ?? "", onUnauthorized, new URLSearchParams(apiQuery)),
    [token, onUnauthorized, apiQuery],
  );
  const summary = usePoller(summaryFetch, { intervalMs: SUMMARY_POLL_MS, enabled: true });

  // Loaded tapes, for previous/next and bulk review.
  const [items, setItems] = useState<SessionListItem[]>([]);
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<{ text: string; undo?: () => void } | null>(null);
  const index = selected ? items.findIndex((s) => s.id === selected) : -1;
  const current = index >= 0 ? items[index] : undefined;
  const isReviewed = selected ? (overrides[selected] ?? current?.reviewed === true) : false;

  const go = useCallback((id: string | undefined) => {
    if (id) window.location.hash = tapeHash(id);
  }, []);
  const prevId = index > 0 ? items[index - 1]?.id : undefined;
  const nextId = index >= 0 ? items[index + 1]?.id : items[0]?.id;

  const markReviewed = useCallback(
    (id: string, reviewed: boolean) => {
      setOverrides((o) => ({ ...o, [id]: reviewed }));
      setTapeReviewed(token ?? "", onUnauthorized, id, reviewed)
        .then(() => summary.refetchNow())
        .catch(() => {
          setOverrides((o) => ({ ...o, [id]: !reviewed }));
          setNotice({ text: "Could not save the review mark. Check the connection and try again." });
        });
    },
    [token, onUnauthorized, summary],
  );

  const reviewAndNext = useCallback(() => {
    if (!selected) return;
    if (!isReviewed) markReviewed(selected, true);
    go(nextId);
  }, [selected, isReviewed, markReviewed, go, nextId]);

  const unreviewedShown = items.filter((s) => !(overrides[s.id] ?? s.reviewed === true));
  const markShown = useCallback(() => {
    const ids = unreviewedShown.map((s) => s.id);
    if (ids.length === 0) return;
    const apply = (value: boolean) =>
      setOverrides((o) => {
        const next = { ...o };
        for (const id of ids) next[id] = value;
        return next;
      });
    apply(true);
    setTapesReviewed(token ?? "", onUnauthorized, ids, true)
      .then(() => {
        summary.refetchNow();
        setNotice({
          text: `Marked ${ids.length} ${ids.length === 1 ? "tape" : "tapes"} as reviewed.`,
          undo: () => {
            apply(false);
            setNotice(null);
            setTapesReviewed(token ?? "", onUnauthorized, ids, false)
              .then(() => summary.refetchNow())
              .catch(() => undefined);
          },
        });
      })
      .catch(() => {
        apply(false);
        setNotice({ text: "Could not save the review marks. Try again." });
      });
  }, [unreviewedShown, token, onUnauthorized, summary]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 8000);
    return () => clearTimeout(t);
  }, [notice]);

  // Keyboard triage: J/K (or N/P) move between tapes, R toggles reviewed.
  const keyState = useRef({ prevId, nextId, selected, isReviewed, markReviewed, go });
  keyState.current = { prevId, nextId, selected, isReviewed, markReviewed, go };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target)) return;
      const s = keyState.current;
      const key = e.key.toLowerCase();
      if (key === "j" || key === "n") s.go(s.nextId);
      else if (key === "k" || key === "p") s.go(s.prevId);
      else if (key === "r" && s.selected) s.markReviewed(s.selected, !s.isReviewed);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Size the two panes to the space left under the header (desktop layout).
  const layoutRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = layoutRef.current;
    if (!el) return undefined;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      el.style.setProperty("--tapes-offset", `${Math.round(top)}px`);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // A newly opened tape starts at its top: the replay pane on desktop, the page on phones.
  const replayRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const pane = replayRef.current;
    if (!selected || !pane) return;
    pane.scrollTop = 0;
    if (window.matchMedia?.("(max-width: 899px)").matches && typeof pane.scrollIntoView === "function") {
      pane.scrollIntoView({ block: "start" });
    }
  }, [selected]);

  const filtered = activeFilterCount(filters) > 0;
  const position =
    index >= 0
      ? `${index + 1} of ${summary.data ? summary.data.total : items.length}`
      : null;

  return (
    <div className={`lab-tapes${selected ? " lab-tapes--selected" : ""}`}>
      <div className="lab-tapes__head">
        <h1>Lab Tapes</h1>
        <p>Replay what a specimen did, step by step.</p>
      </div>
      <div className="lab-tapes__layout" ref={layoutRef}>
        <aside className="lab-tapes__list" aria-label="Tapes and filters">
          <TapeFilterBar filters={filters} onChange={changeFilters} summary={summary.data} />
          {notice ? (
            <div className="tape-notice" role="status">
              <span>{notice.text}</span>
              {notice.undo ? (
                <button type="button" className="btn--link" onClick={notice.undo}>
                  Undo
                </button>
              ) : null}
            </div>
          ) : null}
          <TapeList
            key={listQuery}
            selectedId={selected}
            apiQuery={listQuery}
            oldestFirst={filters.order === "oldest"}
            reviewedOverrides={overrides}
            onItemsChange={setItems}
            filtered={filtered}
            onClearFilters={clearFilters}
          />
          {unreviewedShown.length > 1 ? (
            <div className="tape-list__bulk">
              <button type="button" className="btn" onClick={markShown}>
                Mark {unreviewedShown.length} shown as reviewed
              </button>
            </div>
          ) : null}
        </aside>
        <div className="lab-tapes__replay" ref={replayRef}>
          {selected ? (
            <>
              <div className="tape-toolbar" role="toolbar" aria-label="Tape actions">
                <button
                  type="button"
                  className="btn tape-toolbar__back"
                  onClick={() => {
                    window.location.hash = tapeHash(null);
                  }}
                >
                  ← List
                </button>
                <button type="button" className="btn" disabled={!prevId} onClick={() => go(prevId)} title="Previous tape (K)">
                  ↑ Prev
                </button>
                <button type="button" className="btn" disabled={!nextId || index < 0} onClick={() => go(nextId)} title="Next tape (J)">
                  ↓ Next
                </button>
                {position ? <span className="tape-toolbar__pos mono">{position}</span> : null}
                <span className="tape-toolbar__spacer" />
                <button
                  type="button"
                  className={`btn${isReviewed ? " btn--done" : ""}`}
                  aria-pressed={isReviewed}
                  onClick={() => markReviewed(selected, !isReviewed)}
                  title="Toggle reviewed (R)"
                >
                  {isReviewed ? "✓ Reviewed" : "Mark reviewed"}
                </button>
                {!isReviewed && nextId && index >= 0 ? (
                  <button type="button" className="btn btn--primary" onClick={reviewAndNext}>
                    Reviewed, next →
                  </button>
                ) : null}
              </div>
              {current ? (
                <SpecimenHistory
                  ip={current.src_ip}
                  onShowAll={() => changeFilters({ ...filters, ip: current.src_ip })}
                />
              ) : null}
              <TapeReplay key={selected} id={selected} />
            </>
          ) : (
            <EmptyState title="Select a tape">
              Choose a tape from the list to replay it. Tip: press J and K to move through tapes, and R
              to mark one as reviewed.
            </EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}

export default LabTapes;
