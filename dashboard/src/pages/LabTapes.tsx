import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { TapeList } from "./TapeList";
import { TapeReplay } from "./TapeReplay";
import "../styles/lab-tapes.css";

function idFromHash(hash: string): string | null {
  const m = /^#\/tapes\/([^/]+)/.exec(hash);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

/**
 * Lab Tapes page. `tapeId` (optional) selects a tape; when the prop is
 * omitted the selection follows `#/tapes/<id>` in the URL hash.
 */
export function LabTapes({ tapeId }: { tapeId?: string | null } = {}) {
  const [hashId, setHashId] = useState<string | null>(() => idFromHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setHashId(idFromHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const selected = tapeId !== undefined ? tapeId : hashId;

  return (
    <div className={`lab-tapes${selected ? " lab-tapes--selected" : ""}`}>
      <h1>Lab Tapes</h1>
      <p>Replay what a specimen did, step by step.</p>
      <div className="lab-tapes__layout">
        <div className="lab-tapes__list">
          <TapeList selectedId={selected} />
        </div>
        <div className="lab-tapes__replay">
          {selected ? (
            <TapeReplay key={selected} id={selected} />
          ) : (
            <EmptyState title="Select a tape">Choose a tape from the list to replay it.</EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}

export default LabTapes;
