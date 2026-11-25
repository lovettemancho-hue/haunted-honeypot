import { act, renderHook } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { usePoller } from "./usePoller";

type Outcome =
  | { kind: "ok"; value: number }
  | { kind: "network" }
  | { kind: "http5xx"; status: number };

function settle(outcome: Outcome): Promise<number> {
  if (outcome.kind === "ok") return Promise.resolve(outcome.value);
  if (outcome.kind === "network") return Promise.reject(new TypeError("Failed to fetch"));
  return Promise.reject(new ApiError(outcome.status));
}

function setVisibility(state: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

async function tick(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setVisibility("visible");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("usePoller properties", () => {
  const outcomeArb: fc.Arbitrary<Outcome> = fc.oneof(
    fc.integer().map((value): Outcome => ({ kind: "ok", value })),
    fc.constant<Outcome>({ kind: "network" }),
    fc.integer({ min: 500, max: 599 }).map((status): Outcome => ({ kind: "http5xx", status })),
  );

  // Feature: dashboard, Property 5: Every poll outcome sequence leaves the displayed data as the last success
  // **Validates: Requirements 2.1, 2.5**
  it("Feature: dashboard, Property 5: Every poll outcome sequence leaves the displayed data as the last success", async () => {
    await fc.assert(
      fc.asyncProperty(fc.array(outcomeArb, { minLength: 1, maxLength: 12 }), async (outcomes) => {
        let call = 0;
        const fetchFn = (): Promise<number> => settle(outcomes[Math.min(call++, outcomes.length - 1)]);
        const { result, unmount } = renderHook(() =>
          usePoller(fetchFn, { intervalMs: 5000, enabled: true }),
        );
        try {
          await tick(0);
          for (let i = 1; i < outcomes.length; i++) await tick(5000);

          let lastSuccess: number | null = null;
          for (const o of outcomes) if (o.kind === "ok") lastSuccess = o.value;
          expect(result.current.data).toBe(lastSuccess);
          expect(result.current.connectionLost).toBe(outcomes[outcomes.length - 1].kind !== "ok");
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
  });
});

describe("usePoller", () => {
  it("fetches immediately on mount and then every interval", async () => {
    const fetchFn = vi.fn().mockResolvedValue("x");
    const { result } = renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: true }));
    await tick(0);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("x");
    await tick(4999);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(fetchFn).toHaveBeenCalledTimes(2);
    await tick(5000);
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  it("pauses when hidden and refetches immediately when visible again", async () => {
    const fetchFn = vi.fn().mockResolvedValue(1);
    renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: true }));
    await tick(0);
    expect(fetchFn).toHaveBeenCalledTimes(1);

    act(() => setVisibility("hidden"));
    await tick(20000);
    expect(fetchFn).toHaveBeenCalledTimes(1);

    act(() => setVisibility("visible"));
    await tick(0);
    expect(fetchFn).toHaveBeenCalledTimes(2);
    await tick(5000);
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  it("stops polling on unmount", async () => {
    const fetchFn = vi.fn().mockResolvedValue(1);
    const { unmount } = renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: true }));
    await tick(0);
    unmount();
    await tick(20000);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("does not poll when enabled=false and stops when it turns false", async () => {
    const fetchFn = vi.fn().mockResolvedValue(1);
    const { rerender } = renderHook(
      ({ enabled }) => usePoller(fetchFn, { intervalMs: 5000, enabled }),
      { initialProps: { enabled: true } },
    );
    await tick(0);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    rerender({ enabled: false });
    await tick(20000);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("does not poll at all when initially disabled", async () => {
    const fetchFn = vi.fn().mockResolvedValue(1);
    renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: false }));
    await tick(20000);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("ignores a response that resolves after unmount", async () => {
    let resolve: (v: number) => void = () => undefined;
    const fetchFn = vi.fn(() => new Promise<number>((r) => (resolve = r)));
    const { result, unmount } = renderHook(() =>
      usePoller(fetchFn, { intervalMs: 5000, enabled: true }),
    );
    unmount();
    await act(async () => {
      resolve(7);
      await Promise.resolve();
    });
    expect(result.current.data).toBeNull();
  });

  it("keeps last data on 5xx, and clears connectionLost on next success", async () => {
    const fetchFn = vi
      .fn<() => Promise<number>>()
      .mockResolvedValueOnce(1)
      .mockRejectedValueOnce(new ApiError(503))
      .mockResolvedValueOnce(2);
    const { result } = renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: true }));
    await tick(0);
    await tick(5000);
    expect(result.current).toMatchObject({ data: 1, connectionLost: true });
    await tick(5000);
    expect(result.current).toMatchObject({ data: 2, connectionLost: false });
  });

  it("does not flag connectionLost for a 401", async () => {
    const fetchFn = vi.fn().mockRejectedValue(new ApiError(401));
    const { result } = renderHook(() => usePoller(fetchFn, { intervalMs: 5000, enabled: true }));
    await tick(0);
    expect(result.current.connectionLost).toBe(false);
  });
});
