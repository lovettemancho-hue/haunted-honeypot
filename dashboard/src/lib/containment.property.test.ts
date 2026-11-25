import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { progressCount, toggleItem, type ChecklistState } from "./checklist";
import { deriveContainedSpecimens, type Severity } from "./containmentSpecimens";

const RUNS = { numRuns: 200 };

const idArb = fc.constantFrom("a", "b", "c", "d", "e", "f");
const stateArb = fc.dictionary(idArb, fc.boolean());

describe("Feature: dashboard, Property 11: Checklist progress always equals the number of checked items", () => {
  // **Validates: Requirements 5.2**
  it("progressCount equals the checked ids and each toggle changes only its own id", () => {
    fc.assert(
      fc.property(stateArb, fc.array(idArb, { maxLength: 40 }), (start, ids) => {
        let state: ChecklistState = start;
        for (const id of ids) {
          const before = state;
          const snapshot = { ...before };
          state = toggleItem(before, id);

          expect(before).toEqual(snapshot); // immutable input
          expect(state[id]).toBe(!before[id]);
          for (const key of Object.keys(before)) {
            if (key !== id) expect(state[key]).toBe(before[key]);
          }
          expect(Object.keys(state).sort()).toEqual(
            [...new Set([...Object.keys(before), id])].sort(),
          );
          expect(progressCount(state)).toBe(
            Object.keys(state).filter((k) => state[k] === true).length,
          );
        }
      }),
      RUNS,
    );
  });
});

const RANK: Record<Severity, number> = { Class_1: 1, Class_3: 2, Class_5: 3 };
const sevArb = fc.constantFrom<Severity>("Class_1", "Class_3", "Class_5");
const ipArb = fc.constantFrom("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4");
const sessionIdArb = fc.constantFrom("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8");

const sessionsArb = fc.uniqueArray(
  fc.record({ id: sessionIdArb, src_ip: ipArb, severity: sevArb }),
  { selector: (s) => s.id, maxLength: 8 },
);
const rulesArb = fc.array(
  fc.record({
    // "x1".."x3" never match any session
    evidence_sessions: fc.array(
      fc.oneof(sessionIdArb, fc.constantFrom("x1", "x2", "x3")),
      { maxLength: 6 },
    ),
  }),
  { maxLength: 5 },
);

describe("Feature: dashboard, Property 12: Contained specimens are derived exactly from evidence that matches a known Tape", () => {
  // **Validates: Requirements 5.7, 5.8, 5.12**
  it("matches a reference derivation and omits unmatched evidence", () => {
    fc.assert(
      fc.property(rulesArb, sessionsArb, (rules, sessions) => {
        const evidence = new Set(rules.flatMap((r) => r.evidence_sessions));
        const matched = sessions.filter((s) => evidence.has(s.id));
        const ips = new Set(matched.map((s) => s.src_ip));

        const result = deriveContainedSpecimens(rules, sessions);

        expect(result.length).toBe(ips.size);
        expect(new Set(result.map((r) => r.ip))).toEqual(ips);
        for (const spec of result) {
          const mine = matched.filter((s) => s.src_ip === spec.ip);
          expect(spec.tapeCount).toBe(new Set(mine.map((s) => s.id)).size);
          expect(RANK[spec.highestSeverity]).toBe(
            Math.max(...mine.map((s) => RANK[s.severity])),
          );
        }
        expect(result.reduce((n, r) => n + r.tapeCount, 0)).toBe(matched.length);
      }),
      RUNS,
    );
  });

  it("returns nothing when no evidence matches a session", () => {
    fc.assert(
      fc.property(sessionsArb, (sessions) => {
        expect(
          deriveContainedSpecimens([{ evidence_sessions: ["x1", "x2"] }], sessions),
        ).toEqual([]);
      }),
      RUNS,
    );
  });
});
