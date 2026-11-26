'use client';
import { useEffect } from 'react';

const KEY = 'locaplay:chunk-reload-at';
const isChunkError = (v: unknown) => {
  const s = String((v as { name?: string; message?: string })?.name || '') + ' ' + String((v as { message?: string })?.message || v || '');
  return /ChunkLoadError|Loading chunk .* failed|Loading CSS chunk|Failed to fetch dynamically imported module/i.test(s);
};

/**
 * Quando o site é atualizado (deploy) com a aba aberta, os arquivos antigos da página deixam de existir e o
 * navegador falha ao navegar ("Loading chunk ... failed"). Recarrega a página UMA vez para pegar a versão nova;
 * a trava de 30 s evita laço de recarga se o problema for outro (ex.: servidor fora do ar).
 */
export default function ChunkRecovery() {
  useEffect(() => {
    const recover = (reason: unknown) => {
      if (!isChunkError(reason)) return;
      let last = 0;
      try { last = Number(sessionStorage.getItem(KEY) || 0); } catch { /* armazenamento indisponível */ }
      if (Date.now() - last < 30_000) return;
      try { sessionStorage.setItem(KEY, String(Date.now())); } catch { /* idem */ }
      window.location.reload();
    };
    const onError = (e: ErrorEvent) => recover(e.error || e.message);
    const onRejection = (e: PromiseRejectionEvent) => recover(e.reason);
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => { window.removeEventListener('error', onError); window.removeEventListener('unhandledrejection', onRejection); };
  }, []);
  return null;
}
