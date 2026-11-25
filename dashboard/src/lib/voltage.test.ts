import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { clampVoltage, techniqueBarWidth, voltageDescription } from "./voltage";

const RUNS = { numRuns: 200 };

describe("Feature: dashboard, Property 1: Voltage meter segment count is the clamped threat level", () => {
  // **Validates: Requirements 3.1**
  it("is an integer in [0, 10] for any finite number", () => {
    fc.assert(
      fc.property(fc.double({ noNaN: true, noDefaultInfinity: true }), (n) => {
        const v = clampVoltage(n);
        expect(Number.isInteger(v)).toBe(true);
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(10);
      }),
      RUNS,
    );
  });

  it("equals the truncated level when inside [0, 10], and saturates outside", () => {
    fc.assert(
      fc.property(fc.double({ min: 0, max: 10, noNaN: true }), (n) => {
        expect(clampVoltage(n)).toBe(Math.trunc(n));
      }),
      RUNS,
    );
    fc.assert(
      fc.property(fc.double({ min: 10, max: 1e12, noNaN: true }), (n) => {
        expect(clampVoltage(n)).toBe(10);
        expect(clampVoltage(-n)).toBe(0);
      }),
      RUNS,
    );
  });

  it("maps NaN and non-finite values to 0, and always yields a description", () => {
    expect(clampVoltage(Number.NaN)).toBe(0);
    expect(clampVoltage(Infinity)).toBe(0);
    expect(clampVoltage(-Infinity)).toBe(0);
    fc.assert(
      fc.property(fc.double(), (n) => {
        expect(voltageDescription(n).length).toBeGreaterThan(0);
      }),
      RUNS,
    );
  });
});

describe("Feature: dashboard, Property 2: Technique bar width is proportional and bounded", () => {
  // **Validates: Requirements 3.6**
  it("is always within [0, 100] for any input", () => {
    fc.assert(
      fc.property(fc.double(), fc.double(), (count, max) => {
        const w = techniqueBarWidth(count, max);
        expect(w).toBeGreaterThanOrEqual(0);
        expect(w).toBeLessThanOrEqual(100);
      }),
      RUNS,
    );
  });

  it("equals count / max * 100 when 0 <= count <= max, and 100 for the max itself", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 1_000_000 }),
        fc.double({ min: 0, max: 1, noNaN: true }),
        (max, frac) => {
          const count = Math.floor(max * frac);
          expect(techniqueBarWidth(count, max)).toBeCloseTo((count / max) * 100, 9);
          expect(techniqueBarWidth(max, max)).toBe(100);
        },
      ),
      RUNS,
    );
  });

  it("is monotonic in count for a fixed max", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 1_000_000 }),
        fc.integer({ min: 0, max: 1_000_000 }),
        fc.integer({ min: 0, max: 1_000_000 }),
        (max, a, b) => {
          const [lo, hi] = a <= b ? [a, b] : [b, a];
          expect(techniqueBarWidth(lo, max)).toBeLessThanOrEqual(techniqueBarWidth(hi, max));
        },
      ),
      RUNS,
    );
  });

  it("returns 0 when max is not positive or inputs are non-finite", () => {
    expect(techniqueBarWidth(5, 0)).toBe(0);
    expect(techniqueBarWidth(5, -3)).toBe(0);
    expect(techniqueBarWidth(Number.NaN, 5)).toBe(0);
    expect(techniqueBarWidth(5, Infinity)).toBe(0);
  });
});
