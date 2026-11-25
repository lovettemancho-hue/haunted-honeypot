import type {
  ApiSeverity,
  ContainmentRule,
  SessionDetailResponse,
  SessionEvent,
  SessionListItem,
  SessionListResponse,
  SessionTechnique,
  StatsResponse,
} from "./types";

/**
 * Normalises Brain responses into the shapes the pages use. Accepts both the
 * real Brain shapes and the older flat shapes, and never throws on unknown input.
 */

type Rec = Record<string, unknown>;

function isRec(v: unknown): v is Rec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown, fallback = 0): number =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

/** "Class 5" or "Class_5" -> "Class_5". Unknown labels pass through with spaces replaced. */
export function normalizeSeverityLabel(label: string): ApiSeverity {
  return label.trim().replace(/\s+/g, "_") as ApiSeverity;
}

export function normalizeSeverity(raw: unknown): { severity: ApiSeverity; description: string | null } {
  if (typeof raw === "string") return { severity: normalizeSeverityLabel(raw), description: null };
  if (isRec(raw) && typeof raw.label === "string") {
    return {
      severity: normalizeSeverityLabel(raw.label),
      description: typeof raw.description === "string" ? raw.description : null,
    };
  }
  return { severity: "Unknown" as ApiSeverity, description: null };
}

export function normalizeStats(raw: unknown): StatsResponse {
  const r: Rec = isRec(raw) ? raw : {};
  return {
    attempts: num(r.attempts),
    unique_ips: num(r.unique_ips),
    captured: num(r.captured),
    longest_session_seconds: num(r.longest_session_seconds),
    threat_level: num(r.threat_level),
    top_passwords: r.top_passwords,
    technique_counts: r.technique_counts,
  };
}

export function normalizeSessionListItem(raw: unknown): SessionListItem | null {
  if (!isRec(raw) || typeof raw.id !== "string") return null;
  const { severity, description } = normalizeSeverity(raw.severity);
  const item: SessionListItem = {
    id: raw.id,
    src_ip: str(raw.src_ip),
    src_port: num(raw.src_port),
    username: strOrNull(raw.username),
    started_at: str(raw.started_at),
    ended_at: strOrNull(raw.ended_at),
    severity,
    open: raw.open === true,
    // Brain sends `techniques: string[]`; older shape was `attack_ids`.
    attack_ids: Array.isArray(raw.techniques) ? strList(raw.techniques) : strList(raw.attack_ids),
  };
  if (description !== null) item.severity_description = description;
  return item;
}

export function normalizeSessionList(raw: unknown): SessionListResponse {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((x) => {
    const item = normalizeSessionListItem(x);
    return item ? [item] : [];
  });
}

/** Payloads arrive as JSON objects; pages decode them from a JSON string. */
function payloadToString(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload === undefined || payload === null) return "";
  try {
    return JSON.stringify(payload) ?? "";
  } catch {
    return "";
  }
}

function normalizeEvent(raw: unknown, index: number): SessionEvent | null {
  if (!isRec(raw)) return null;
  return {
    id: typeof raw.id === "number" && Number.isFinite(raw.id) ? raw.id : -(index + 1),
    timestamp: str(raw.timestamp),
    kind: str(raw.kind, "unknown"),
    payload: payloadToString(raw.payload),
    generated_by: raw.generated_by === "llm" ? "llm" : "scripted",
  };
}

function normalizeTechnique(raw: unknown): SessionTechnique | null {
  if (!isRec(raw) || typeof raw.attack_id !== "string") return null;
  return {
    attack_id: raw.attack_id,
    name: str(raw.name),
    evidence_event_id: num(raw.evidence_event_id, -1),
  };
}

export function normalizeSessionDetail(raw: unknown): SessionDetailResponse {
  const r: Rec = isRec(raw) ? raw : {};
  const base = normalizeSessionListItem({ ...r, id: str(r.id) }) as SessionListItem;
  const events = Array.isArray(r.events)
    ? r.events.flatMap((e, i) => {
        const ev = normalizeEvent(e, i);
        return ev ? [ev] : [];
      })
    : [];
  const techniques = Array.isArray(r.techniques)
    ? r.techniques.flatMap((t) => {
        const tech = normalizeTechnique(t);
        return tech ? [tech] : [];
      })
    : [];
  return {
    ...base,
    attack_ids: techniques.length > 0 ? techniques.map((t) => t.attack_id) : base.attack_ids,
    password: strOrNull(r.password),
    client_version: str(r.client_version),
    events,
    techniques,
    lab_note: strOrNull(r.lab_note),
    iocs: strList(r.iocs),
  };
}

export function normalizeContainment(raw: unknown): ContainmentRule[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((x) => {
    if (!isRec(x) || typeof x.id !== "string") return [];
    return [
      {
        id: x.id,
        kind: str(x.kind),
        title: str(x.title),
        description: str(x.description),
        content: str(x.content),
        evidence_sessions: strList(x.evidence_sessions),
      },
    ];
  });
}
