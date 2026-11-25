/** Format an ISO 8601 string as "YYYY-MM-DD HH:MM:SS UTC", or "—" for missing/invalid input. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (typeof iso !== "string" || iso === "") return "—";
  const date = new Date(iso);
  const time = date.getTime();
  if (Number.isNaN(time)) return "—";
  try {
    const s = date.toISOString(); // throws RangeError for out-of-range dates
    return `${s.slice(0, 10)} ${s.slice(11, 19)} UTC`;
  } catch {
    return "—";
  }
}
