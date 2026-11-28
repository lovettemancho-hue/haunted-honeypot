import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSessions } from "../api/sessions";
import type { SessionListItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AttackerText } from "../components/AttackerText";
import { ConnectionLostBanner } from "../components/ConnectionLostBanner";
import { EmptyState } from "../components/EmptyState";
import { SeverityChip } from "../components/SeverityChip";
import { usePoller } from "../hooks/usePoller";
import { dayLabel, hashQuery, timeOfDay } from "../lib/tapeFilters";
import { formatTimestamp } from "../lib/timestamp";

export const PAGE_SIZE = 50;
const POLL_MS = 5000;

/** Hash for a tape (or the list), keeping the current filter query. */
export function tapeHash(id: string | null): string {
  const query = hashQuery(window.location.hash);
  const base = id === null ? "#/tapes" : `#/tapes/${encodeURIComponent(id)}`;
  return query ? `${base}?${query}` : base;
}

/** Newest first; ties keep a stable order by id. */
function byStartedDesc(a: SessionListItem, b: SessionListItem): number {
  const am = Date.parse(a.started_at);
  const bm = Date.parse(b.started_at);
  const an = Number.isNaN(am) ? 0 : am;
  const bn = Number.isNaN(bm) ? 0 : bm;
  return bn - an || a.id.localeCompare(b.id);
}

export interface TapeListProps {
  selectedId: string | null;
  /** Brain filter parameters; the list restarts from page one when they change. */
  apiQuery?: string;
  oldestFirst?: boolean;
  /** Review marks set in this browser session, applied over the server values. */
  reviewedOverrides?: Readonly<Record<string, boolean>>;
  /** Called with the loaded tapes in display order (for previous/next). */
  onItemsChange?: (items: SessionListItem[]) => void;
  /** True when filters are active, so the empty state can say so. */
  filtered?: boolean;
  onClearFilters?: () => void;
}

export function TapeList({
  selectedId,
  apiQuery = "",
  oldestFirst = false,
  reviewedOverrides,
  onItemsChange,
  filtered = false,
  onClearFilters,
}: TapeListProps) {
  const { token, onUnauthorized } = useAuth();
  const [extra, setExtra] = useState<SessionListItem[]>([]);
  const [lastPageLength, setLastPageLength] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const filters = useMemo(() => new URLSearchParams(apiQuery), [apiQuery]);

  const fetchFirst = useCallback(
    () => fetchSessions(token ?? "", onUnauthorized, { limit: PAGE_SIZE, offset: 0, filters }),
    [token, onUnauthorized, filters],
  );
  const { data: first, connectionLost } = usePoller(fetchFirst, {
    intervalMs: POLL_MS,
    enabled: true,
  });

  const items = useMemo(() => {
    const seen = new Set<string>();
    const merged: SessionListItem[] = [];
    for (const s of [...(first ?? []), ...extra]) {
      if (seen.has(s.id)) continue;
      seen.add(s.id);
      merged.push(s);
    }
    merged.sort(byStartedDesc);
    if (oldestFirst) merged.reverse();
    return merged;
  }, [first, extra, oldestFirst]);

  useEffect(() => {
    onItemsChange?.(items);
  }, [items, onItemsChange]);

  const pageLength = lastPageLength ?? first?.length ?? 0;
  const hasMore = first !== null && pageLength >= PAGE_SIZE;
  const itemCount = items.length;

  const loadMore = useCallback((): void => {
    if (loadingRef.current || !hasMore) return;
    loadingRef.current = true;
    setLoadingMore(true);
    fetchSessions(token ?? "", onUnauthorized, { limit: PAGE_SIZE, offset: itemCount, filters })
      .then((page) => {
        setExtra((prev) => [...prev, ...page]);
        setLastPageLength(page.length);
      })
      .catch(() => undefined)
      .finally(() => {
        loadingRef.current = false;
        setLoadingMore(false);
      });
  }, [hasMore, token, onUnauthorized, itemCount, filters]);

  const hasObserver = typeof IntersectionObserver !== "undefined";
  useEffect(() => {
    const node = sentinelRef.current;
    if (!hasObserver || !node || !hasMore) return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasObserver, hasMore, loadMore]);

  // Keep the selected row visible inside the list (e.g. after "next tape").
  useEffect(() => {
    if (!selectedId || !listRef.current) return;
    const row = Array.from(listRef.current.querySelectorAll<HTMLElement>("[data-tape-id]")).find(
      (el) => el.dataset.tapeId === selectedId,
    );
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }, [selectedId, items.length]);

  const nowMs = Date.now();
  let lastDay = "";

  return (
    <section className="tape-list" aria-label="Tape list">
      <h2 className="visually-hidden">Tapes</h2>
      {connectionLost ? <ConnectionLostBanner /> : null}
      {first !== null && items.length === 0 ? (
        filtered ? (
          <EmptyState title="No tapes match these filters">
            Try a wider date range or fewer filters.
            {onClearFilters ? (
              <>
                {" "}
                <button type="button" className="btn btn--link" onClick={onClearFilters}>
                  Clear filters
                </button>
              </>
            ) : null}
          </EmptyState>
        ) : (
          <EmptyState title="No tapes recorded yet">
            When a specimen connects to the trap, its session will appear here.
          </EmptyState>
        )
      ) : null}
      <ul className="tape-list__items" ref={listRef}>
        {items.map((s) => {
          const day = dayLabel(s.started_at, nowMs);
          const showDay = day !== lastDay;
          lastDay = day;
          const reviewed = reviewedOverrides?.[s.id] ?? s.reviewed === true;
          return (
            <Fragment key={s.id}>
              {showDay ? (
                <li className="tape-day" aria-hidden="true">
                  {day}
                </li>
              ) : null}
              <li data-tape-id={s.id}>
                <button
                  type="button"
                  className={`tape-row${reviewed ? " tape-row--reviewed" : ""}`}
                  aria-current={s.id === selectedId ? "true" : undefined}
                  onClick={() => {
                    window.location.hash = tapeHash(s.id);
                  }}
                >
                  <span className="tape-row__top">
                    <span className="tape-row__ip">
                      <AttackerText value={s.src_ip} />
                    </span>
                    <span className="tape-row__user">
                      {s.username ? <AttackerText value={s.username} /> : "—"}
                    </span>
                    <span className="tape-row__time" title={formatTimestamp(s.started_at)}>
                      <span className="visually-hidden">{day} </span>
                      {timeOfDay(s.started_at)}
                    </span>
                  </span>
                  <span className="tape-row__bottom">
                    <SeverityChip severity={s.severity} description={s.severity_description} />
                    {s.open ? <span className="tape-row__live">● Live</span> : null}
                    <span className="tape-row__attacks">
                      {s.attack_ids.map((a) => (
                        <span key={a} className="tag tape-tag">
                          <AttackerText value={a} />
                        </span>
                      ))}
                    </span>
                    {reviewed ? (
                      <span className="tape-row__reviewed" title="Reviewed">
                        ✓<span className="visually-hidden"> reviewed</span>
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            </Fragment>
          );
        })}
      </ul>
      {hasMore ? (
        <div ref={sentinelRef} className="tape-list__sentinel">
          {!hasObserver ? (
            <button type="button" className="btn" onClick={loadMore} disabled={loadingMore}>
              Load more tapes
            </button>
          ) : loadingMore ? (
            <span role="status">Loading more tapes…</span>
          ) : null}
        </div>
      ) : items.length > 0 ? (
        <p className="tape-list__end">End of the list.</p>
      ) : null}
    </section>
  );
}
