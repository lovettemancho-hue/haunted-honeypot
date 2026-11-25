import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSessions } from "../api/sessions";
import type { SessionListItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AttackerText } from "../components/AttackerText";
import { ConnectionLostBanner } from "../components/ConnectionLostBanner";
import { EmptyState } from "../components/EmptyState";
import { SeverityChip } from "../components/SeverityChip";
import { usePoller } from "../hooks/usePoller";
import { formatTimestamp } from "../lib/timestamp";

export const PAGE_SIZE = 50;
const POLL_MS = 5000;

export function tapeHash(id: string | null): string {
  return id === null ? "#/tapes" : `#/tapes/${encodeURIComponent(id)}`;
}

/** Newest first; ties keep a stable order by id. */
function byStartedDesc(a: SessionListItem, b: SessionListItem): number {
  const am = Date.parse(a.started_at);
  const bm = Date.parse(b.started_at);
  const an = Number.isNaN(am) ? 0 : am;
  const bn = Number.isNaN(bm) ? 0 : bm;
  return bn - an || a.id.localeCompare(b.id);
}

export function TapeList({ selectedId }: { selectedId: string | null }) {
  const { token, onUnauthorized } = useAuth();
  const [extra, setExtra] = useState<SessionListItem[]>([]);
  const [lastPageLength, setLastPageLength] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const fetchFirst = useCallback(
    () => fetchSessions(token ?? "", onUnauthorized, { limit: PAGE_SIZE, offset: 0 }),
    [token, onUnauthorized],
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
    return merged.sort(byStartedDesc);
  }, [first, extra]);

  const pageLength = lastPageLength ?? first?.length ?? 0;
  const hasMore = first !== null && pageLength >= PAGE_SIZE;
  const itemCount = items.length;

  const loadMore = useCallback((): void => {
    if (loadingRef.current || !hasMore) return;
    loadingRef.current = true;
    setLoadingMore(true);
    fetchSessions(token ?? "", onUnauthorized, { limit: PAGE_SIZE, offset: itemCount })
      .then((page) => {
        setExtra((prev) => [...prev, ...page]);
        setLastPageLength(page.length);
      })
      .catch(() => undefined)
      .finally(() => {
        loadingRef.current = false;
        setLoadingMore(false);
      });
  }, [hasMore, token, onUnauthorized, itemCount]);

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

  return (
    <section className="tape-list" aria-label="Tape list">
      <h2>Tapes</h2>
      <p className="tape-list__hint">Recorded attack sessions (experiments), newest first.</p>
      {connectionLost ? <ConnectionLostBanner /> : null}
      {first !== null && items.length === 0 ? (
        <EmptyState title="No tapes recorded yet">
          When a specimen connects to the trap, its session will appear here.
        </EmptyState>
      ) : null}
      <ul className="tape-list__items">
        {items.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              className="tape-row"
              aria-current={s.id === selectedId ? "true" : undefined}
              onClick={() => {
                window.location.hash = tapeHash(s.id);
              }}
            >
              <span className="tape-row__ip">
                <AttackerText value={s.src_ip} />
              </span>
              <span className="tape-row__user">
                {s.username ? <AttackerText value={s.username} /> : "—"}
              </span>
              <span className="tape-row__time">{formatTimestamp(s.started_at)}</span>
              <SeverityChip severity={s.severity} description={s.severity_description} />
              <span className="tape-row__attacks">
                {s.attack_ids.map((a) => (
                  <span key={a} className="tag tape-tag">
                    <AttackerText value={a} />
                  </span>
                ))}
              </span>
            </button>
          </li>
        ))}
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
      ) : null}
    </section>
  );
}

