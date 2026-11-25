// The API token lives in sessionStorage only (never localStorage, cookies or memory-persisted files).
const KEY = "hh_api_token";

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch {
    // Storage unavailable: the session simply won't survive a reload.
  }
}

export function clearToken(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}
