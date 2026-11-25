import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { clearToken, getToken, setToken } from "./tokenStorage";

export const TOKEN_REJECTED_MESSAGE =
  "Token rejected: the Brain did not accept this API token. Please sign in again.";

export interface AuthContextValue {
  token: string | null;
  /** Message shown on the login screen after a 401, or null. */
  message: string | null;
  signIn: (token: string) => void;
  signOut: () => void;
  /** Called by the API client on any 401: clears storage, signs out, sets the message. */
  onUnauthorized: () => void;
  clearMessage: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [message, setMessage] = useState<string | null>(null);

  const signIn = useCallback((next: string) => {
    setToken(next);
    setTokenState(next);
    setMessage(null);
  }, []);

  const signOut = useCallback(() => {
    clearToken();
    setTokenState(null);
  }, []);

  const onUnauthorized = useCallback(() => {
    clearToken();
    setTokenState(null);
    setMessage(TOKEN_REJECTED_MESSAGE);
  }, []);

  const clearMessage = useCallback(() => setMessage(null), []);

  const value = useMemo(
    () => ({ token, message, signIn, signOut, onUnauthorized, clearMessage }),
    [token, message, signIn, signOut, onUnauthorized, clearMessage],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
