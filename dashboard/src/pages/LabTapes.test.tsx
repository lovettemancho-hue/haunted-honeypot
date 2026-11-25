import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionDetailResponse, SessionListItem } from "../api/types";
import { fetchedPaths, json, renderPage, stubFetch } from "../test/pageHelpers";
import { LabTapes } from "./LabTapes";

function item(n: number, over: Partial<SessionListItem> = {}): SessionListItem {
  const minute = String(n % 60).padStart(2, "0");
  return {
    id: `id-${n}`,
    src_ip: `192.0.2.${n % 250}`,
    src_port: 1000 + n,
    username: `user-${n}`,
    started_at: `2024-05-01T10:${minute}:00Z`,
    ended_at: null,
    severity: "Class_3",
    open: false,
    attack_ids: [],
    ...over,
  };
}

function detail(over: Partial<SessionDetailResponse> = {}): SessionDetailResponse {
  return {
    ...item(1),
    id: "abc",
    src_ip: "203.0.113.9",
    src_port: 51234,
    username: "mallory",
    started_at: "2024-05-01T10:00:00Z",
    ended_at: "2024-05-01T10:05:00Z",
    severity: "Class_5",
    open: false,
    password: "pw",
    client_version: "SSH-2.0-x",
    events: [
      { id: 2, timestamp: "2024-05-01T10:00:02.500Z", kind: "response", payload: "\"uid=0(root)\"", generated_by: "llm" },
      { id: 1, timestamp: "2024-05-01T10:00:01Z", kind: "command", payload: "id", generated_by: "scripted" },
      { id: 3, timestamp: "2024-05-01T10:00:04Z", kind: "command", payload: "ls /tmp", generated_by: "scripted" },
    ],
    techniques: [{ attack_id: "T1033", name: "System Owner Discovery", evidence_event_id: 3 }],
    lab_note: "The specimen probed the host.",
    iocs: ["hxxp://evil[.]example/x.sh"],
    ...over,
  };
}

function userOrder(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(".tape-row__user")).map((n) => n.textContent ?? "");
}

describe("LabTapes list", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.location.hash = "#/tapes";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("orders tapes by started_at descending", async () => {
    stubFetch(() => json([item(5), item(30), item(12)]));
    const { container } = renderPage(<LabTapes />);
    await screen.findByText("user-30");
    expect(userOrder(container)).toEqual(["user-30", "user-12", "user-5"]);
  });

  it("shows an empty state and a select prompt with no tapes", async () => {
    stubFetch(() => json([]));
    renderPage(<LabTapes />);
    await screen.findByText("No tapes recorded yet");
    expect(screen.getByText("Select a tape")).toBeTruthy();
  });

  it("fetches the first page with limit 50 and offset 0", async () => {
    const mock = stubFetch(() => json([item(1)]));
    renderPage(<LabTapes />);
    await screen.findByText("user-1");
    expect(fetchedPaths(mock)[0]).toBe("/api/sessions?limit=50&offset=0");
  });

  it("loads the second page with offset 50 and appends it", async () => {
    const firstPage = Array.from({ length: 50 }, (_, i) => item(i + 1));
    const secondPage = [item(55), item(56)];
    const mock = stubFetch((path) => {
      if (path.includes("offset=50")) return json(secondPage);
      return json(firstPage);
    });
    const { container } = renderPage(<LabTapes />);
    const more = await screen.findByRole("button", { name: "Load more tapes" });
    fireEvent.click(more);
    await screen.findByText("user-56");
    expect(fetchedPaths(mock)).toContain("/api/sessions?limit=50&offset=50");
    expect(container.querySelectorAll(".tape-row")).toHaveLength(52);
    // a short second page means there is nothing more to load
    expect(screen.queryByRole("button", { name: "Load more tapes" })).toBeNull();
  });

  it("selects a tape by setting the hash when a row is clicked", async () => {
    stubFetch(() => json([item(7)]));
    renderPage(<LabTapes />);
    fireEvent.click(await screen.findByRole("button", { name: /user-7/ }));
    expect(window.location.hash).toBe("#/tapes/id-7");
  });
});

