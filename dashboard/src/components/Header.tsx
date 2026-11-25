import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { formatDuration } from "../lib/duration";

function BoltLogo() {
  return (
    <svg
      className="bolt-logo"
      width="28"
      height="28"
      viewBox="0 0 24 24"
      role="img"
      aria-label="Haunted Honeypot lightning bolt logo"
    >
      <path d="M13 2 4 14h6l-1 8 9-12h-6z" fill="var(--volt)" stroke="var(--copper)" strokeWidth="1" />
    </svg>
  );
}

/** Seconds since this component mounted, ticking once per second. */
function useUptimeSeconds(): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return seconds;
}

export function Header() {
  const { signOut } = useAuth();
  const uptime = useUptimeSeconds();
  return (
    <header className="app-header">
      <BoltLogo />
      <span className="rec-status">
        <span className="rec-dot" aria-hidden="true" />
        <span>REC · LAB 09</span>
        <span className="mono" title="Time this dashboard has been open">
          <span className="visually-hidden">Uptime </span>
          {formatDuration(uptime)}
        </span>
      </span>
      <span className="status-badge" title="The lab is running and recording">
        STATUS: IT'S ALIVE
      </span>
      <button type="button" className="btn header-signout" onClick={signOut}>
        Sign out
      </button>
    </header>
  );
}
