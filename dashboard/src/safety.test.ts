/**
 * Source-level safety tests for the dashboard.
 * Feature: dashboard. Validates: Requirements 6.2, 6.4, 7.9
 */
// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = dirname(fileURLToPath(import.meta.url));

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const sourceFiles = walk(SRC)
  .filter((f) => /\.(ts|tsx)$/.test(f))
  .filter((f) => !/\.test\.(ts|tsx)$/.test(f))
  .filter((f) => !/[\\/]test[\\/]/.test(f))
  .map((f) => ({ path: f, text: readFileSync(f, "utf8") }));

/** Remove comments so explanatory prose does not trigger the scans. */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const ATTACKER_FIELDS = /\b(username|password|payload|ioc|iocs|url|client_version|command|evidence)\b/i;

describe("source safety: no raw HTML injection (Req 6.2)", () => {
  it("scans at least one source file", () => {
    expect(sourceFiles.length).toBeGreaterThan(10);
  });

  it.each(["dangerouslySetInnerHTML", "innerHTML", "outerHTML"])("no source file uses %s", (needle) => {
    const offenders = sourceFiles.filter((f) => stripComments(f.text).includes(needle)).map((f) => f.path);
    expect(offenders).toEqual([]);
  });
});

describe("source safety: links never derive from attacker text (Req 6.4)", () => {
  const ALLOWED_HREF = [
    /^"[^"{}]*"$/, // static string
    /^\{"[^"]*"\}$/, // static string in braces
    /^\{tapeHref\([A-Za-z_.]*\bid\)\}$/, // route helper with a server-assigned id
    /^\{item\.href\}$/, // NAV_ITEMS constant
  ];

  it("every <a> element uses a static or route-helper href", () => {
    const found: string[] = [];
    for (const f of sourceFiles) {
      const code = stripComments(f.text);
      for (const m of code.matchAll(/<a(\s[^>]*?)?>/gs)) {
        const attrs = m[1] ?? "";
        const hm = attrs.match(/\shref=("[^"]*"|\{[^}]*(?:\([^)]*\))?[^}]*\})/s) ?? attrs.match(/^href=("[^"]*"|\{[^}]*\})/s);
        const value = hm?.[1]?.trim();
        found.push(`${f.path}: ${value ?? "(no href)"}`);
        expect(value, `<a> without href in ${f.path}`).toBeDefined();
        expect(
          ALLOWED_HREF.some((re) => re.test(value as string)),
          `disallowed href ${value} in ${f.path}`,
        ).toBe(true);
        expect(value as string).not.toMatch(ATTACKER_FIELDS);
      }
    }
    expect(found.length).toBeGreaterThan(0);
  });

  it("programmatic href assignments only use an object URL", () => {
    for (const f of sourceFiles) {
      const code = stripComments(f.text);
      for (const m of code.matchAll(/\.href\s*=\s*([^;\n]+)/g)) {
        const rhs = m[1]?.trim() ?? "";
        if (/window\.location\.hash/.test(m[0])) continue;
        expect(rhs, `unexpected href assignment in ${f.path}`).toBe("url");
        expect(code, `href assignment in ${f.path} must use an object URL`).toMatch(
          /const url = URL\.createObjectURL\(/,
        );
      }
      expect(code).not.toMatch(/setAttribute\(\s*["']href["']/);
    }
  });

  it("window.location.hash is only set from tapeHref or static routes", () => {
    for (const f of sourceFiles) {
      const code = stripComments(f.text);
      for (const m of code.matchAll(/location\.hash\s*=\s*([^;\n]+)/g)) {
        const rhs = m[1]?.trim() ?? "";
        expect(rhs, `unsafe hash assignment in ${f.path}`).toMatch(/^(tape(Href|Hash)\((null|[A-Za-z_.]*\bid)\)|"#\/[a-z/]*")$/);
      }
    }
  });
});

describe("design tokens: text contrast (Req 7.9)", () => {
  const css = readFileSync(join(SRC, "styles", "tokens.css"), "utf8");

  function token(name: string): string {
    const m = css.match(new RegExp(`${name}\\s*:\\s*(#[0-9a-fA-F]{6})\\b`));
    if (!m) throw new Error(`token ${name} not found`);
    return m[1] as string;
  }

  function luminance(hex: string): number {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contrast(a: string, b: string): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
    return (hi + 0.05) / (lo + 0.05);
  }

  const texts = ["--text", "--text-terminal", "--muted", "--volt"];
  const backgrounds = ["--bg", "--panel"];

  for (const t of texts) {
    for (const bg of backgrounds) {
      it(`${t} on ${bg} is at least 4.5:1`, () => {
        expect(contrast(token(t), token(bg))).toBeGreaterThanOrEqual(4.5);
      });
    }
  }

  it("--text-terminal is readable on --terminal", () => {
    expect(contrast(token("--text-terminal"), token("--terminal"))).toBeGreaterThanOrEqual(4.5);
  });

  it("--on-volt is readable on --volt", () => {
    expect(contrast(token("--on-volt"), token("--volt"))).toBeGreaterThanOrEqual(4.5);
  });
});
