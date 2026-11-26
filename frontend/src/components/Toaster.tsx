'use client';
import { useEffect, useState } from 'react';
import { CheckCircle2, X, XCircle } from 'lucide-react';

type Toast = { id: number; kind: 'ok' | 'error'; text: string };
const EVENT = 'lp-toast';

/** Mostra um aviso flutuante em qualquer tela (sobrevive a recarregamentos de componente). */
export function toast(kind: Toast['kind'], text: string) {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(EVENT, { detail: { kind, text } }));
}

export default function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    let seq = 0;
    const onToast = (e: Event) => {
      const { kind, text } = (e as CustomEvent<{ kind: Toast['kind']; text: string }>).detail;
      const id = ++seq;
      setItems((xs) => [...xs.slice(-3), { id, kind, text }]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), kind === 'error' ? 8000 : 4000);
    };
    window.addEventListener(EVENT, onToast);
    return () => window.removeEventListener(EVENT, onToast);
  }, []);
  if (!items.length) return null;
  return (
    <div className="toaster" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
          {t.kind === 'ok' ? <CheckCircle2 size={18} aria-hidden /> : <XCircle size={18} aria-hidden />}
          <span>{t.text}</span>
          <button aria-label="Fechar aviso" onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}><X size={15} /></button>
        </div>))}
    </div>
  );
}
