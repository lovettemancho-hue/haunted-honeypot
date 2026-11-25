import { useCallback } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { fetchStats } from "../api/stats";
import { AuthProvider, TOKEN_REJECTED_MESSAGE, useAuth } from "../auth/AuthContext";
import { usePoller } from "../hooks/usePoller";
import { LoginScreen } from "./LoginScreen";

const KEY = "hh_api_token";

function jsonResponse(status: number): Response {
  return new Response(status === 200 ? "{}" : "", { status });
}

function submitToken(token: string) {
  fireEvent.change(screen.getByLabelText("API token"), { target: { value: token } });
  fireEvent.click(screen.getByRole("button", { name: /enter the lab/i }));
}

/** Stands in for a page: polls /api/stats with the auth context's onUnauthorized. */
function PollingPage() {
  const { token, onUnauthorized } = useAuth();
  const fetchFn = useCallback(() => fetchStats(token ?? "", onUnauthorized), [token, onUnauthorized]);
  usePoller(fetchFn, { intervalMs: 5000, enabled: true });
  return <p>poller page</p>;
}

function PollerGate() {
  const { token } = useAuth();
  return token ? <PollingPage /> : <LoginScreen />;
}

describe("login and auth flow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("200 stores the token in sessionStorage and shows the signed-in app", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200));
    render(<App />);
    submitToken("good-token");

    await screen.findByRole("heading", { name: "Lab Monitor" });
    expect(sessionStorage.getItem(KEY)).toBe("good-token");
    expect(screen.queryByLabelText("API token")).toBeNull();

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/stats");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer good-token");
  });

  it("401 shows token rejected and stores nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(401));
    render(<App />);
    submitToken("bad-token");

    await screen.findByText(TOKEN_REJECTED_MESSAGE);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(screen.getByLabelText("API token")).toBeTruthy();
  });

  it("network error shows an error and stores nothing", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    submitToken("any-token");

    await screen.findByText(/could not reach the lab/i);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(screen.getByLabelText("API token")).toBeTruthy();
  });

  it("other status (500) shows an error and stores nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500));
    render(<App />);
    submitToken("any-token");

    await screen.findByText(/could not reach the lab/i);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(screen.queryByText(TOKEN_REJECTED_MESSAGE)).toBeNull();
  });

  it("empty token shows a prompt and makes no request", () => {
    render(<App />);
    submitToken("   ");
    expect(screen.getByText(/enter your api token/i)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("starts signed in when a token is already in sessionStorage", async () => {
    sessionStorage.setItem(KEY, "saved");
    render(<App />);
    await screen.findByRole("heading", { name: "Lab Monitor" });
  });

  it("sign-out clears the token and returns to the login screen", async () => {
    sessionStorage.setItem(KEY, "saved");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /sign out/i }));

    await screen.findByLabelText("API token");
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("a 401 from a page poller returns to the login screen with a rejected message", async () => {
    sessionStorage.setItem(KEY, "expired");
    fetchMock.mockResolvedValue(jsonResponse(401));
    render(
      <AuthProvider>
        <PollerGate />
      </AuthProvider>,
    );

    await screen.findByText(TOKEN_REJECTED_MESSAGE);
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBeNull());
    expect(screen.getByLabelText("API token")).toBeTruthy();
    expect(screen.queryByText("poller page")).toBeNull();
  });
});
