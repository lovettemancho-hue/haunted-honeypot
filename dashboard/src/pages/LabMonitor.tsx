import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { fetchSessions, fetchSessionSummary } from "../api/sessions";
import { fetchStats } from "../api/stats";
import type { SessionListItem } from "../api/types";
import { tapeHref, tapesHref } from "../routes";
import { useAuth } from "../auth/AuthContext";
import { AttackerText } from "../components/AttackerText";
import { ConnectionLostBanner } from "../components/ConnectionLostBanner";
import { EmptyState } from "../components/EmptyState";
import { SeverityChip } from "../components/SeverityChip";
import { VoltageMeter } from "../components/VoltageMeter";
import { usePoller } from "../hooks/usePoller";
import { formatDuration } from "../lib/duration";
import { parseTechniqueCounts, parseTopPasswords } from "../lib/statParsers";
import { TECHNIQUE_NAMES } from "../lib/techniques";
import { formatTimestamp } from "../lib/timestamp";
import { techniqueBarWidth } from "../lib/voltage";
import "../styles/lab-monitor.css";

const POLL_MS = 5000;
const SESSIONS_LIMIT = 50;
const TOP_PASSWORDS_MAX = 10;
/** The monitor shows only the latest tapes; Lab Tapes has the full, filterable list. */
const LOG_ROWS = 10;

