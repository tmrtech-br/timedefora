'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, get } from './api';

/** Busca dados da API com estados de carregamento/erro e atualização periódica opcional (tempo real por polling). */
export function useApi<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(!!path);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await get<T>(path);
      if (alive.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e : new ApiError(0, { detail: String(e) }));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    setLoading(!!path);
    load();
    if (!intervalMs || !path) return () => { alive.current = false; };
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, intervalMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [load, intervalMs, path]);
  return { data, error, loading, reload: load, setData };
}

/** Relógio sincronizado ao servidor: usa o server_time recebido e o desvio local. */
export function useServerClock(serverTimeIso?: string | null) {
  const [offset, setOffset] = useState(0);
  const [, tick] = useState(0);
  useEffect(() => {
    if (serverTimeIso) setOffset(new Date(serverTimeIso).getTime() - Date.now());
  }, [serverTimeIso]);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return () => Date.now() + offset;
}
