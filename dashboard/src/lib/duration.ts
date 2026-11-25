const pad2 = (n: number): string => String(n).padStart(2, "0");

/** Format seconds as "HH:MM:SS". Invalid, non-finite or negative input gives "00:00:00". */
export function formatDuration(totalSeconds: number): string {
  if (typeof totalSeconds !== "number" || !Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "00:00:00";
  }
  const whole = Math.floor(totalSeconds);
  const hours = BigInt(Math.floor(whole / 3600)); // BigInt avoids "1e+21" notation for huge values
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  return `${String(hours).padStart(2, "0")}:${pad2(minutes)}:${pad2(seconds)}`;
}