function sessionSeconds(s: SessionListItem, nowMs: number): number {
  const start = Date.parse(s.started_at);
  const end = s.open || !s.ended_at ? nowMs : Date.parse(s.ended_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return (end - start) / 1000;
}

function openTape(id: string): void {
  window.location.hash = tapeHref(id);
}

function SessionRow({ session, nowMs }: { session: SessionListItem; nowMs: number }) {
  const onKeyDown = (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openTape(session.id);
    }
  };
  return (
    <tr
      className="log-row"
      tabIndex={0}
      onClick={() => openTape(session.id)}
      onKeyDown={onKeyDown}
      data-testid="log-row"
    >
      <td className="mono">{formatTimestamp(session.started_at)}</td>
      <td>
        <a
          href={tapeHref(session.id)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Open Tape for ${session.src_ip}`}
        >
          <AttackerText value={session.src_ip} />
        </a>
      </td>
      <td>{session.username ? <AttackerText value={session.username} /> : <span>—</span>}</td>
      <td>
        <SeverityChip severity={session.severity} description={session.severity_description} />
      </td>
      <td className="mono">{formatDuration(sessionSeconds(session, nowMs))}</td>
      <td>
        {session.open ? (
          <span className="log-status log-status--live">
            <span className="live-dot" aria-hidden="true" /> Live (session still open)
          </span>
        ) : (
          <span className="log-status">Closed</span>
        )}
      </td>
    </tr>
  );
}

export function LabMonitor() {
  const { token, onUnauthorized } = useAuth();
  const enabled = token !== null;

  const statsFetch = useCallback(
    () => fetchStats(token ?? "", onUnauthorized),
    [token, onUnauthorized],
  );
  const sessionsFetch = useCallback(
    () => fetchSessions(token ?? "", onUnauthorized, { limit: SESSIONS_LIMIT, offset: 0 }),
    [token, onUnauthorized],
  );
  const summaryFetch = useCallback(
    () => fetchSessionSummary(token ?? "", onUnauthorized),
    [token, onUnauthorized],
  );
  const stats = usePoller(statsFetch, { intervalMs: POLL_MS, enabled });
  const summary = usePoller(summaryFetch, { intervalMs: POLL_MS * 2, enabled });
  const sessions = usePoller(sessionsFetch, { intervalMs: POLL_MS, enabled });
  const connectionLost = stats.connectionLost || sessions.connectionLost;

  const sessionList = useMemo<SessionListItem[]>(
    () => (Array.isArray(sessions.data) ? sessions.data : []),
    [sessions.data],
  );
  const hasOpen = sessionList.some((s) => s.open);

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    setNowMs(Date.now());
    if (!hasOpen) return undefined;
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [hasOpen, sessions.data]);

  const s = stats.data;
  const techniques = useMemo(() => parseTechniqueCounts(s?.technique_counts), [s]);
  const passwords = useMemo(
    () =>
      parseTopPasswords(s?.top_passwords)
        .slice()
        .sort((a, b) => b.count - a.count)
        .slice(0, TOP_PASSWORDS_MAX),
    [s],
  );
  const maxTechnique = techniques.reduce((m, t) => Math.max(m, t.count), 0);

  return (
    <div className="lab-monitor">
      <h1>Lab Monitor</h1>
      <p className="lab-monitor__intro">Live overview of attacks caught by the trap.</p>
      {connectionLost ? <ConnectionLostBanner /> : null}

      <section className="panel panel--stitched" aria-labelledby="lm-voltage">
        <h2 id="lm-voltage">Lab voltage</h2>
        {s ? (
          <VoltageMeter level={s.threat_level} />
        ) : (
          <EmptyState title="Waiting for data">Reading the lab voltage…</EmptyState>
        )}
      </section>

      <section className="lab-monitor__stats" aria-label="Key numbers">
        <div className="panel stat-card">
          <p className="stat-card__label">Login attempts</p>
          <p className="stat-card__value mono">{s ? s.attempts : "—"}</p>
        </div>
        <div className="panel stat-card">
          <p className="stat-card__label">Unique attacker IPs</p>
          <p className="stat-card__value mono">{s ? s.unique_ips : "—"}</p>
        </div>
        <div className="panel stat-card">
          <p className="stat-card__label">Break-ins (got past login)</p>
          <p className="stat-card__value mono">{s ? s.captured : "—"}</p>
          {s && s.captured > 0 ? (
            <a className="stat-card__link" href={tapesHref({ login: "yes" })}>
              See the break-ins →
            </a>
          ) : null}
        </div>
        <div className="panel stat-card">
          <p className="stat-card__label">Longest session</p>
          <p className="stat-card__value mono">{s ? formatDuration(s.longest_session_seconds) : "—"}</p>
        </div>
      </section>

      <section className="panel" aria-labelledby="lm-log">
        <h2 id="lm-log">Experiment log</h2>
        <p className="lab-monitor__hint">Recent attack sessions (Tapes). Select a row to replay it.</p>
        {summary.data && summary.data.unreviewed > 0 ? (
          <p className="review-callout">
            <span>
              <strong className="mono">{summary.data.unreviewed}</strong> of {summary.data.total} tapes
              waiting for review
              {summary.data.by_severity["Class 5"]
                ? ` (${summary.data.by_severity["Class 5"]} Class 5 in total)`
                : ""}
              .
            </span>
            <a className="btn" href={tapesHref({ status: "unreviewed" })}>
              Start reviewing →
            </a>
          </p>
        ) : null}
        {sessionList.length === 0 ? (
          <EmptyState title="No experiments yet">
            <p className="quiet-line">The lab is quiet... for now.</p>No attacker has connected yet. Sessions will appear here as they arrive.
          </EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="log-table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Specimen IP</th>
                  <th scope="col">Username</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {sessionList.slice(0, LOG_ROWS).map((row) => (
                  <SessionRow key={row.id} session={row} nowMs={nowMs} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {sessionList.length > LOG_ROWS ? (
          <p className="lab-monitor__more">
            <a href="#/tapes">See all tapes in Lab Tapes →</a>
          </p>
        ) : null}
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="lm-tech">
          <h2 id="lm-tech">ATT&amp;CK techniques</h2>
          <p className="lab-monitor__hint">
            Known attacker behaviours (MITRE ATT&amp;CK) seen so far. Select one to see its tapes.
          </p>
          {techniques.length === 0 ? (
            <EmptyState title="No techniques detected yet">
              Behaviours will be listed once attackers do something recognisable.
            </EmptyState>
          ) : (
            <ul className="bar-list">
              {techniques.map((t) => (
                <li key={t.label} className="bar-list__item">
                  <a
                    className="bar-list__id mono"
                    href={tapesHref({ technique: t.label })}
                    title={`Show tapes with ${t.label}`}
                  >
                    <AttackerText value={t.label} />
                    {TECHNIQUE_NAMES[t.label] ? (
                      <span className="bar-list__name"> {TECHNIQUE_NAMES[t.label]}</span>
                    ) : null}
                  </a>
                  <span className="bar-list__track" aria-hidden="true">
                    <span
                      className="bar-list__fill"
                      style={{ width: `${techniqueBarWidth(t.count, maxTechnique)}%` }}
                    />
                  </span>
                  <span className="bar-list__count mono">{t.count}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel" aria-labelledby="lm-pass">
          <h2 id="lm-pass">Top passwords</h2>
          <p className="lab-monitor__hint">Passwords attackers tried most often.</p>
          {passwords.length === 0 ? (
            <EmptyState title="No passwords captured yet">
              Guessed passwords will be ranked here.
            </EmptyState>
          ) : (
            <ol className="pass-list">
              {passwords.map((p) => (
                <li key={p.label} className="pass-list__item">
                  <AttackerText value={p.label} />
                  <span className="pass-list__count mono">{p.count}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <section className="panel panel--stitched lab-monitor__callout" aria-labelledby="lm-contain">
        <h2 id="lm-contain">Containment</h2>
        <p>Hardening rules are ready. They protect your real server from what the trap has seen.</p>
        <a className="btn btn--primary" href="#/containment">
          Pull the lever: open Containment
        </a>
      </section>
    </div>
  );
}

