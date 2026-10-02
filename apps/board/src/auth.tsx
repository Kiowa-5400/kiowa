import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, ApiError, onUnauthorized, setCsrfToken } from '@shared/api';

export type BoardSession = {
  csrf_token: string;
  person: { id: number; first_name: string; last_name: string; email: string };
  role: string;
  role_label: string;
  position: string | null;
  permissions: string[];
};

type AuthValue = {
  session: BoardSession | null;
  checking: boolean;
  can: (permission: string) => boolean;
  signIn: (email: string, password: string, remember: boolean) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<BoardSession | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api<BoardSession>('/api/board/auth/session', { quiet401: true })
      .then(setSession)
      .catch((error) => {
        if (!(error instanceof ApiError && error.status === 401)) console.error(error);
      })
      .finally(() => setChecking(false));
    return onUnauthorized(() => {
      setSession(null);
      setCsrfToken(null);
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string, remember: boolean) => {
    setSession(await api<BoardSession>('/api/board/auth/login', { body: { email, password, remember }, quiet401: true }));
  }, []);

  const signOut = useCallback(async () => {
    await api('/api/board/auth/logout', { method: 'POST' }).catch(() => undefined);
    setCsrfToken(null);
    setSession(null);
  }, []);

  const can = useCallback((permission: string) => Boolean(session?.permissions.includes(permission)), [session]);

  return <AuthContext.Provider value={{ session, checking, can, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
