import { decodePayload } from "./replay";

export const TERMINAL_PROMPT = "[root@records-srv-09 ~]# ";

export type TerminalLineKind = "command" | "output" | "download" | "login" | "status" | "other";

export interface TerminalLine {
  kind: TerminalLineKind;
  /** Static prefix written by the dashboard (never attacker text). */
  prefix: string;
  /** Attacker-influenced text; render only through AttackerText. */
  text: string;
  /** Dim status lines (session start/end). */
  dim: boolean;
}

function field(value: unknown, key: string): string | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const v = (value as Record<string, unknown>)[key];
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return String(v);
  }
  return null;
}

function fallbackText(value: unknown, raw: string): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value) ?? raw;
  } catch {
    return raw;
  }
}

/** Turns an event into a terminal-style line. Total: never throws. */
export function terminalLine(kind: string, payload: string): TerminalLine {
  const { value } = decodePayload(payload);
  switch (kind) {
    case "command":
      return {
        kind: "command",
        prefix: TERMINAL_PROMPT,
        text: field(value, "command") ?? fallbackText(value, payload),
        dim: false,
      };
    case "response":
      return {
        kind: "output",
        prefix: "",
        text: field(value, "output") ?? fallbackText(value, payload),
        dim: false,
      };
    case "download_attempt":
      return {
        kind: "download",
        prefix: "download attempt: ",
        text: field(value, "url") ?? fallbackText(value, payload),
        dim: false,
      };
    case "login_attempt": {
      const success = typeof value === "object" && value !== null && (value as Record<string, unknown>).success === true;
      const user = field(value, "username") ?? "?";
      const pass = field(value, "password") ?? "?";
      return {
        kind: "login",
        prefix: "",
        text: `login ${user} / ${pass} (${success ? "accepted" : "rejected"})`,
        dim: false,
      };
    }
    case "session_start": {
      const ip = field(value, "src_ip");
      const port = field(value, "src_port");
      const where = ip ? ` from ${ip}${port ? `:${port}` : ""}` : "";
      return { kind: "status", prefix: "", text: `-- session started${where} --`, dim: true };
    }
    case "session_end": {
      const reason = field(value, "reason");
      return { kind: "status", prefix: "", text: `-- session ended${reason ? ` (${reason})` : ""} --`, dim: true };
    }
    default:
      return { kind: "other", prefix: `${kind}: `, text: fallbackText(value, payload), dim: false };
  }
}
