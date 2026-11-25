import { mapSeverity, severityChipVariant } from "../lib/severity";

const VARIANT_CLASS = {
  solid: "chip--class-5",
  outline: "chip--class-3",
  "outline-muted": "chip--class-1",
  unknown: "chip--class-1",
} as const;

/** Severity label: Class 5 solid volt, Class 3 volt outline, Class 1 muted outline. */
export function SeverityChip({ severity, description }: { severity: string; description?: string }) {
  const variant = severityChipVariant(severity);
  return (
    <span
      className={`chip ${VARIANT_CLASS[variant]}`}
      data-variant={variant}
      title={description || undefined}
    >
      {mapSeverity(severity)}
    </span>
  );
}
