import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface PollerOptions {
  intervalMs: number;
  enabled: boolean;
}

export interface PollerResult<T> {
  data: T | null;
  connectionLost: boolean;
  refetchNow: () => void;
}

/**
 * Polls `fetchFn` every `intervalMs` while `enabled` and the tab is visible.
 * Keeps the last good data on failure. Network errors and 5xx set
 * `connectionLost`. A 401 is left to the API client's `onUnauthorized`
 * handler: it neither marks connectionLost nor changes data. Other 4xx
 * errors are likewise ignored here so pages can handle them themselves.
 */
export function usePoller<T>(
  fetchFn: () => Promise<T>,
  { intervalMs, enabled }: PollerOptions,
): PollerResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const runRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled) {
      runRef.current = () => undefined;
      return undefined;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const run = (): void => {
      fetchFn().then(
        (result) => {
          if (cancelled) return;
          setData(result);
          setConnectionLost(false);
        },
        (error: unknown) => {
          if (cancelled) return;
          if (error instanceof ApiError && error.status < 500) return;
          setConnectionLost(true);
        },
      );
    };

    const stop = (): void => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const start = (): void => {
      stop();
      run();
      timer = setInterval(run, intervalMs);
    };

    const onVisibility = (): void => {
      if (document.visibilityState === "hidden") {
        stop();
      } else {
        start();
      }
    };

    runRef.current = run;
    if (document.visibilityState !== "hidden") {
      start();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      runRef.current = () => undefined;
    };
  }, [fetchFn, intervalMs, enabled]);

  const refetchNow = useCallback((): void => {
    runRef.current();
  }, []);

  return { data, connectionLost, refetchNow };
}