describe("LabTapes replay", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.location.hash = "#/tapes/abc";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function route(d: SessionDetailResponse | null) {
    return stubFetch((path) => {
      if (path.startsWith("/api/sessions?")) return json([item(1)]);
      if (path === "/api/sessions/abc") return d ? json(d) : json({ detail: "nope" }, 404);
      return json({}, 404);
    });
  }

  it("shows header fields, lab note, events in order with offsets, and IOCs", async () => {
    route(detail());
    renderPage(<LabTapes />);
    const replay = await screen.findByRole("region", { name: "Tape replay" });
    const meta = replay.querySelector(".tape-meta") as HTMLElement;
    expect(meta.textContent).toContain("203.0.113.9");
    expect(meta.textContent).toContain("51234");
    expect(meta.textContent).toContain("mallory");
    expect(meta.textContent).toContain("2024-05-01 10:00:00 UTC");
    expect(meta.textContent).toContain("2024-05-01 10:05:00 UTC");
    expect(meta.textContent).toContain("Class 5");
    expect(screen.getByText("The specimen probed the host.")).toBeTruthy();
    const events = Array.from(replay.querySelectorAll(".tape-event"));
    expect(events.map((e) => e.getAttribute("data-event-id"))).toEqual(["1", "2", "3"]);
    expect(events[0].textContent).toContain("+0.000 s");
    expect(events[1].textContent).toContain("+1.500 s");
    expect(events[2].textContent).toContain("+3.000 s");
    expect(screen.getByText("hxxp://evil[.]example/x.sh")).toBeTruthy();
  });

  it("shows a 'no note yet' message when the lab note is missing", async () => {
    route(detail({ lab_note: null }));
    renderPage(<LabTapes />);
    await screen.findByText(/No note yet/);
  });

  it("shows the Stitched tag only on LLM-generated events", async () => {
    route(detail());
    renderPage(<LabTapes />);
    await screen.findByRole("region", { name: "Tape replay" });
    const tagged = document.querySelectorAll(".tape-event .tag-stitched");
    expect(tagged).toHaveLength(1);
    const ev = tagged[0].closest(".tape-event") as HTMLElement;
    expect(ev.getAttribute("data-event-id")).toBe("2");
    expect(within(ev).getByText("Stitched")).toBeTruthy();
  });

  it("scrolls to and highlights the evidence event when a technique tag is clicked", async () => {
    route(detail());
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: scroll,
    });
    renderPage(<LabTapes />);
    fireEvent.click(await screen.findByRole("button", { name: /T1033/ }));
    expect(scroll).toHaveBeenCalledTimes(1);
    const target = scroll.mock.contexts[0] as HTMLElement;
    expect(target.getAttribute("data-event-id")).toBe("3");
    expect(target.getAttribute("data-highlighted")).toBe("true");
    expect(target.className).toContain("tape-event--highlight");
  });

  it("shows 'Tape not found' with a back control on 404", async () => {
    route(null);
    renderPage(<LabTapes />);
    await screen.findByText("Tape not found");
    fireEvent.click(screen.getByRole("button", { name: "Back to tape list" }));
    expect(window.location.hash).toBe("#/tapes");
  });

  it("does not poll the tape once it is closed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const mock = route(detail({ open: false }));
    renderPage(<LabTapes />);
    await screen.findByRole("region", { name: "Tape replay" });
    const detailCalls = () => fetchedPaths(mock).filter((p) => p === "/api/sessions/abc").length;
    expect(detailCalls()).toBe(1);
    await act(async () => {
      vi.advanceTimersByTime(20000);
    });
    expect(detailCalls()).toBe(1);
  });

  it("keeps polling an open tape", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const mock = route(detail({ open: true, ended_at: null }));
    renderPage(<LabTapes />);
    await screen.findByText("Still recording");
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    const calls = fetchedPaths(mock).filter((p) => p === "/api/sessions/abc").length;
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it("uses stacked view classes at phone width: list hidden, replay shown, back control present", async () => {
    route(detail());
    const { container } = renderPage(<LabTapes />);
    await screen.findByRole("region", { name: "Tape replay" });
    // jsdom has no media queries, so assert the classes the 640px CSS rules key on.
    const root = container.querySelector(".lab-tapes") as HTMLElement;
    expect(root.classList.contains("lab-tapes--selected")).toBe(true);
    expect(root.querySelector(".lab-tapes__list")).toBeTruthy();
    expect(root.querySelector(".lab-tapes__replay")).toBeTruthy();
    const back = root.querySelector(".lab-tapes__replay .tape-back") as HTMLElement;
    expect(back.textContent).toBe("Back to tape list");
  });

  it("uses the list-only class when no tape is selected", async () => {
    window.location.hash = "#/tapes";
    route(detail());
    const { container } = renderPage(<LabTapes />);
    await screen.findByText("user-1");
    const root = container.querySelector(".lab-tapes") as HTMLElement;
    expect(root.classList.contains("lab-tapes--selected")).toBe(false);
    expect(root.querySelector(".tape-replay")).toBeNull();
  });
});
