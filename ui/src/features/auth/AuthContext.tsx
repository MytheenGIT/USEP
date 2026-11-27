import { createContext, ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { api } from "../../shared/api/client";
import { ApiError, Session } from "../../shared/api/types";

interface AuthApi {
  session: Session | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Call when any request answers 401: the session is gone, so show the sign-in page. */
  expire: () => void;
}

const AuthContext = createContext<AuthApi | null>(null);

// The token lives in memory only: a page reload signs the admin out. Nothing is written to browser storage.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);

  const signIn = useCallback(async (username: string, password: string) => {
    setSession(await api.login(username.trim(), password));
  }, []);

  const signOut = useCallback(async () => {
    const token = session?.token;
    setSession(null);
    if (token) await api.logout(token).catch(() => undefined);
  }, [session]);

  const expire = useCallback(() => setSession(null), []);
  const value = useMemo(() => ({ session, signIn, signOut, expire }), [session, signIn, signOut, expire]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** The signed-in session, plus a wrapper that signs out when the API says 401. */
export function useSession(): { session: Session; guard: <T>(p: Promise<T>) => Promise<T> } {
  const { session, expire } = useAuth();
  if (!session) throw new Error("useSession requires a signed-in user");
  const guard = useCallback(
    <T,>(p: Promise<T>) =>
      p.catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) expire();
        throw e;
      }),
    [expire],
  );
  return { session, guard };
}
