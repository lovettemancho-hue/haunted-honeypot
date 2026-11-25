import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionListItem } from "../api/types";
import { json, renderPage, stubFetch } from "../test/pageHelpers";
import { LabMonitor } from "./LabMonitor";

function session(over: Partial<SessionListItem>): SessionListItem {
  return {
    id: "s1",
    src_ip: "198.51.100.7",
    src_port: 4000,
    username: "root",
    started_at: "2024-05-01T10:00:00Z",
    ended_at: "2024-05-01T10:01:05Z",
    severity: "Class_5",
    open: false,
    attack_ids: [],
    ...over,
  };
}

const STATS = {
  attempts: 1234,
  unique_ips: 56,
  captured: 7,
  longest_session_seconds: 3725,
  threat_level: 4,
  top_passwords: [
    { password: "hunter2", count: 9 },
    { password: "admin", count: 3 },
  ],
  technique_counts: { T1110: 8, T1059: 2 },
};

function routeWith(stats: unknown, sessions: unknown) {
  return stubFetch((path) => {
    if (path.startsWith("/api/stats")) return json(stats);
    if (path.startsWith("/api/sessions")) return json(sessions);
    return json({}, 404);
  });
}

function cardValue(label: string): string {
  const card = screen.getByText(label).parentElement as HTMLElement;
  return card.textContent ?? "";
}

describe("LabMonitor", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.location.hash = "";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the four stat cards with formatted values", async () => {
    routeWith(STATS, []);
    renderPage(<LabMonitor />);
    await waitFor(() => expect(cardValue("Login attempts")).toContain("1234"));
    expect(cardValue("Unique attacker IPs")).toContain("56");
    expect(cardValue("Captured sessions (Tapes)")).toContain("7");
    expect(cardValue("Longest session")).toContain("01:02:05");
  });

  it("renders the log columns and row values", async () => {
    routeWith(STATS, [session({})]);
    renderPage(<LabMonitor />);
    const row = await screen.findByTestId("log-row");
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Started", "Specimen IP", "Username", "Severity", "Duration", "Status"]);
    const cells = within(row).getAllByRole("cell");
    expect(cells[0].textContent).toBe("2024-05-01 10:00:00 UTC");
    expect(cells[1].textContent).toContain("198.51.100.7");
    expect(cells[2].textContent).toContain("root");
    expect(cells[3].textContent).toBe("Class 5");
    expect(cells[4].textContent).toBe("00:01:05");
    expect(cells[5].textContent).toBe("Closed");
  });

  it("navigates to the tape when a row is clicked", async () => {
    routeWith(STATS, [session({ id: "abc 1" })]);
    renderPage(<LabMonitor />);
    const row = await screen.findByTestId("log-row");
    fireEvent.click(within(row).getAllByRole("cell")[2]);
    expect(window.location.hash).toBe("#/tapes/abc%201");
  });

  it("navigates with the keyboard (Enter) on a focused row", async () => {
    routeWith(STATS, [session({ id: "k1" })]);
    renderPage(<LabMonitor />);
    const row = await screen.findByTestId("log-row");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(window.location.hash).toBe("#/tapes/k1");
  });

  it("marks open sessions as live and closed ones as closed", async () => {
    routeWith(STATS, [
      session({ id: "open", open: true, ended_at: null, started_at: new Date().toISOString() }),
      session({ id: "done" }),
    ]);
    renderPage(<LabMonitor />);
    await screen.findAllByTestId("log-row");
    expect(screen.getByText(/Live \(session still open\)/)).toBeTruthy();
    expect(screen.getByText("Closed")).toBeTruthy();
  });

  it("shows the empty state when there are zero sessions", async () => {
    routeWith(STATS, []);
    renderPage(<LabMonitor />);
    await screen.findByText("No experiments yet");
    expect(screen.queryByTestId("log-row")).toBeNull();
  });

  it("shows technique and password panels from valid stats", async () => {
    routeWith(STATS, []);
    renderPage(<LabMonitor />);
    await screen.findByText("T1110");
    expect(screen.getByText("T1059")).toBeTruthy();
    expect(screen.getByText("hunter2")).toBeTruthy();
    expect(screen.queryByText("No techniques detected yet")).toBeNull();
    expect(screen.queryByText("No passwords captured yet")).toBeNull();
  });

  it("shows empty states for both panels when stat shapes are malformed", async () => {
    routeWith({ ...STATS, top_passwords: "oops", technique_counts: 42 }, [session({})]);
    renderPage(<LabMonitor />);
    await screen.findByText("No techniques detected yet");
    expect(screen.getByText("No passwords captured yet")).toBeTruthy();
    // other panels are unaffected
    expect(cardValue("Login attempts")).toContain("1234");
    expect(screen.getByTestId("log-row")).toBeTruthy();
  });

  it("keeps each panel independent: malformed passwords do not hide techniques", async () => {
    routeWith({ ...STATS, top_passwords: { nested: { x: 1 } } }, []);
    renderPage(<LabMonitor />);
    await screen.findByText("T1110");
    expect(screen.getByText("No passwords captured yet")).toBeTruthy();
  });

  it("links the containment call-out to #/containment", async () => {
    routeWith(STATS, []);
    renderPage(<LabMonitor />);
    const link = await screen.findByRole("link", { name: /open containment/i });
    expect(link.getAttribute("href")).toBe("#/containment");
  });
});
