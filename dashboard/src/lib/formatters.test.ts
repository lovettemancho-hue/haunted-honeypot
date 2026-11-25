import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { formatDuration } from "./duration";
import { formatOffset } from "./offset";
import { mapSeverity, severityChipVariant } from "./severity";
import { formatTimestamp } from "./timestamp";

const RUNS = { numRuns: 200 };

describe("Feature: dashboard, Property 18: Duration formatting is total and correctly bounded", () => {
  // **Validates: Requirements 9.1**
  it("always matches HH:MM:SS and returns zeros for negative / NaN / non-finite input", () => {
    fc.assert(
      fc.property(fc.double({ noNaN: false }), (n) => {
        const out = formatDuration(n);
        expect(out).toMatch(/^\d{2,}:\d{2}:\d{2}$/);
        if (!Number.isFinite(n) || n < 0) expect(out).toBe("00:00:00");
      }),
      RUNS,
    );
  });

  it("returns the exact zero-padded decomposition of the floored value", () => {
    fc.assert(
      fc.property(fc.double({ min: 0, max: 1e9, noNaN: true }), (n) => {
        const whole = Math.floor(n);
        const pad = (x: number) => String(x).padStart(2, "0");
        const expected = `${pad(Math.floor(whole / 3600))}:${pad(Math.floor((whole % 3600) / 60))}:${pad(whole % 60)}`;
        expect(formatDuration(n)).toBe(expected);
      }),
      RUNS,
    );
  });

  it("handles specific examples", () => {
    expect(formatDuration(0)).toBe("00:00:00");
    expect(formatDuration(3661.9)).toBe("01:01:01");
    expect(formatDuration(-1)).toBe("00:00:00");
    expect(formatDuration(Number.NaN)).toBe("00:00:00");
    expect(formatDuration(Infinity)).toBe("00:00:00");
  });
});

describe("Feature: dashboard, Property 19: Timestamp formatting is total", () => {
  // **Validates: Requirements 9.2**
  it("never throws for any input and returns a dash for null/undefined/empty", () => {
    fc.assert(
      fc.property(fc.oneof(fc.string(), fc.constant(null), fc.constant(undefined)), (v) => {
        const out = formatTimestamp(v);
        expect(typeof out).toBe("string");
        if (v === null || v === undefined || v === "") expect(out).toBe("—");
      }),
      RUNS,
    );
  });

  it("returns a dash for any string that does not parse as a date", () => {
    fc.assert(
      fc.property(
        fc.string().filter((s) => Number.isNaN(new Date(s).getTime())),
        (s) => {
          expect(formatTimestamp(s)).toBe("—");
        },
      ),
      RUNS,
    );
  });

  it("returns a non-empty display string for ISO strings that round-trip", () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date("0001-01-01T00:00:00Z"), max: new Date("9999-12-31T23:59:59Z"), noInvalidDate: true }),
        (d) => {
          const iso = d.toISOString();
          expect(new Date(iso).toISOString()).toBe(iso);
          const out = formatTimestamp(iso);
          expect(out.length).toBeGreaterThan(0);
          expect(out).not.toBe("—");
        },
      ),
      RUNS,
    );
  });
});

describe("Feature: dashboard, Property 20: Offset formatting is total and monotonic", () => {
  // **Validates: Requirements 9.3**
  const parse = (s: string): number => {
    const m = /^\+(\d+)\.(\d{3}) s$/.exec(s);
    expect(m).not.toBeNull();
    return Number(`${m![1]}.${m![2]}`);
  };

  it("has the form +S.mmm s and equals the input in seconds; negatives become 0", () => {
    fc.assert(
      fc.property(fc.double({ min: -1e6, max: 1e12, noNaN: true }), (ms) => {
        const out = formatOffset(ms);
        const seconds = parse(out);
        const expected = ms > 0 ? ms / 1000 : 0;
        expect(Math.abs(seconds - expected)).toBeLessThanOrEqual(0.0005 + 1e-6);
        if (ms < 0) expect(out).toBe("+0.000 s");
      }),
      RUNS,
    );
  });

  it("is monotonic for non-negative inputs", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1e12, noNaN: true }),
        fc.double({ min: 0, max: 1e12, noNaN: true }),
        (x, y) => {
          const [a, b] = x <= y ? [x, y] : [y, x];
          expect(parse(formatOffset(a))).toBeLessThanOrEqual(parse(formatOffset(b)));
        },
      ),
      RUNS,
    );
  });

  it("handles specific examples", () => {
    expect(formatOffset(0)).toBe("+0.000 s");
    expect(formatOffset(1234)).toBe("+1.234 s");
    expect(formatOffset(-5)).toBe("+0.000 s");
  });
});

describe("Feature: dashboard, Property 21: Severity mapping and chip variant are total functions over all strings", () => {
  // **Validates: Requirements 9.4, 7.5**
  const known: Record<string, [string, string]> = {
    Class_1: ["Class 1", "outline-muted"],
    Class_3: ["Class 3", "outline"],
    Class_5: ["Class 5", "solid"],
  };

  it("maps the three known values and passes everything else through", () => {
    fc.assert(
      fc.property(fc.oneof(fc.string(), fc.constantFrom("Class_1", "Class_3", "Class_5")), (s) => {
        const entry = known[s];
        if (Object.prototype.hasOwnProperty.call(known, s)) {
          expect(mapSeverity(s)).toBe(entry[0]);
          expect(severityChipVariant(s)).toBe(entry[1]);
        } else {
          expect(mapSeverity(s)).toBe(s);
          expect(severityChipVariant(s)).toBe("unknown");
        }
      }),
      RUNS,
    );
  });

  it("does not treat prototype keys as known severities", () => {
    for (const s of ["__proto__", "constructor", "toString", "class_5", "Class_5 "]) {
      expect(mapSeverity(s)).toBe(s);
      expect(severityChipVariant(s)).toBe("unknown");
    }
  });
});
