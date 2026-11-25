import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { fetchContainment, fetchContainmentScript } from "./containment";
import { fetchSessionDetail, fetchSessions } from "./sessions";
import { fetchStats } from "./stats";

type Endpoint = {
  name: string;
  call: (token: string, onUnauthorized: () => void) => Promise<unknown>;
};

const endpoints: Endpoint[] = [
  { name: "fetchStats", call: (t, u) => fetchStats(t, u) },
  { name: "fetchSessions", call: (t, u) => fetchSessions(t, u, { limit: 20, offset: 0 }) },
  { name: "fetchSessionDetail", call: (t, u) => fetchSessionDetail(t, u, "abc-123") },
  { name: "fetchContainment", call: (t, u) => fetchContainment(t, u) },
  { name: "fetchContainmentScript", call: (t, u) => fetchContainmentScript(t, u) },
];

// Header-safe, non-empty tokens (no whitespace, so Headers does not trim them).
const tokenArb = fc.stringMatching(/^[A-Za-z0-9._~+/=-]{1,64}$/);
const endpointArb = fc.constantFrom(...endpoints);

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Feature: dashboard, Property 6: The Authorization header is present on every request through the API client", () => {
  /** **Validates: Requirements 2.6** */
  it("sends Authorization: Bearer <token> from every endpoint function", async () => {
    await fc.assert(
      fc.asyncProperty(endpointArb, tokenArb, async (endpoint, token) => {
        fetchMock.mockReset();
        fetchMock.mockImplementation(async () => new Response("{}", { status: 200 }));

        await endpoint.call(token, () => {});

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${token}`);
      }),
      { numRuns: 100 },
    );
  });
});

describe("Feature: dashboard, Property 7: A 401 response always triggers sign-out, regardless of endpoint", () => {
  /** **Validates: Requirements 1.4** */
  it("calls onUnauthorized exactly once and throws ApiError 401 from every endpoint function", async () => {
    await fc.assert(
      fc.asyncProperty(endpointArb, tokenArb, fc.string(), async (endpoint, token, body) => {
        fetchMock.mockReset();
        fetchMock.mockImplementation(async () => new Response(body, { status: 401 }));
        const onUnauthorized = vi.fn();

        const error = await endpoint.call(token, onUnauthorized).then(
          () => null,
          (e: unknown) => e,
        );

        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(401);
        expect(onUnauthorized).toHaveBeenCalledTimes(1);
      }),
      { numRuns: 100 },
    );
  });
});
