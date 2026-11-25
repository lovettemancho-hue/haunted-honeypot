export type ApiSeverity = "Class_1" | "Class_3" | "Class_5";

export interface StatsResponse {
  attempts: number;
  unique_ips: number;
  captured: number;
  longest_session_seconds: number;
  threat_level: number;
  top_passwords: unknown;
  technique_counts: unknown;
}

export interface SessionListItem {
  id: string;
  src_ip: string;
  src_port: number;
  username: string | null;
  started_at: string;
  ended_at: string | null;
  severity: ApiSeverity;
  open: boolean;
  attack_ids: string[];
}

export type SessionListResponse = SessionListItem[];

export interface SessionEvent {
  id: number;
  timestamp: string;
  kind: string;
  payload: string;
  generated_by: "scripted" | "llm";
}

export interface SessionTechnique {
  attack_id: string;
  name: string;
  evidence_event_id: number;
}

export interface SessionDetailResponse extends SessionListItem {
  password: string | null;
  client_version: string;
  events: SessionEvent[];
  techniques: SessionTechnique[];
  lab_note: string | null;
  iocs: string[];
}

export interface ContainmentRule {
  id: string;
  kind: string;
  title: string;
  description: string;
  content: string;
  evidence_sessions: string[];
}
