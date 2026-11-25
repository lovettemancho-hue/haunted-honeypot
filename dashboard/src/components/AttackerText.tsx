import { defangText } from "../lib/defang";
import { stripControlChars } from "../lib/sanitize";
import { truncateAttackerText } from "../lib/truncate";

/**
 * The single safe-rendering path for attacker-supplied strings.
 * Pipeline: stripControlChars -> truncateAttackerText -> defangText.
 * Output is a React text child (escaped by React); never a link or raw HTML.
 */
export function AttackerText({ value }: { value: string }) {
  const { text, truncated } = truncateAttackerText(stripControlChars(String(value)));
  return (
    <span className="mono attacker-text">
      {defangText(text)}
      {truncated ? <em className="attacker-text__truncated"> (truncated)</em> : null}
    </span>
  );
}
