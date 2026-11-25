/** Format a millisecond offset as "+S.mmm s". Negative or non-finite input is treated as 0. */
export function formatOffset(ms: number): string {
  const safe = typeof ms === "number" && Number.isFinite(ms) && ms > 0 ? Math.round(ms) : 0;
  const seconds = Math.floor(safe / 1000);
  const millis = safe % 1000;
  return `+${seconds}.${String(millis).padStart(3, "0")} s`;
}
