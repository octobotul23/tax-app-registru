/** Session context: who is signed in, and how to sign in or out. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError } from "../api/client";
import type { User } from "../api/types";

interface AuthValue {
  user: User | null;
  /** True until the initial "am I signed in?" check has finished. */
  checking: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch (cause) {
      // A 401 here is the normal "not signed in yet" case, not a failure.
      if (cause instanceof ApiError && cause.isUnauthorized) {
        setUser(null);
      } else {
        throw cause;
      }
    }
  }, []);

  useEffect(() => {
    refresh()
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, [refresh]);

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password));
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      // Clear locally even if the request failed - the cookie may already be
      // expired, and leaving a stale user on screen is worse.
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ user, checking, signIn, signOut, refresh }),
    [user, checking, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider");
  return context;
}
