import { useCallback, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { fetchSessionDetail } from "../api/sessions";
import type { SessionDetailResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AttackerText } from "../components/AttackerText";
import { ConnectionLostBanner } from "../components/ConnectionLostBanner";
import { EmptyState } from "../components/EmptyState";
import { SeverityChip } from "../components/SeverityChip";
import { StitchedTag } from "../components/StitchedTag";
import { usePoller } from "../hooks/usePoller";
import { formatOffset } from "../lib/offset";
import { isStitched, sortEventsWithOffsets } from "../lib/replay";
import { terminalLine } from "../lib/terminal";
import { formatTimestamp } from "../lib/timestamp";
import { tapeHash } from "./TapeList";

const POLL_MS = 5000;

type NotFound = { notFound: true };
type Loaded = SessionDetailResponse & { notFound?: false };
type Result = Loaded | NotFound;

function isNotFound(r: Result): r is NotFound {
  return (r as NotFound).notFound === true;
}


/** Back control: always visible on the 404 state; on wide screens only needed on mobile via CSS. */
export function BackToTapes({ className }: { className?: string }) {
  return (
    <button
      type="button"
      className={`btn ${className ?? ""}`.trim()}
      onClick={() => {
        window.location.hash = tapeHash(null);
      }}
    >
      Back to tape list
    </button>
  );
}

function TerminalLine({ kind, payload }: { kind: string; payload: string }) {
  const line = terminalLine(kind, payload);
  return (
    <pre className={`tape-event__payload terminal-line terminal-line--${line.kind}${line.dim ? " terminal-line--dim" : ""}`}>
      {line.prefix ? <span className="terminal-line__prefix">{line.prefix}</span> : null}
      <AttackerText value={line.text} />
    </pre>
  );
}

export function TapeReplay({ id }: { id: string }) {
  const { token, onUnauthorized } = useAuth();
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const eventRefs = useRef(new Map<number, HTMLElement>());

  // usePoller ignores 4xx, so a 404 is turned into a sentinel here.
  const fetchFn = useCallback(async (): Promise<Result> => {
    try {
      return await fetchSessionDetail(token ?? "", onUnauthorized, id);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return { notFound: true };
      throw error;
    }
  }, [token, onUnauthorized, id]);

  const [stopped, setStopped] = useState(false);
  const { data, connectionLost } = usePoller(fetchFn, {
    intervalMs: POLL_MS,
    enabled: !stopped,
  });
  // Stop polling once the tape is closed or missing (enabled: tape.open semantics).
  if (data && !stopped && (isNotFound(data) || !data.open)) {
    setStopped(true);
  }

  if (data === null) {
    return (
      <section className="tape-replay" aria-label="Tape replay">
        <BackToTapes className="tape-back" />
        {connectionLost ? <ConnectionLostBanner /> : <p role="status">Loading tapeâ€¦</p>}
      </section>
    );
  }

  if (isNotFound(data)) {
    return (
      <section className="tape-replay" aria-label="Tape replay">
        <EmptyState title="Tape not found">
          No recorded session matches this link. It may have been removed.
        </EmptyState>
        <BackToTapes />
      </section>
    );
  }

  const events = sortEventsWithOffsets(data.events);
  const jumpTo = (eventId: number): void => {
    const el = eventRefs.current.get(eventId);
    setHighlightId(eventId);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <section className="tape-replay" aria-label="Tape replay">
      <BackToTapes className="tape-back" />
      {connectionLost ? <ConnectionLostBanner /> : null}
      <header className="tape-replay__header panel">
        <h2>Tape replay</h2>
        <dl className="tape-meta">
          <dt>Specimen IP</dt>
          <dd><AttackerText value={data.src_ip} /></dd>
          <dt>Port</dt>
          <dd>{data.src_port}</dd>
          <dt>Username</dt>
          <dd>{data.username ? <AttackerText value={data.username} /> : "â€”"}</dd>
          <dt>Started</dt>
          <dd>{formatTimestamp(data.started_at)}</dd>
          <dt>Ended</dt>
          <dd>{data.open ? "Still recording" : formatTimestamp(data.ended_at)}</dd>
          <dt>Severity</dt>
          <dd><SeverityChip severity={data.severity} description={data.severity_description} /></dd>
        </dl>
      </header>

      <section className="panel" aria-label="Field notes">
        <h3>Lab note</h3>
        {data.lab_note ? (
          <p className="tape-note"><AttackerText value={data.lab_note} /></p>
        ) : (
          <p className="tape-note tape-note--empty">No note yet. The field note has not been written for this tape.</p>
        )}
      </section>

      <section className="panel" aria-label="Techniques">
        <h3>Techniques</h3>
        {data.techniques.length === 0 ? (
          <p>No techniques identified yet.</p>
        ) : (
          <ul className="tape-techniques">
            {data.techniques.map((t) => (
              <li key={`${t.attack_id}-${t.evidence_event_id}`}>
                <button
                  type="button"
                  className="tag tape-technique"
                  onClick={() => jumpTo(t.evidence_event_id)}
                >
                  <AttackerText value={t.attack_id} /> <AttackerText value={t.name} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel" aria-label="Events">
        <h3>Events</h3>
        {events.length === 0 ? (
          <p>No events recorded yet.</p>
        ) : (
          <ol className="tape-events">
            {events.map((ev) => (
              <li
                key={ev.id}
                ref={(node) => {
                  if (node) eventRefs.current.set(ev.id, node);
                  else eventRefs.current.delete(ev.id);
                }}
                className={`tape-event${highlightId === ev.id ? " tape-event--highlight" : ""}`}
                data-event-id={ev.id}
                data-highlighted={highlightId === ev.id ? "true" : undefined}
              >
                <div className="tape-event__meta">
                  <span className="mono tape-event__offset">{formatOffset(ev.offsetMs)}</span>
                  <span className="tape-event__kind">{ev.kind}</span>
                  {isStitched(ev) ? <StitchedTag /> : null}
                </div>
                <TerminalLine kind={ev.kind} payload={ev.payload} />
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="panel" aria-label="Indicators of compromise">
        <h3>IOCs</h3>
        {data.iocs.length === 0 ? (
          <p>No indicators recorded.</p>
        ) : (
          <ul className="tape-iocs">
            {data.iocs.map((ioc, i) => (
              <li key={`${i}-${ioc}`}><AttackerText value={ioc} /></li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}


