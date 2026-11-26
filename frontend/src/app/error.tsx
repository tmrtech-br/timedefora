'use client';
import { useEffect } from 'react';
import { Alert } from '@/components/ui';

/** Erro numa página: se for arquivo desatualizado (site atualizado com a aba aberta), recarrega; senão oferece tentar de novo. */
export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const chunk = /ChunkLoadError|Loading chunk .* failed|Loading CSS chunk/i.test(`${error.name} ${error.message}`);
  useEffect(() => {
    if (!chunk) return;
    let last = 0;
    try { last = Number(sessionStorage.getItem('locaplay:chunk-reload-at') || 0); } catch { /* sem armazenamento */ }
    if (Date.now() - last > 30_000) {
      try { sessionStorage.setItem('locaplay:chunk-reload-at', String(Date.now())); } catch { /* idem */ }
      window.location.reload();
    }
  }, [chunk]);
  return (
    <Alert kind={chunk ? 'warn' : 'error'} dismissible={false}>
      <div className="stack">
        <strong>{chunk ? 'O site foi atualizado' : 'Algo deu errado nesta página'}</strong>
        <span>{chunk ? 'Recarregue para carregar a versão nova.' : 'Tente novamente. Se continuar, abra um chamado no suporte.'}</span>
        <div><button className="btn primary" onClick={() => (chunk ? window.location.reload() : reset())}>{chunk ? 'Recarregar' : 'Tentar novamente'}</button></div>
      </div>
    </Alert>
  );
}
