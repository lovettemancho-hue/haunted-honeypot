export type LabelCount = { label: string; count: number };

function toCount(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function toLabel(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function parseEntry(item: unknown, labelKey: string): LabelCount | null {
  let rawLabel: unknown;
  let rawCount: unknown;
  if (Array.isArray(item)) {
    if (item.length !== 2) return null;
    rawLabel = item[0];
    rawCount = item[1];
  } else if (isPlainObject(item)) {
    if (!Object.prototype.hasOwnProperty.call(item, labelKey)) return null;
    rawLabel = item[labelKey];
    rawCount = item["count"];
  } else {
    return null;
  }
  const label = toLabel(rawLabel);
  const count = toCount(rawCount);
  if (label === null || count === null) return null;
  return { label, count };
}

function parseStat(raw: unknown, labelKey: string): LabelCount[] {
  try {
    const out: LabelCount[] = [];
    if (Array.isArray(raw)) {
      for (const item of raw) {
        const entry = parseEntry(item, labelKey);
        if (entry) out.push(entry);
      }
    } else if (isPlainObject(raw)) {
      for (const key of Object.keys(raw)) {
        const count = toCount(raw[key]);
        if (count !== null) out.push({ label: key, count });
      }
    }
    return out;
  } catch {
    return [];
  }
}

export function parseTopPasswords(raw: unknown): LabelCount[] {
  return parseStat(raw, "password");
}

export function parseTechniqueCounts(raw: unknown): LabelCount[] {
  return parseStat(raw, "attack_id");
}
