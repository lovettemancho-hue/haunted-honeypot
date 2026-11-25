/** Shown while polling fails; the last received data stays on screen. */
export function ConnectionLostBanner() {
  return (
    <div className="connection-banner" role="alert">
      <span className="live-dot" aria-hidden="true" />{" "}
      Connection to the lab lost. Showing the last data received; retrying every 5 seconds.
    </div>
  );
}
