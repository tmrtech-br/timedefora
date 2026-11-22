'use client';
import { cloneElement, isValidElement, useId } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react';
import type { ApiError } from '@/lib/api';

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export function Alert({ kind = 'info', children }: { kind?: 'info' | 'error' | 'ok' | 'warn'; children: React.ReactNode }) {
  const Icon = kind === 'error' ? XCircle : kind === 'ok' ? CheckCircle2 : kind === 'warn' ? AlertTriangle : Info;
  return <div className={`alert ${kind}`} role={kind === 'error' ? 'alert' : 'status'}><Icon aria-hidden />{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <Alert kind="error">
      <span>{error.message} {onRetry && <button className="btn sm" onClick={onRetry} style={{ marginLeft: 8 }}>Tentar novamente</button>}</span>
    </Alert>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Skeleton({ h = 120, w = '100%' }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} aria-hidden />;
}

export function Loading({ label = 'Carregando…' }: { label?: string }) {
  return <div className="row muted" role="status"><Loader2 className="spin" size={18} aria-hidden />{label}</div>;
}

export function Field({ label, error, children, hint }: { label: string; error?: string; children: React.ReactNode; hint?: string }) {
  const id = useId();
  const describedBy = [hint && !error ? `${id}-hint` : '', error ? `${id}-err` : ''].filter(Boolean).join(' ') || undefined;
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, { id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })
    : children;
  return (
    <div className={`field ${error ? 'invalid' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {control}
      {hint && !error && <span id={`${id}-hint`} className="dim small">{hint}</span>}
      {error && <span id={`${id}-err`} className="err" role="alert">{error}</span>}
    </div>
  );
}

const LABELS: Record<string, string> = {
  online: 'online', offline: 'offline', degraded: 'degradado', maintenance: 'manutenção', unconfigured: 'não configurado', disabled: 'desativado',
  pairing: 'pareando', error: 'erro', passed: 'aprovado', failed: 'falhou', not_available: 'indisponível', draft: 'rascunho',
  published: 'publicado', unpublished: 'despublicado', archived: 'arquivado', open: 'aberto', in_progress: 'em andamento', resolved: 'resolvido', closed: 'fechado',
};

export function StatusPill({ status, map, tone }: { status: string; map?: Record<string, string>; tone?: string }) {
  const t = tone || ({ confirmed: 'green', approved: 'green', active: 'cyan', completed: 'purple', pending_payment: 'amber', pending: 'amber',
    cancelled: 'red', rejected: 'red', expired: 'red', no_show: 'red', needs_resolution: 'amber', refunded: 'purple', online: 'green',
    offline: 'red', maintenance: 'amber', passed: 'green', failed: 'red', not_available: 'amber' } as Record<string, string>)[status] || '';
  return <span className={`pill ${t}`}>{map?.[status] || LABELS[status] || status}</span>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-bg" onClick={onClose} onKeyDown={(e) => e.key === 'Escape' && onClose()} role="presentation">
      <div className="card modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn sm" onClick={onClose} aria-label="Fechar" autoFocus>Fechar</button>
        </div>
        {children}
      </div>
    </div>
  );
}
