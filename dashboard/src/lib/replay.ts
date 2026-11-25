export type TimedEvent<E> = E & { offsetMs: number };

function toMs(timestamp: string): number {
  return Date.parse(timestamp);
}

/**
 * Sorts events by timestamp ascending (stable) and attaches `offsetMs`,
 * the distance from the earliest timestamp. Unparseable timestamps sort
 * last and get an offset of 0. Does not mutate the input.
 */
export function sortEventsWithOffsets<E extends { timestamp: string }>(
  events: E[],
): TimedEvent<E>[] {
  const keyed = events.map((event, index) => ({ event, index, ms: toMs(event.timestamp) }));
  keyed.sort((a, b) => {
    const aBad = Number.isNaN(a.ms);
    const bBad = Number.isNaN(b.ms);
    if (aBad || bBad) {
      if (aBad && bBad) return a.index - b.index;
      return aBad ? 1 : -1;
    }
    return a.ms - b.ms || a.index - b.index;
  });
  const first = keyed.find((k) => !Number.isNaN(k.ms))?.ms ?? 0;
  return keyed.map(({ event, ms }) => ({
    ...event,
    offsetMs: Number.isNaN(ms) ? 0 : ms - first,
  }));
}

/** Parses a JSON payload; falls back to the raw string. Never throws. */
export function decodePayload(payload: string): { value: unknown; isJson: boolean } {
  try {
    return { value: JSON.parse(payload) as unknown, isJson: true };
  } catch {
    return { value: payload, isJson: false };
  }
}

/** True exactly when the event's response was invented by the LLM. */
export function isStitched(event: { generated_by?: unknown }): boolean {
  return event.generated_by === "llm";
}
