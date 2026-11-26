'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';

/** Busca dados da API com estados de carregamento/erro e atualização periódica opcional (tempo real por polling). */
export function useApi<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(!!path);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    if (!path) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const d = await api<T>(path, { signal: controller.signal });
      if (!controller.signal.aborted) { setData(d); setError(null); }
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof ApiError ? e : new ApiError(0, { detail: String(e) }));
    } finally {
      if (request.current === controller) {
        request.current = null;
        setLoading(false);
      }
    }
  }, [path]);
  useEffect(() => {
    setLoading(!!path);
    setError(null);
    load();
    const timer = intervalMs && path ? setInterval(() => {
      if (!request.current && document.visibilityState === 'visible') load();
    }, intervalMs) : undefined;
    return () => {
      request.current?.abort();
      request.current = null;
      clearInterval(timer);
    };
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
