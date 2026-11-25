import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LabMonitor } from "../pages/LabMonitor";
import { TapeList } from "../pages/TapeList";
import { TapeReplay } from "../pages/TapeReplay";
import { Containment } from "../pages/Containment";
import { json, renderPage, stubFetch } from "../test/pageHelpers";
import {
  normalizeContainment,
  normalizeSessionDetail,
  normalizeSessionList,
  normalizeSeverity,
  normalizeStats,
} from "./adapter";
import containmentFixture from "./__fixtures__/brain-containment.json";
import detailFixture from "./__fixtures__/brain-session-detail.json";
import sessionsFixture from "./__fixtures__/brain-sessions.json";
import statsFixture from "./__fixtures__/brain-stats.json";

const DETAIL_ID = detailFixture.id;

function routeFixtures() {
  return stubFetch((path) => {
    if (path.startsWith("/api/stats")) return json(statsFixture);
    if (path.startsWith(`/api/sessions/${DETAIL_ID}`)) return json(detailFixture);
    if (path.startsWith("/api/sessions")) return json(sessionsFixture);
    if (path.startsWith("/api/containment")) return json(containmentFixture);
    return json({}, 404);
  });
}

describe("adapter: fixtures", () => {
  it("maps severity objects to Severity ids and keeps the description", () => {
    expect(normalizeSeverity({ label: "Class 5", description: "d" })).toEqual({
      severity: "Class_5",
      description: "d",
    });
    expect(normalizeSeverity("Class_3").severity).toBe("Class_3");
    expect(normalizeSeverity(undefined).description).toBeNull();
  });

  it("normalises the session list (techniques -> attack_ids)", () => {
    const list = normalizeSessionList(sessionsFixture);
    expect(list).toHaveLength(sessionsFixture.length);
    expect(list[0].severity).toBe("Class_5");
    expect(list[0].severity_description).toMatch(/^High:/);
    expect(list[0].attack_ids).toEqual(sessionsFixture[0].techniques);
  });

  it("normalises the session detail (payload objects become JSON text)", () => {
    const d = normalizeSessionDetail(detailFixture);
    expect(d.severity).toBe("Class_5");
    expect(d.events).toHaveLength(detailFixture.events.length);
    for (const ev of d.events) expect(typeof ev.payload).toBe("string");
    expect(JSON.parse(d.events[2].payload)).toEqual({ command: "whoami" });
    expect(d.techniques[0].attack_id).toBe("T1078");
  });

  it("normalises stats and containment", () => {
    expect(normalizeStats(statsFixture).threat_level).toBe(8);
    expect(normalizeContainment(containmentFixture)).toHaveLength(containmentFixture.length);
  });

  it("never throws on unknown shapes", () => {
    for (const bad of [null, undefined, 1, "x", [], {}, [null, 1, {}], { events: "no", techniques: 3 }]) {
      expect(() => normalizeStats(bad)).not.toThrow();
      expect(() => normalizeSessionList(bad)).not.toThrow();
      expect(() => normalizeSessionDetail(bad)).not.toThrow();
      expect(() => normalizeContainment(bad)).not.toThrow();
    }
    expect(normalizeSessionList({ nope: true })).toEqual([]);
  });
});

describe("contract: pages render Brain fixtures", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.location.hash = "";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("LabMonitor", async () => {
    routeFixtures();
    renderPage(<LabMonitor />);
    expect((await screen.findAllByTestId("log-row")).length).toBe(sessionsFixture.length);
    expect(screen.getAllByText("Class 5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("T1078").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ubuntu").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Class 5")[0].getAttribute("title")).toMatch(/^High:/);
  });

  it("TapeList", async () => {
    routeFixtures();
    const { container } = renderPage(<TapeList selectedId={null} />);
    await screen.findByText("ubuntu");
    expect(container.querySelectorAll(".tape-row")).toHaveLength(sessionsFixture.length);
  });

  it("TapeReplay renders events like a terminal", async () => {
    routeFixtures();
    const { container } = renderPage(<TapeReplay id={DETAIL_ID} />);
    await screen.findByText("whoami");
    const text = container.textContent ?? "";
    expect(text).toContain("[root@records-srv-09 ~]# ");
    expect(text).toContain("login root / 123456 (accepted)");
    expect(text).toContain("-- session started from 127.0.0.1:52764 --");
    expect(text).toContain("-- session ended (exit) --");
    expect(text).toContain("Segmentation fault (core dumped)");
    // download_attempt shows only a defanged URL; no live scheme anywhere.
    expect(text).toContain("download attempt: hxxp://198[.]51[.]100[.]77/xmrig");
    expect(text).not.toMatch(/https?:\/\//);
    expect(container.querySelector("a[href]")).toBeNull();
    expect(container.querySelector(".tag-stitched")).toBeNull();
    const rows = container.querySelectorAll(".tape-event");
    expect(rows).toHaveLength(detailFixture.events.length);
    expect(within(container.querySelector(".tape-meta") as HTMLElement).getByText("Class 5").getAttribute("title")).toMatch(/^High:/);
  });

  it("TapeReplay marks llm-generated events as stitched and escapes text", async () => {
    stubFetch((path) =>
      json({
        ...detailFixture,
        events: [
          { id: 1, timestamp: "2026-11-25T18:46:07Z", kind: "command", payload: { command: "<img src=x onerror=alert(1)>" }, generated_by: "scripted" },
          { id: 2, timestamp: "2026-11-25T18:46:08Z", kind: "response", payload: { output: "<b>made up</b>" }, generated_by: "llm" },
        ],
        path,
      }),
    );
    const { container } = renderPage(<TapeReplay id="x" />);
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.querySelectorAll(".tag-stitched")).toHaveLength(1);
    expect(container.querySelector(".tape-events img, .tape-events b")).toBeNull();
  });

  it("Containment", async () => {
    routeFixtures();
    renderPage(<Containment />);
    await screen.findByText("Harden sshd logins");
    expect(screen.getByText("Block outbound mining port 3333")).toBeTruthy();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(1);
  });
});


