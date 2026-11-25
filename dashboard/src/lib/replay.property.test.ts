import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { decodePayload, isStitched, sortEventsWithOffsets } from "./replay";

const RUNS = { numRuns: 200 };

const isoTimestamp = fc
  .integer({ min: Date.UTC(2000, 0, 1), max: Date.UTC(2100, 0, 1) })
  .map((ms) => new Date(ms).toISOString());

// A small timestamp pool forces duplicates; the id lets us check no event is lost.
const eventList = fc
  .array(isoTimestamp, { minLength: 1, maxLength: 40 })
  .map((timestamps) => timestamps.map((timestamp, id) => ({ id, timestamp })));

describe("Feature: dashboard, Property 8: Event ordering and offsets are correct for any timestamp arrangement", () => {
  // **Validates: Requirements 4.4**
  it("sorts ascending, starts at offset 0, and offsets equal timestamp minus minimum", () => {
    fc.assert(
      fc.property(eventList, (events) => {
        const result = sortEventsWithOffsets(events);
        const min = Math.min(...events.map((e) => Date.parse(e.timestamp)));

        expect(result).toHaveLength(events.length);
        expect(result.map((e) => e.id).sort((a, b) => a - b)).toEqual(events.map((e) => e.id));
        expect(result[0].offsetMs).toBe(0);
        for (let i = 0; i < result.length; i++) {
          const ms = Date.parse(result[i].timestamp);
          expect(result[i].offsetMs).toBe(ms - min);
          if (i > 0) expect(ms).toBeGreaterThanOrEqual(Date.parse(result[i - 1].timestamp));
        }
      }),
      RUNS,
    );
  });

  it("does not mutate the input list", () => {
    fc.assert(
      fc.property(eventList, (events) => {
        const copy = events.map((e) => ({ ...e }));
        sortEventsWithOffsets(events);
        expect(events).toEqual(copy);
      }),
      RUNS,
    );
  });
});

describe("Feature: dashboard, Property 9: Payload decoding never throws and round-trips valid JSON", () => {
  // **Validates: Requirements 4.5**
  it("never throws for any string", () => {
    fc.assert(
      fc.property(fc.string({ unit: "binary" }), (s) => {
        expect(() => decodePayload(s)).not.toThrow();
      }),
      RUNS,
    );
  });

  it("round-trips any JSON-serializable value", () => {
    fc.assert(
      fc.property(fc.jsonValue(), (v) => {
        // Normalise through JSON so -0 and similar do not affect equality.
        const expected = JSON.parse(JSON.stringify(v)) as unknown;
        const result = decodePayload(JSON.stringify(v));
        expect(result.isJson).toBe(true);
        expect(result.value).toEqual(expected);
      }),
      RUNS,
    );
  });

  it("returns the same string with isJson false for invalid JSON", () => {
    const invalid = fc.string({ unit: "binary" }).filter((s) => {
      try {
        JSON.parse(s);
        return false;
      } catch {
        return true;
      }
    });
    fc.assert(
      fc.property(invalid, (s) => {
        expect(decodePayload(s)).toEqual({ value: s, isJson: false });
      }),
      RUNS,
    );
  });
});

describe("Feature: dashboard, Property 10: The Stitched tag appears exactly for LLM-generated events", () => {
  // **Validates: Requirements 4.6**
  it("isStitched is true if and only if generated_by is the string 'llm'", () => {
    const generatedBy = fc.oneof(
      fc.constantFrom("llm", "scripted", "LLM", "llm ", " llm", ""),
      fc.string(),
      fc.anything(),
      fc.constant(undefined),
    );
    fc.assert(
      fc.property(generatedBy, (g) => {
        expect(isStitched({ generated_by: g })).toBe(g === "llm");
      }),
      RUNS,
    );
  });

  it("is false when generated_by is absent", () => {
    expect(isStitched({})).toBe(false);
  });
});
