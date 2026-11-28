import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionListItem } from "../api/types";
import { fetchedPaths, json, renderPage, stubFetch } from "../test/pageHelpers";
import { LabTapes } from "./LabTapes";

function item(n: number, over: Partial<SessionListItem> = {}): Record<string, unknown> {
  return {
    id: `id-${n}`,
    src_ip: `192.0.2.${n}`,
    src_port: 1000 + n,
    username: `user-${n}`,
    started_at: `2024-05-01T10:${String(59 - n).padStart(2, "0")}:00Z`,
    ended_at: "2024-05-01T11:00:00Z",
    severity: { label: "Class 1", description: "Low" },
    open: false,
    techniques: [],
    reviewed: false,
    ...over,
  };
}

const SUMMARY = {
  total: 3,
  unreviewed: 3,
  by_severity: { "Class 1": 2, "Class 3": 0, "Class 5": 1 },
  by_technique: { T1110: 2 },
  first_seen: null,
  last_seen: null,
};

const DETAIL = {
  ...item(1),
  password: null,
  client_version: "x",
  events: [],
  techniques: [],
  lab_note: null,
  iocs: [],
};

function router(path: string): Response {
  if (path.startsWith("/api/sessions/summary")) return json(SUMMARY);
  if (path.startsWith("/api/sessions?")) return json([item(1), item(2), item(3)]);
  if (path.startsWith("/api/sessions/review")) return json({ updated: 3, reviewed: true });
  if (/\/review$/.test(path)) return json({ updated: 1, reviewed: true });
  return json({ ...DETAIL, id: decodeURIComponent(path.split("/").pop() ?? "") });
}

describe("Lab Tapes triage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.location.hash = "#/tapes";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows counts on the severity filters and sends filters to the Brain", async () => {
    const mock = stubFetch(router);
    renderPage(<LabTapes />);
    const class5 = await screen.findByRole("button", { name: /Class 5\s*1/ });
    fireEvent.click(class5);
    expect(class5.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() =>
      expect(fetchedPaths(mock)).toContain("/api/sessions?limit=50&offset=0&severity=5"),
    );
    expect(window.location.hash).toBe("#/tapes?sev=5");
    fireEvent.click(screen.getByRole("button", { name: "To review" }));
    await waitFor(() =>
      expect(fetchedPaths(mock)).toContain(
        "/api/sessions?limit=50&offset=0&severity=5&reviewed=false",
      ),
    );
    expect(screen.getByText(/3 tapes · 3 to review/)).toBeTruthy();
  });

  it("reads filters from the URL on load and keeps them when a tape is opened", async () => {
    window.location.hash = "#/tapes?status=unreviewed&tech=T1110";
    const mock = stubFetch(router);
    renderPage(<LabTapes />);
    fireEvent.click(await screen.findByRole("button", { name: /user-2/ }));
    expect(window.location.hash).toBe("#/tapes/id-2?status=unreviewed&tech=T1110");
    expect(fetchedPaths(mock)).toContain(
      "/api/sessions?limit=50&offset=0&technique=T1110&reviewed=false",
    );
  });

  it("debounces search and can clear all filters", async () => {
    const mock = stubFetch(router);
    renderPage(<LabTapes />);
    const box = await screen.findByRole("searchbox");
    fireEvent.change(box, { target: { value: "192.0" } });
    await waitFor(() => expect(fetchedPaths(mock)).toContain("/api/sessions?limit=50&offset=0&q=192.0"));
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(window.location.hash).toBe("#/tapes");
  });

  it("moves between tapes and marks one reviewed, by button and keyboard", async () => {
    window.location.hash = "#/tapes/id-1";
    const mock = stubFetch(router);
    renderPage(<LabTapes />);
    await screen.findByRole("button", { name: /user-3/ });
    await screen.findByText("1 of 3");
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(window.location.hash).toBe("#/tapes/id-2");
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await screen.findByText("2 of 3");
    fireEvent.keyDown(window, { key: "r" });
    await waitFor(() =>
      expect(mock.mock.calls.some((c) => String(c[0]) === "/api/sessions/id-2/review")).toBe(true),
    );
    const call = mock.mock.calls.find((c) => String(c[0]) === "/api/sessions/id-2/review");
    expect((call?.[1] as RequestInit).method).toBe("PUT");
    expect((call?.[1] as RequestInit).body).toBe(JSON.stringify({ reviewed: true }));
    expect(screen.getByRole("button", { name: "✓ Reviewed" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "k" });
    expect(window.location.hash).toBe("#/tapes/id-1");
  });

  it("ignores triage keys while typing in the search box", async () => {
    window.location.hash = "#/tapes/id-1";
    stubFetch(router);
    renderPage(<LabTapes />);
    await screen.findByText("1 of 3");
    fireEvent.keyDown(screen.getByRole("searchbox"), { key: "j" });
    expect(window.location.hash).toBe("#/tapes/id-1");
  });

  it("marks every shown tape reviewed in one request, with undo", async () => {
    const mock = stubFetch(router);
    renderPage(<LabTapes />);
    fireEvent.click(await screen.findByRole("button", { name: "Mark 3 shown as reviewed" }));
    await screen.findByText("Marked 3 tapes as reviewed.");
    const bulk = mock.mock.calls.filter((c) => String(c[0]) === "/api/sessions/review");
    expect(JSON.parse(String((bulk[0]?.[1] as RequestInit).body))).toEqual({
      ids: ["id-1", "id-2", "id-3"],
      reviewed: true,
    });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(mock.mock.calls.filter((c) => String(c[0]) === "/api/sessions/review")).toHaveLength(2),
    );
  });

  it("says when no tapes match the filters", async () => {
    window.location.hash = "#/tapes?sev=5";
    stubFetch((p) => (p.startsWith("/api/sessions?") ? json([]) : router(p)));
    renderPage(<LabTapes />);
    await screen.findByText("No tapes match these filters");
  });
});
