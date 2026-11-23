'use client';
import { useEffect, useRef, useState } from 'react';
import { Alert, Field, Modal } from '@/components/ui';
import type { ApiError } from '@/lib/api';
import { toast } from '@/components/Toaster';

/** Nomes dos campos da API em português (para mensagens de validação). */
export const FIELD_LABELS: Record<string, string> = {
  starts_at: 'Início', ends_at: 'Fim', console_id: 'Console', game_id: 'Jogo', reason: 'Motivo/justificativa', name: 'Nome', code: 'Código',
  title: 'Título', slug: 'Slug', minutes: 'Minutos', price_cents: 'Preço', valid_from: 'Válido de', valid_until: 'Válido até', occurrences: 'Ocorrências',
  discount_value: 'Desconto', discount_type: 'Tipo de desconto', email: 'E-mail', username: 'Nome de usuário', full_name: 'Nome completo',
  channel_name: 'Nome do canal', external_url: 'URL', provider: 'Plataforma', version: 'Versão', body: 'Texto', subject: 'Assunto', value: 'Valor',
  host_name: 'Host', endpoint_url: 'Endpoint', platform_code: 'Plataforma', model: 'Modelo', serial: 'Série', location: 'Localização', method: 'Método',
  agent_id: 'Agente', manufacturer: 'Fabricante', device_identifier: 'Device ID', input_port: 'Entrada', identifier: 'Identificador', adapter_type: 'Tipo',
  max_redemptions: 'Limite total', per_user_limit: 'Limite por usuário', compensation: 'Compensação', compensation_notes: 'Observações',
  platform_codes: 'Plataformas', min_minutes: 'Duração mínima', max_minutes: 'Duração máxima', description: 'Descrição', kind: 'Tipo',
  date_from: 'Data inicial', date_to: 'Data final', amount_cents: 'Valor',
};

/** Validação no navegador: interrompe a ação com uma mensagem clara (exibida pelo useAction). */
export function need(ok: unknown, message: string): asserts ok {
  if (!ok) throw new Error(message);
}

/** Agora, no formato do <input type="datetime-local"> (horário de Fortaleza). */
export const nowLocalInput = () => new Date(Date.now() - 3 * 3600 * 1000).toISOString().slice(0, 16);

