import { clampVoltage, voltageDescription } from "../lib/voltage";

const SEGMENTS = 10;

/** Lab voltage (threat level) meter: 10 segments, lit count equals the clamped level. */
export function VoltageMeter({ level }: { level: number }) {
  const lit = clampVoltage(level);
  return (
    <div className="voltage">
      <div
        className={`voltage-meter${lit >= 8 ? " voltage-meter--surge" : ""}`}
        role="meter"
        aria-label="Lab voltage"
        aria-valuemin={0}
        aria-valuemax={10}
        aria-valuenow={lit}
        aria-valuetext={`${lit} of 10. ${voltageDescription(lit)}`}
      >
        {Array.from({ length: SEGMENTS }, (_, i) => {
          const tone = i < 3 ? "low" : i < 7 ? "mid" : "high";
          return (
            <span
              key={i}
              className={`voltage-segment voltage-segment--${tone}${i < lit ? " is-lit" : ""}${lit >= 8 && i === lit - 1 ? " is-top" : ""}`}
              data-lit={i < lit ? "true" : "false"}
              style={{ height: `${30 + i * 7}%` }}
            />
          );
        })}
      </div>
      <p className="voltage-readout">
        <span className="mono voltage-level">{lit}/10</span>{" "}
        <span className="voltage-description">
          Lab voltage (threat level). {voltageDescription(lit)}
        </span>
      </p>
    </div>
  );
}
