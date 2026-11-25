/** Clamp a threat level to the integer range [0, 10]; non-finite maps to 0. */
export function clampVoltage(threatLevel: number): number {
  if (!Number.isFinite(threatLevel)) return 0;
  return Math.min(10, Math.max(0, Math.trunc(threatLevel)));
}

/** Plain-language description of a lab voltage level. */
export function voltageDescription(level: number): string {
  const v = clampVoltage(level);
  if (v === 0) return "Dormant: no attacker activity detected";
  if (v <= 3) return "Low activity: mostly automated probing";
  if (v <= 6) return "Elevated: attackers are actively poking around";
  return "Critical: serious attack behaviour captured";
}

/** Bar width as a percentage in [0, 100], proportional to the largest count. */
export function techniqueBarWidth(count: number, maxCount: number): number {
  if (!Number.isFinite(count) || !Number.isFinite(maxCount) || maxCount <= 0) {
    return 0;
  }
  const pct = (count / maxCount) * 100;
  return Math.min(100, Math.max(0, pct));
}
