'use client';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { ApiError, get, post } from './api';
import type { Me } from './types';

type Ctx = { me: Me | null; loading: boolean; refresh: () => Promise<void>; logout: () => Promise<void> };
const AuthCtx = createContext<Ctx>({ me: null, loading: true, refresh: async () => {}, logout: async () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const s = await get<{ authenticated: boolean; user?: Me }>('/me/session');
      setMe(s.authenticated && s.user ? s.user : null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);
  const logout = useCallback(async () => {
    try { await post('/auth/logout'); } catch { /* sessão já encerrada */ }
    setMe(null);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return <AuthCtx.Provider value={{ me, loading, refresh, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
export const isStaff = (me: Me | null) => !!me && me.roles.some((r) => ['operator', 'admin', 'superadmin'].includes(r));
