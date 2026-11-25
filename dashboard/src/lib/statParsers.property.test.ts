import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { parseTechniqueCounts, parseTopPasswords, type LabelCount } from "./statParsers";

const RUNS = { numRuns: 200 };

const byLabel = (a: LabelCount, b: LabelCount): number =>
  a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
const normalize = (xs: LabelCount[]): LabelCount[] => [...xs].sort(byLabel);

const pairs = fc.uniqueArray(
  fc.tuple(
    fc.string({ maxLength: 20 }).filter((s) => s !== "__proto__"),
    fc.nat({ max: 1_000_000 }),
  ),
  { selector: ([label]) => label, maxLength: 20 },
);

const parsers = [
  ["password", parseTopPasswords],
  ["attack_id", parseTechniqueCounts],
] as const;

describe("Feature: dashboard, Property 3: Stat shape parsers are equivalent across all documented input shapes", () => {
  // **Validates: Requirements 3.10, 3.11**
  for (const [key, parse] of parsers) {
    it(`${parse.name} yields the same entries for object, tuple and map shapes`, () => {
      fc.assert(
        fc.property(pairs, (list) => {
          const expected = normalize(list.map(([label, count]) => ({ label, count })));
          const asObjects = list.map(([label, count]) => ({ [key]: label, count }));
          const asTuples = list.map(([label, count]) => [label, count]);
          const asMap = Object.fromEntries(list);
          expect(normalize(parse(asObjects))).toEqual(expected);
          expect(normalize(parse(asTuples))).toEqual(expected);
          expect(normalize(parse(asMap))).toEqual(expected);
        }),
        RUNS,
      );
    });
  }
});

const badNumber = fc.constantFrom(NaN, Infinity, -Infinity);
const badString = fc
  .string({ maxLength: 10 })
  .filter((s) => s.trim() === "" || !Number.isFinite(Number(s)));
// Values that can never resolve to a finite count.
const badCount: fc.Arbitrary<unknown> = fc.oneof(
  badNumber,
  badString,
  fc.constantFrom(null, undefined, true, false),
  fc.array(fc.integer(), { maxLength: 3 }),
  fc.constant({}),
);

describe("Feature: dashboard, Property 4: Unrecognized stat input always normalizes to an empty list", () => {
  // **Validates: Requirements 3.9, 9.5**
  const nonContainers = fc.oneof(
    fc.constant(null),
    fc.constant(undefined),
    fc.boolean(),
    fc.double(),
    fc.string(),
    fc.bigInt(),
    fc.constant(() => 1),
    fc.constant(new Date()),
    fc.constant(new Map([["a", 1]])),
  );

  for (const [key, parse] of parsers) {
    it(`${parse.name} returns [] for non-array, non-object input`, () => {
      fc.assert(
        fc.property(nonContainers, (raw) => {
          expect(parse(raw)).toEqual([]);
        }),
        RUNS,
      );
    });

    it(`${parse.name} returns [] when no element or value resolves`, () => {
      const badElement: fc.Arbitrary<unknown> = fc.oneof(
        fc.constantFrom(null, undefined, 1, "x", true),
        fc.array(fc.string(), { maxLength: 4 }).filter((a) => a.length !== 2),
        fc.tuple(fc.oneof(fc.integer(), fc.constant(null)), fc.integer()),
        fc.tuple(fc.string(), badCount),
        fc.record({ other: fc.string(), count: fc.nat() }),
        fc.record({ [key]: fc.string(), count: badCount }),
        fc.record({ [key]: fc.oneof(fc.integer(), fc.constant(null)), count: fc.nat() }),
      );
      fc.assert(
        fc.property(
          fc.array(badElement, { maxLength: 10 }),
          fc.dictionary(
            fc.string({ maxLength: 10 }).filter((s) => s !== "__proto__"),
            badCount,
            { maxKeys: 10 },
          ),
          (arr, map) => {
            expect(parse(arr)).toEqual([]);
            expect(parse(map)).toEqual([]);
          },
        ),
        RUNS,
      );
    });
  }
});
