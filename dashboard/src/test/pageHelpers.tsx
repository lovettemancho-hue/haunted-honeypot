import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";

export const TOKEN_KEY = "hh_api_token";

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export type Router = (path: string) => Response | Promise<Response>;

/** Stubs global fetch with a path router and returns the mock for call inspection. */
export function stubFetch(router: Router): ReturnType<typeof vi.fn> {
  const mock = vi.fn((input: unknown) => Promise.resolve(router(String(input))));
  vi.stubGlobal("fetch", mock);
  return mock;
}

export function fetchedPaths(mock: ReturnType<typeof vi.fn>): string[] {
  return mock.mock.calls.map((c) => String(c[0]));
}

/** Renders a page inside AuthProvider with a token already in sessionStorage. */
export function renderPage(ui: ReactElement) {
  sessionStorage.setItem(TOKEN_KEY, "test-token");
  return render(<AuthProvider>{ui}</AuthProvider>);
}
