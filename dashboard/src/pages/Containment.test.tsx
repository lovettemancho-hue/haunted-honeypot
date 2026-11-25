import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ContainmentRule, SessionListItem } from "../api/types";
import { CHECKLIST_ITEMS } from "../lib/checklist";
import { json, renderPage, stubFetch } from "../test/pageHelpers";
import { Containment } from "./Containment";

const RULES: ContainmentRule[] = [
  {
    id: "r1",
    kind: "firewall",
    title: "Block brute-forcers",
    description: "Drops repeat offenders.",
    content: "iptables -A INPUT -s 198.51.100.7 -j DROP",
    evidence_sessions: ["s1", "s2"],
  },
  {
    id: "r2",
    kind: "sshd_config",
    title: "Disable passwords",
    description: "Keys only.",
    content: "PasswordAuthentication no",
    evidence_sessions: ["s3"],
  },
];

function sess(id: string, ip: string, severity: SessionListItem["severity"]): SessionListItem {
  return {
    id,
    src_ip: ip,
    src_port: 1,
    username: null,
    started_at: "2024-05-01T10:00:00Z",
    ended_at: null,
    severity,
    open: false,
    attack_ids: [],
  };
}

const SESSIONS = [
  sess("s1", "198.51.100.7", "Class_1"),
  sess("s2", "198.51.100.7", "Class_5"),
  sess("s3", "203.0.113.5", "Class_3"),
  sess("unrelated", "192.0.2.1", "Class_5"),
];

function setup(rules: ContainmentRule[] = RULES, script: () => Response = () => new Response("#!/bin/sh\n")) {
  return stubFetch((path) => {
    if (path === "/api/containment") return json(rules);
    if (path === "/api/containment?format=script") return script();
    if (path.startsWith("/api/sessions")) return json(SESSIONS);
    return json({}, 404);
  });
}

function setClipboard(writeText: (t: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
}

describe("Containment", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  });

  it("updates checklist progress as items are toggled", async () => {
    setup();
    renderPage(<Containment />);
    const total = CHECKLIST_ITEMS.length;
    expect(screen.getByText(`0 of ${total} steps done`)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(CHECKLIST_ITEMS[0].label));
    fireEvent.click(screen.getByLabelText(CHECKLIST_ITEMS[1].label));
    expect(screen.getByText(`2 of ${total} steps done`)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(CHECKLIST_ITEMS[0].label));
    expect(screen.getByText(`1 of ${total} steps done`)).toBeTruthy();
    expect((screen.getByLabelText(CHECKLIST_ITEMS[1].label) as HTMLInputElement).checked).toBe(true);
    await screen.findByText("Block brute-forcers");
  });

  it("renders rule cards with kind, evidence count and content", async () => {
    setup();
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    const cards = document.querySelectorAll(".rule-card");
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain("Kind: firewall");
    expect(cards[0].textContent).toContain("Evidence: 2 sessions");
    expect(cards[1].textContent).toContain("Evidence: 1 session");
    expect(cards[0].textContent).toContain("iptables -A INPUT -s 198.51.100.7 -j DROP");
  });

  it("copies rule content and shows a success message", async () => {
    setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    fireEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]);
    await screen.findByText("Copied to clipboard.");
    expect(writeText).toHaveBeenCalledWith("iptables -A INPUT -s 198.51.100.7 -j DROP");
  });

  it("shows a failure message when copying is rejected", async () => {
    setup();
    setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    fireEvent.click(screen.getAllByRole("button", { name: "Copy" })[1]);
    await screen.findByText(/Copying failed/);
  });

  it("shows a failure message when the clipboard API is unavailable", async () => {
    setup();
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    fireEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]);
    await screen.findByText(/Copying failed/);
  });

  it("downloads the script as containment.sh", async () => {
    const mock = setup();
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    let downloadName = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloadName = this.download;
    });
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    fireEvent.click(screen.getByRole("button", { name: /Download script/ }));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake"));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(downloadName).toBe("containment.sh");
    const urls = mock.mock.calls.map((c) => String(c[0]));
    expect(urls).toContain("/api/containment?format=script");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an error message when the download fails", async () => {
    setup(RULES, () => new Response("", { status: 500 }));
    const createObjectURL = vi.fn(() => "blob:fake");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    renderPage(<Containment />);
    await screen.findByText("Block brute-forcers");
    fireEvent.click(screen.getByRole("button", { name: /Download script/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Download failed/);
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("disables download and shows an empty state when there are no rules", async () => {
    setup([]);
    renderPage(<Containment />);
    await screen.findByText("No containment rules yet");
    const button = screen.getByRole("button", { name: /Download script/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("No contained specimens yet")).toBeTruthy();
  });

  it("lists contained specimens joined from rule evidence, with the highest class", async () => {
    setup();
    renderPage(<Containment />);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    const text = rows.map((r) => r.textContent ?? "");
    expect(rows).toHaveLength(2);
    expect(text.find((t) => t.includes("198.51.100.7"))).toMatch(/Class 52$/);
    expect(text.find((t) => t.includes("203.0.113.5"))).toMatch(/Class 31$/);
    expect(text.some((t) => t.includes("192.0.2.1"))).toBe(false);
  });
});