export function useAction() {
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string; extra?: unknown } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setBusy(true); setMsg(null);
    try { const r = await fn(); if (ok) { setMsg({ k: 'ok', t: ok }); toast('ok', ok); } return r; }
    catch (e) {
      const a = e as ApiError;
      const fields = a.fields && Object.keys(a.fields).length
        ? ' Corrija: ' + Object.entries(a.fields).map(([k, v]) => `${FIELD_LABELS[k] || k} (${String(v).replace(/^Valor inválido\.?$/, 'valor inválido ou não preenchido').replace(/^Campo obrigatório\.?$/, 'obrigatório')})`).join(' · ') + '.' : '';
      setMsg({ k: 'error', t: a.message + fields, extra: a.data });
      toast('error', a.message + fields);
    } finally { setBusy(false); }
  }
  const view = msg ? <Alert kind={msg.k}><span>{msg.t}{Array.isArray((msg.extra as { reservations?: unknown[] })?.reservations) &&
    <ul>{((msg.extra as { reservations: { code: string; starts_at: string }[] }).reservations).map((r) => <li key={r.code}>{r.code} — {new Date(r.starts_at).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' })}</li>)}</ul>}</span></Alert> : null;
  return { run, msg: view, busy };
}

export function DataTable<T extends Record<string, unknown>>({ rows, cols, empty = 'Nenhum registro.' }: {
  rows: T[] | null; cols: [string, (r: T) => React.ReactNode][]; empty?: string }) {
  if (!rows) return <div className="skeleton" style={{ height: 120 }} />;
  if (!rows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap"><table className="table"><thead><tr>{cols.map(([h]) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={String(r.id ?? i)}>{cols.map(([h, f]) => <td key={h}>{f(r)}</td>)}</tr>)}</tbody></table></div>
  );
}

/** Lista suspensa com marcação múltipla (aparência de <select>, sem caixa com rolagem). */
export function MultiSelect({ options, value, onChange, placeholder = 'Selecione', label }: {
  options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void; placeholder?: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  const text = options.filter((o) => value.includes(o.value)).map((o) => o.label).join(', ');
  return (
    <div className="multi-select" ref={ref}>
      <button type="button" className="multi-select-btn" aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={() => setOpen(!open)}>
        <span className={text ? '' : 'dim'}>{text || placeholder}</span>
      </button>
      {open && (
        <div className="multi-select-menu" role="listbox" aria-multiselectable="true">
          {options.map((o) => (
            <label key={o.value} className="multi-select-opt" role="option" aria-selected={value.includes(o.value)}>
              <input type="checkbox" checked={value.includes(o.value)}
                onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((x) => x !== o.value))} />{o.label}
            </label>))}
        </div>)}
    </div>
  );
}

type AskOpts = { title: string; label: string; message?: React.ReactNode; confirm?: string; danger?: boolean; minLength?: number;
  defaultValue?: string; placeholder?: string; inputMode?: 'text' | 'decimal'; validate?: (v: string) => string | null };

/** Diálogo do sistema para pedir um texto (motivo, observação, valor) — substitui o prompt() do navegador.
 *  Uso: const [ask, askDialog] = useAsk(); const motivo = await ask({...}); if (motivo === null) return; e renderize {askDialog}. */
export function useAsk(): [(o: AskOpts) => Promise<string | null>, React.ReactNode] {
  const [state, setState] = useState<{ o: AskOpts; resolve: (v: string | null) => void } | null>(null);
  const [value, setValue] = useState('');
  const [err, setErr] = useState('');
  const ask = (o: AskOpts) => new Promise<string | null>((resolve) => { setValue(o.defaultValue || ''); setErr(''); setState({ o, resolve }); });
  const close = (v: string | null) => { state?.resolve(v); setState(null); };
  const submit = () => {
    if (!state) return;
    const v = value.trim(), min = state.o.minLength ?? 3;
    if (v.length < min) { setErr(min <= 1 ? 'Preencha este campo.' : `Escreva pelo menos ${min} caracteres (fica registrado na auditoria).`); return; }
    const custom = state.o.validate?.(v);
    if (custom) { setErr(custom); return; }
    close(v);
  };
  const dialog = state ? (
    <Modal title={state.o.title} onClose={() => close(null)}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {state.o.message && <div className="small muted">{state.o.message}</div>}
        <Field label={state.o.label} required error={err || undefined}>
          {state.o.inputMode === 'decimal'
            ? <input autoFocus inputMode="decimal" value={value} placeholder={state.o.placeholder} onChange={(e) => setValue(e.target.value)} />
            : <textarea autoFocus rows={3} maxLength={500} value={value} placeholder={state.o.placeholder} onChange={(e) => setValue(e.target.value)} />}
        </Field>
        <div className="row">
          <button type="submit" className={`btn ${state.o.danger ? 'danger' : 'primary'}`}>{state.o.confirm || 'Confirmar'}</button>
          <button type="button" className="btn" onClick={() => close(null)}>Voltar</button>
        </div>
      </form>
    </Modal>) : null;
  return [ask, dialog];
}

/** Confirmação "sim/não" no padrão do site (substitui o confirm() do navegador). */
export function useConfirm(): [(o: { title: string; message: React.ReactNode; confirm?: string; danger?: boolean }) => Promise<boolean>, React.ReactNode] {
  const [state, setState] = useState<{ o: { title: string; message: React.ReactNode; confirm?: string; danger?: boolean }; resolve: (v: boolean) => void } | null>(null);
  const ask = (o: { title: string; message: React.ReactNode; confirm?: string; danger?: boolean }) => new Promise<boolean>((resolve) => setState({ o, resolve }));
  const close = (v: boolean) => { state?.resolve(v); setState(null); };
  const dialog = state ? (
    <Modal title={state.o.title} onClose={() => close(false)}>
      <div className="stack">
        <div className="small muted">{state.o.message}</div>
        <div className="row">
          <button autoFocus className={`btn ${state.o.danger ? 'danger' : 'primary'}`} onClick={() => close(true)}>{state.o.confirm || 'Confirmar'}</button>
          <button className="btn" onClick={() => close(false)}>Voltar</button>
        </div>
      </div>
    </Modal>) : null;
  return [ask, dialog];
}

export const toLocalInput = (iso?: string | null) => iso ? new Date(new Date(iso).getTime() - 3 * 3600 * 1000).toISOString().slice(0, 16) : '';
export const fromLocalInput = (v: string) => (v ? new Date(v + ':00-03:00').toISOString() : null);
