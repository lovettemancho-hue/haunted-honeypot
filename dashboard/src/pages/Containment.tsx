import { useCallback, useMemo, useState } from "react";
import { fetchContainment, fetchContainmentScript } from "../api/containment";
import { fetchSessions } from "../api/sessions";
import { tapeHref } from "../routes";
import { AttackerText } from "../components/AttackerText";
import { ConnectionLostBanner } from "../components/ConnectionLostBanner";
import { EmptyState } from "../components/EmptyState";
import { SeverityChip } from "../components/SeverityChip";
import { useAuth } from "../auth/AuthContext";
import { usePoller } from "../hooks/usePoller";
import {
  CHECKLIST_ITEMS,
  progressCount,
  toggleItem,
  type ChecklistState,
} from "../lib/checklist";
import { deriveContainedSpecimens } from "../lib/containmentSpecimens";
import "../styles/containment.css";

const POLL_MS = 5000;
const SESSIONS_LIMIT = 200;
const SCRIPT_FILENAME = "containment.sh";

type CopyStatus = { ruleId: string; ok: boolean } | null;

function initialChecklist(): ChecklistState {
  const state: ChecklistState = {};
  for (const item of CHECKLIST_ITEMS) state[item.id] = false;
  return state;
}

/** Opens the first tape that triggered a rule, so the reason for it can be checked. */
function EvidenceLink({ ids }: { ids: string[] }) {
  const id = ids[0];
  if (!id) return null;
  return (
    <>
      {" · "}
      <a href={tapeHref(id)}>Replay the evidence →</a>
    </>
  );
}

export function Containment() {
  const { token, onUnauthorized } = useAuth();
  const [checklist, setChecklist] = useState<ChecklistState>(initialChecklist);
  const [copyStatus, setCopyStatus] = useState<CopyStatus>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const enabled = token !== null;
  const fetchRules = useCallback(
    () => fetchContainment(token ?? "", onUnauthorized),
    [token, onUnauthorized],
  );
  const fetchSessionList = useCallback(
    () => fetchSessions(token ?? "", onUnauthorized, { limit: SESSIONS_LIMIT, offset: 0 }),
    [token, onUnauthorized],
  );

  const rulesPoll = usePoller(fetchRules, { intervalMs: POLL_MS, enabled });
  const sessionsPoll = usePoller(fetchSessionList, { intervalMs: POLL_MS, enabled });
  const rules = rulesPoll.data;
  const sessions = sessionsPoll.data;
  const connectionLost = rulesPoll.connectionLost || sessionsPoll.connectionLost;

  const specimens = useMemo(
    () => (rules && sessions ? deriveContainedSpecimens(rules, sessions) : []),
    [rules, sessions],
  );

  const onCopy = (ruleId: string, content: string): void => {
    const write = (): Promise<void> => {
      if (!navigator.clipboard) return Promise.reject(new Error("Clipboard unavailable"));
      return navigator.clipboard.writeText(content);
    };
    write().then(
      () => setCopyStatus({ ruleId, ok: true }),
      () => setCopyStatus({ ruleId, ok: false }),
    );
  };

  const onDownload = (): void => {
    if (token === null) return;
    setDownloading(true);
    setDownloadError(null);
    fetchContainmentScript(token, onUnauthorized).then(
      (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = SCRIPT_FILENAME;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setDownloading(false);
      },
      () => {
        setDownloadError("Download failed. The hardening script could not be fetched. Try again.");
        setDownloading(false);
      },
    );
  };

  const hasRules = rules !== null && rules.length > 0;
  const checked = progressCount(checklist);

  return (
    <div className="containment">
      <h1>Containment</h1>
      <p className="containment__intro">
        Hardening rules generated from what the specimens did, ready to protect your real server.
        Nothing is applied automatically.
      </p>
      {connectionLost ? <ConnectionLostBanner /> : null}

      <section className="panel panel--stitched containment__section" aria-labelledby="checklist-heading">
        <h2 id="checklist-heading">Hardening checklist</h2>
        <p className="containment__progress" aria-live="polite">
          {checked} of {CHECKLIST_ITEMS.length} steps done
        </p>
        <ul className="checklist">
          {CHECKLIST_ITEMS.map((item) => {
            const inputId = `check-${item.id}`;
            return (
              <li key={item.id} className="checklist__row panel-inset">
                <input
                  id={inputId}
                  type="checkbox"
                  className="checklist__box"
                  checked={checklist[item.id] === true}
                  onChange={() => setChecklist((s) => toggleItem(s, item.id))}
                />
                <div>
                  <label htmlFor={inputId} className="checklist__label">
                    {item.label}
                  </label>
                  <p className="checklist__desc">{item.description}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="panel panel--stitched containment__section" aria-labelledby="rules-heading">
        <div className="containment__rules-head">
          <h2 id="rules-heading">Generated rules</h2>
          <button
            type="button"
            className="btn btn--primary"
            onClick={onDownload}
            disabled={!hasRules || downloading}
          >
            Download script (.sh)
          </button>
        </div>
        {downloadError ? (
          <p className="form-message" role="alert">
            {downloadError}
          </p>
        ) : null}
        {hasRules ? (
          <ul className="rule-list">
            {rules.map((rule) => (
              <li key={rule.id} className="rule-card panel-inset">
                <h3 className="rule-card__title">
                  <AttackerText value={rule.title} />
                </h3>
                <p className="rule-card__meta">
                  Kind: <AttackerText value={rule.kind} /> · Evidence: {rule.evidence_sessions.length}{" "}
                  {rule.evidence_sessions.length === 1 ? "session" : "sessions"}
                  <EvidenceLink ids={rule.evidence_sessions} />
                </p>
                <p className="rule-card__desc">
                  <AttackerText value={rule.description} />
                </p>
                <pre className="terminal rule-card__content" tabIndex={0}>
                  <AttackerText value={rule.content} />
                </pre>
                <div className="rule-card__actions">
                  <button type="button" onClick={() => onCopy(rule.id, rule.content)}>
                    Copy
                  </button>
                  {copyStatus && copyStatus.ruleId === rule.id ? (
                    <span role="status" className="rule-card__status">
                      {copyStatus.ok
                        ? "Copied to clipboard."
                        : "Copying failed. Select the text above and copy it manually."}
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No containment rules yet">
            Rules appear once specimens have attacked the trap and enough evidence is captured.
          </EmptyState>
        )}
      </section>

      <section className="panel panel--stitched containment__section" aria-labelledby="specimens-heading">
        <h2 id="specimens-heading">Contained specimens</h2>
        <p className="containment__intro">
          Specimens (attacker addresses) that the rules above are built from.
        </p>
        {specimens.length > 0 ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">IP</th>
                  <th scope="col">Highest class</th>
                  <th scope="col">Tapes</th>
                </tr>
              </thead>
              <tbody>
                {specimens.map((s) => (
                  <tr key={s.ip}>
                    <td>
                      <AttackerText value={s.ip} />
                    </td>
                    <td>
                      <SeverityChip severity={s.highestSeverity} />
                    </td>
                    <td className="mono">{s.tapeCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No contained specimens yet" />
        )}
      </section>
    </div>
  );
}
