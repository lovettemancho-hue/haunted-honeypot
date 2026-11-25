export type Severity = "Class_1" | "Class_3" | "Class_5";

export type ContainedSpecimen = {
  ip: string;
  highestSeverity: Severity;
  tapeCount: number;
};

const RANK: Record<Severity, number> = { Class_1: 1, Class_3: 2, Class_5: 3 };

/**
 * Joins rule evidence ids to known sessions, drops ids with no matching
 * session, and groups the matches by source IP.
 */
export function deriveContainedSpecimens(
  rules: { evidence_sessions: string[] }[],
  sessions: { id: string; src_ip: string; severity: Severity }[],
): ContainedSpecimen[] {
  const evidenceIds = new Set<string>();
  for (const rule of rules) {
    for (const id of rule.evidence_sessions) evidenceIds.add(id);
  }

  const byId = new Map<string, { id: string; src_ip: string; severity: Severity }>();
  for (const s of sessions) if (!byId.has(s.id)) byId.set(s.id, s);

  const byIp = new Map<string, ContainedSpecimen>();
  for (const id of evidenceIds) {
    const session = byId.get(id);
    if (!session) continue;
    const existing = byIp.get(session.src_ip);
    if (!existing) {
      byIp.set(session.src_ip, {
        ip: session.src_ip,
        highestSeverity: session.severity,
        tapeCount: 1,
      });
    } else {
      existing.tapeCount += 1;
      if ((RANK[session.severity] ?? 0) > (RANK[existing.highestSeverity] ?? 0)) {
        existing.highestSeverity = session.severity;
      }
    }
  }
  return [...byIp.values()];
}
