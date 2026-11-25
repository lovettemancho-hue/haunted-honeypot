import { useState, type FormEvent } from "react";
import { fetchStats } from "../api/stats";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function LoginScreen() {
  const { message, signIn, onUnauthorized, clearMessage } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = token.trim();
    clearMessage();
    if (!candidate) {
      setError("Enter your API token to continue.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await fetchStats(candidate, onUnauthorized);
      signIn(candidate);
    } catch (err) {
      // A 401 already set the AuthContext message through onUnauthorized.
      if (!(err instanceof ApiError && err.status === 401)) {
        setError("Could not reach the lab or it returned an unexpected response. Try again shortly.");
      }
      setBusy(false);
    }
  }

  return (
    <main className="page login-page">
      <form className="panel panel--bolted login-form" onSubmit={onSubmit} noValidate>
        <h1>Haunted Honeypot</h1>
        <p>Sign in to the lab with your API token to view captured attacker activity.</p>
        <label htmlFor="api-token">API token</label>
        <input
          id="api-token"
          name="api-token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        {message ? (
          <p className="form-message" role="alert">
            {message}
          </p>
        ) : null}
        {error ? (
          <p className="form-message" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn btn--primary login-submit" disabled={busy}>
          {busy ? "Checking…" : "Enter the lab"}
        </button>
      </form>
    </main>
  );
}
