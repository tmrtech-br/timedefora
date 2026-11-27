'use client';
import { cloneElement, isValidElement, useEffect, useId, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { ApiError } from '@/lib/api';
import { SystemAlert, updateNoticeDialog, type NoticeKind } from './Toaster';

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export function Alert({ kind = 'info', children, dismissible = true }: { kind?: NoticeKind; children: React.ReactNode; dismissible?: boolean }) {
  return <SystemAlert key={typeof children === 'string' ? `${kind}:${children}` : kind} kind={kind} dismissible={dismissible}>{children}</SystemAlert>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <Alert key={error.message} kind="error" dismissible={!onRetry}>
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

/** Limite padrão de caracteres dos campos de texto do site (campos mais longos informam `maxLength` explicitamente). */
export const TEXT_MAX = 50;
const TEXTAREA_MAX = 2000;
const COUNTED_TYPES = new Set(['text', 'search', 'tel', 'url']);

type ControlProps = { type?: string; value?: unknown; maxLength?: number; onBlur?: (e: React.FocusEvent) => void; [k: string]: unknown };

/**
 * Campo com rótulo, dica, erro, contador de caracteres e obrigatoriedade.
 * - Inputs de texto recebem `maxLength` padrão de 50 (textarea: 2000) e exibem o contador "n/máx".
 * - `required`: ao sair do campo vazio, mostra "Preencha este campo." (o servidor também valida).
 */
export function Field({ label, error, children, hint, help, required }: { label: string; error?: string; children: React.ReactNode; hint?: string; help?: string; required?: boolean }) {
  const id = useId();
  const [touched, setTouched] = useState(false);
  const el = isValidElement<ControlProps>(children) ? children : null;
  const tag = el && typeof el.type === 'string' ? el.type : '';
  const props = (el?.props || {}) as ControlProps;
  const isText = tag === 'textarea' || (tag === 'input' && COUNTED_TYPES.has(props.type ?? 'text'));
  const max = isText ? (props.maxLength ?? (tag === 'textarea' ? TEXTAREA_MAX : TEXT_MAX)) : props.maxLength;
  const value = typeof props.value === 'string' ? props.value : null;
  const emptyErr = required && touched && value !== null && !value.trim() ? 'Preencha este campo.' : undefined;
  const shownError = error || emptyErr;
  const describedBy = [hint && !shownError ? `${id}-hint` : '', shownError ? `${id}-err` : '', isText && value !== null ? `${id}-count` : ''].filter(Boolean).join(' ') || undefined;
  const control = el
    ? cloneElement(el, {
      id, 'aria-describedby': describedBy, 'aria-invalid': shownError ? true : undefined,
      ...(max ? { maxLength: max } : {}), ...(required ? { required: true, 'aria-required': true } : {}),
      onBlur: (e: React.FocusEvent) => { setTouched(true); props.onBlur?.(e); },
    })
    : children;
  const near = max && value !== null && value.length >= max * 0.9;
  return (
    <div className={`field ${shownError ? 'invalid' : ''}`}>
      <div className="field-label">
        <label htmlFor={id}>{label}{required && <span className="req" aria-hidden> *</span>}</label>
        {help && <FieldHelp text={help} />}
      </div>
      {control}
      <div className="field-foot">
        <span>
          {hint && !shownError && <span id={`${id}-hint`} className="dim small">{hint}</span>}
          {shownError && <span id={`${id}-err`} className="err" role="alert">{shownError}</span>}
        </span>
        {isText && max && value !== null && <span id={`${id}-count`} className={`counter ${near ? 'near' : ''}`} aria-live="polite">{value.length}/{max}</span>}
      </div>
    </div>
  );
}

export function FieldHelp({ text }: { text: string }) {
  const id = useId();
  const tooltip = useRef<HTMLSpanElement>(null);
  function show(anchor: HTMLButtonElement) {
    const help = tooltip.current;
    if (!help) return;
    if (!help.matches(':popover-open')) help.showPopover();
    const rect = anchor.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, document.documentElement.clientWidth - help.offsetWidth - 8));
    const top = rect.top >= help.offsetHeight + 14 ? rect.top - help.offsetHeight - 6 : rect.bottom + 6;
    help.style.left = `${left}px`;
    help.style.top = `${top}px`;
  }
  function hide() {
    if (tooltip.current?.matches(':popover-open')) tooltip.current.hidePopover();
  }
  return <span className="field-help">
    <button type="button" aria-label="Ajuda sobre o campo" aria-describedby={id}
      onMouseEnter={(e) => show(e.currentTarget)} onMouseLeave={hide}
      onFocus={(e) => show(e.currentTarget)} onBlur={hide}
      onKeyDown={(e) => { if (e.key === 'Escape' && tooltip.current?.matches(':popover-open')) { e.preventDefault(); hide(); } }}>?</button>
    <span id={id} ref={tooltip} popover="manual" role="tooltip">{text}</span>
  </span>;
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

export function ModalShell({ title, onClose, children, allowEscape = false, closeLabel = 'Fechar', closeButtonClassName = 'sm', showCloseButton = true, compact = false }: {
  title: string; onClose: () => void; children: React.ReactNode; allowEscape?: boolean; closeLabel?: string; closeButtonClassName?: string; showCloseButton?: boolean; compact?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    updateNoticeDialog();
    return () => {
      node?.close();
      updateNoticeDialog();
    };
  }, []);
  return (
    <dialog ref={dialog} className={`card modal modal-shell${compact ? ' modal-compact' : ''}`} aria-modal="true" aria-label={title} onCancel={(event) => {
      // O backdrop nunca fecha o diálogo. Esc é opt-in para telas que não guardam alterações.
      event.preventDefault();
      if (allowEscape) onClose();
    }}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          {showCloseButton && <button type="button" className={`btn ${closeButtonClassName}`} onClick={onClose} autoFocus>{closeLabel}</button>}
        </div>
        {children}
    </dialog>
  );
}

export const Modal = ModalShell;
