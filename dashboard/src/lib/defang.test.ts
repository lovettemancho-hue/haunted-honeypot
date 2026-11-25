import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { defangText, defangUrl } from "./defang";

const RUNS = { numRuns: 200 };

// Arbitrary text biased toward URL-looking fragments.
const urlish = fc
  .array(
    fc.oneof(
      fc.string({ unit: "binary" }),
      fc.constantFrom("http://", "https://", "HTTP://", "HtTpS://", ".", "/", "http://http://", "hxxp://", "[.]", " ", "\n"),
    ),
    { maxLength: 12 },
  )
  .map((parts) => parts.join(""));

const hasLiveScheme = (s: string): boolean => /https?:\/\//i.test(s);

// Text with no "://" so it can never form or alter a URL.
const plain = fc.string({ unit: "binary", maxLength: 40 }).filter((s) => !s.includes("://"));
const label = fc.stringMatching(/^[a-z0-9-]{1,10}$/);
const host = fc.array(label, { minLength: 1, maxLength: 4 }).map((l) => l.join("."));
const scheme = fc.constantFrom("http", "https", "HTTP", "HTTPS", "Http", "hTtPs");

describe("defang helpers", () => {
  it("defangs a simple URL", () => {
    expect(defangText("go to http://evil.example.com/a.sh now")).toBe(
      "go to hxxp://evil[.]example[.]com/a.sh now",
    );
    expect(defangUrl("https://1.2.3.4:80/x.y")).toBe("hxxps://1[.]2[.]3[.]4:80/x.y");
  });

  it("leaves text without URLs unchanged", () => {
    expect(defangText("cat /etc/passwd. done")).toBe("cat /etc/passwd. done");
  });

  // Feature: dashboard, Property 13: Defanging removes every live URL scheme and is idempotent
  it("Feature: dashboard, Property 13: Defanging removes every live URL scheme and is idempotent", () => {
    // **Validates: Requirements 6.3, 6.4, 6.6, 9.7**
    fc.assert(
      fc.property(fc.oneof(urlish, fc.string({ unit: "binary" })), (s) => {
        const out = defangText(s);
        expect(hasLiveScheme(out)).toBe(false);
        expect(defangText(out)).toBe(out);
      }),
      RUNS,
    );
    fc.assert(
      fc.property(scheme, host, plain, (sc, h, rest) => {
        const out = defangUrl(`${sc}://${h}/${rest}`);
        expect(hasLiveScheme(out)).toBe(false);
      }),
      RUNS,
    );
  });

  // Feature: dashboard, Property 14: Defanging replaces exactly the scheme and host dots, and preserves everything else
  it("Feature: dashboard, Property 14: Defanging replaces exactly the scheme and host dots, and preserves everything else", () => {
    // **Validates: Requirements 6.3, 6.5, 6.7**
    fc.assert(
      fc.property(plain, scheme, host, plain, (prefix, sc, h, rest) => {
        const input = `${prefix}${sc}://${h}/${rest}`;
        const safeScheme = sc.toLowerCase() === "https" ? "hxxps" : "hxxp";
        const expected = `${prefix}${safeScheme}://${h.replace(/\./g, "[.]")}/${rest}`;
        expect(defangText(input)).toBe(expected);
      }),
      RUNS,
    );
  });
});
