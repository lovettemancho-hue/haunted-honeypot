import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { maskIp } from "./maskIp";
import { stripControlChars } from "./sanitize";
import { MAX_ATTACKER_TEXT_LENGTH, truncateAttackerText } from "./truncate";

const RUNS = { numRuns: 200 };

// eslint-disable-next-line no-control-regex
const DISALLOWED = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/;
const isDisallowed = (ch: string): boolean => DISALLOWED.test(ch);

const printableChar = fc.oneof(
  fc.char().filter((c) => !isDisallowed(c)),
  fc.constantFrom("\n", "\t", "é", "日", "[", "]", "m"),
);
// Control characters that do not introduce an escape sequence.
const plainControl = fc
  .integer({ min: 0, max: 0x9f })
  .filter((n) => (n <= 0x1f || n >= 0x7f) && n !== 0x1b && n !== 0x9b && n !== 0x9d)
  .map((n) => String.fromCharCode(n));

describe("Feature: dashboard, Property 15: Control-character stripping removes exactly the disallowed bytes", () => {
  // **Validates: Requirements 6.8**
  it("output never contains disallowed control characters", () => {
    fc.assert(
      fc.property(fc.string({ unit: "binary" }), (s) => {
        expect(isDisallowed(stripControlChars(s))).toBe(false);
        expect(stripControlChars(s)).not.toContain("\u001b");
      }),
      RUNS,
    );
  });

  it("removes exactly the control characters and keeps printable characters in order", () => {
    fc.assert(
      fc.property(
        fc.array(fc.oneof(printableChar, plainControl), { maxLength: 200 }),
        (chars) => {
          const input = chars.join("");
          const expected = chars.filter((c) => !isDisallowed(c)).join("");
          expect(stripControlChars(input)).toBe(expected);
        },
      ),
      RUNS,
    );
  });

  it("removes ANSI CSI and OSC sequences", () => {
    fc.assert(
      fc.property(fc.stringMatching(/^[a-z ]{0,20}$/), fc.stringMatching(/^[a-z ]{0,20}$/), (a, b) => {
        expect(stripControlChars(`${a}\u001b[31;1m${b}`)).toBe(a + b);
        expect(stripControlChars(`${a}\u001b]0;title\u0007${b}`)).toBe(a + b);
      }),
      RUNS,
    );
  });
});

const octet = fc.integer({ min: 0, max: 255 });

describe("Feature: dashboard, Property 16: maskIp affects only valid IPv4 input, and always drops the last octet", () => {
  // **Validates: Requirements 6.9**
  it("masks the last octet of any valid IPv4", () => {
    fc.assert(
      fc.property(octet, octet, octet, octet, (a, b, c, d) => {
        expect(maskIp(`${a}.${b}.${c}.${d}`)).toBe(`${a}.${b}.${c}.x`);
      }),
      RUNS,
    );
  });

  it("returns IPv6 addresses unchanged", () => {
    fc.assert(
      fc.property(fc.ipV6(), (ip) => {
        expect(maskIp(ip)).toBe(ip);
      }),
      RUNS,
    );
  });

  it("returns non-IPv4 strings unchanged", () => {
    const IPV4_SHAPE = /^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;
    fc.assert(
      fc.property(fc.string(), (s) => {
        fc.pre(!IPV4_SHAPE.test(s));
        expect(maskIp(s)).toBe(s);
      }),
      RUNS,
    );
  });

  it("returns malformed octets unchanged", () => {
    fc.assert(
      fc.property(fc.integer({ min: 256, max: 9999 }), octet, octet, octet, fc.nat(3), (bad, x, y, z, pos) => {
        const parts = [String(x), String(y), String(z), String(x)];
        parts[pos] = String(bad);
        const ip = parts.join(".");
        expect(maskIp(ip)).toBe(ip);
        const short = [x, y, z].join(".");
        expect(maskIp(short)).toBe(short);
        expect(maskIp(`${ip}.1`)).toBe(`${ip}.1`);
      }),
      RUNS,
    );
  });
});

describe("Feature: dashboard, Property 17: Truncation is exact and total", () => {
  // **Validates: Requirements 6.11**
  it("leaves strings of at most 4096 characters unchanged", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: MAX_ATTACKER_TEXT_LENGTH }), (s) => {
        expect(truncateAttackerText(s)).toEqual({ text: s, truncated: false });
      }),
      RUNS,
    );
  });

  it("cuts longer strings to exactly the first 4096 characters", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: MAX_ATTACKER_TEXT_LENGTH + 1, maxLength: MAX_ATTACKER_TEXT_LENGTH + 500 }),
        (s) => {
          const r = truncateAttackerText(s);
          expect(r.truncated).toBe(true);
          expect(r.text).toBe(s.slice(0, MAX_ATTACKER_TEXT_LENGTH));
          expect(r.text.length).toBe(MAX_ATTACKER_TEXT_LENGTH);
        },
      ),
      RUNS,
    );
  });

  it("handles the boundary lengths 4095, 4096, 4097", () => {
    for (const n of [4095, 4096, 4097]) {
      const r = truncateAttackerText("a".repeat(n));
      expect(r.truncated).toBe(n > 4096);
      expect(r.text.length).toBe(Math.min(n, 4096));
    }
  });
});
