export type Severity = "Class_1" | "Class_3" | "Class_5";

export type SeverityChipVariant = "solid" | "outline" | "outline-muted" | "unknown";

/** "Class_5" -> "Class 5" etc. Any other string is returned unchanged. */
export function mapSeverity(value: string): string {
  switch (value) {
    case "Class_1":
      return "Class 1";
    case "Class_3":
      return "Class 3";
    case "Class_5":
      return "Class 5";
    default:
      return value;
  }
}

/** Chip style for a severity value; unexpected values map to "unknown". */
export function severityChipVariant(value: string): SeverityChipVariant {
  switch (value) {
    case "Class_5":
      return "solid";
    case "Class_3":
      return "outline";
    case "Class_1":
      return "outline-muted";
    default:
      return "unknown";
  }
}
