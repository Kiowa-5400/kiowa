import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, ApiError, onUnauthorized, setCsrfToken } from '@shared/api';
import type { Profile } from './types';

type Session = { csrf_token: string; profile: Profile };

type AuthValue = {
  profile: Profile | null;
  checking: boolean;
  signIn: (email: string, password: string, remember: boolean) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  setProfile: (profile: Profile) => void;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const session = await api<Session>('/api/auth/session', { quiet401: true });
      setProfile(session.profile);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
      setProfile(null);
      setCsrfToken(null);
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setProfile(null)).finally(() => setChecking(false));
    return onUnauthorized((error) => {
      if (error.code !== 'preview_locked') {
        setProfile(null);
        setCsrfToken(null);
      }
    });
  }, [refresh]);

  const signIn = useCallback(async (email: string, password: string, remember: boolean) => {
    const session = await api<Session>('/api/auth/login', { body: { email, password, remember }, quiet401: true });
    setProfile(session.profile);
  }, []);

  const signOut = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
    setCsrfToken(null);
    setProfile(null);
  }, []);

  return (
    <AuthContext.Provider value={{ profile, checking, signIn, signOut, refresh, setProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}

/** Profile for pages that only render when signed in. */
export function useProfile(): Profile {
  const { profile } = useAuth();
  if (!profile) throw new Error('useProfile requires a signed-in member');
  return profile;
}
