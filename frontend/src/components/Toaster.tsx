'use client';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';

export type NoticeKind = 'ok' | 'error' | 'warn' | 'info';
type Toast = { id: number; kind: NoticeKind; text: string };
const EVENT = 'lp-toast';
const DIALOG_EVENT = 'lp-toast-dialog';
const NoticeViewport = createContext<HTMLDivElement | null>(null);
const icons = { ok: CheckCircle2, error: XCircle, warn: AlertTriangle, info: Info };

/** Mostra um aviso flutuante em qualquer tela (sobrevive a recarregamentos de componente). */
export function toast(kind: Toast['kind'], text: string) {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(EVENT, { detail: { kind, text } }));
}

export function updateNoticeDialog() {
  window.dispatchEvent(new Event(DIALOG_EVENT));
}

function Notice({ kind, children, onDismiss }: { kind: NoticeKind; children: ReactNode; onDismiss?: () => void }) {
  const Icon = icons[kind];
  return (
    <div className={`alert toast ${kind}`}>
      <Icon className="toast-icon" aria-hidden />
      <div className="toast-content" role={kind === 'error' ? 'alert' : 'status'}>{children}</div>
      {onDismiss && <button type="button" className="toast-close" aria-label="Fechar aviso" onClick={onDismiss}><X aria-hidden /></button>}
    </div>
  );
}

export function SystemAlert({ kind, children, dismissible }: { kind: NoticeKind; children: ReactNode; dismissible: boolean }) {
  const viewport = useContext(NoticeViewport);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (!viewport || !dismissible) return;
    const timer = window.setTimeout(() => setDismissed(true), kind === 'ok' ? 5000 : 12000);
    return () => window.clearTimeout(timer);
  }, [viewport, dismissible, kind]);
  return viewport && !dismissed ? createPortal(
    <Notice kind={kind} onDismiss={dismissible ? () => setDismissed(true) : undefined}>{children}</Notice>,
    viewport,
  ) : null;
}

export default function Toaster({ children }: { children: ReactNode }) {
  const [viewport, setViewport] = useState<HTMLDivElement | null>(null);
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const container = document.createElement('div');
    container.className = 'toaster';
    const position = () => {
      const parent = Array.from(document.querySelectorAll('.modal-shell:modal')).at(-1)
        ?? document.fullscreenElement ?? document.body;
      if (container.parentElement !== parent) parent.append(container);
    };
    position();
    setViewport(container);
    window.addEventListener(DIALOG_EVENT, position);
    document.addEventListener('fullscreenchange', position);
    let seq = 0;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const onToast = (e: Event) => {
      const { kind, text } = (e as CustomEvent<{ kind: Toast['kind']; text: string }>).detail;
      const id = ++seq;
      setItems((xs) => [...xs.slice(-3), { id, kind, text }]);
      const timer = setTimeout(() => {
        timers.delete(timer);
        setItems((xs) => xs.filter((x) => x.id !== id));
      }, kind === 'ok' ? 4000 : 8000);
      timers.add(timer);
    };
    window.addEventListener(EVENT, onToast);
    return () => {
      window.removeEventListener(EVENT, onToast);
      window.removeEventListener(DIALOG_EVENT, position);
      document.removeEventListener('fullscreenchange', position);
      timers.forEach(clearTimeout);
      container.remove();
    };
  }, []);
  return (
    <NoticeViewport.Provider value={viewport}>
      {children}
      {viewport && createPortal(
        <>
          {items.map((t) => (
            <Notice key={t.id} kind={t.kind} onDismiss={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>{t.text}</Notice>
          ))}
        </>,
        viewport,
      )}
    </NoticeViewport.Provider>
  );
}
