'use client';
import { useEffect, useRef, useState } from 'react';
import { Alert } from '@/components/ui';
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

export const toLocalInput =(iso?: string | null) => iso ? new Date(new Date(iso).getTime() - 3 * 3600 * 1000).toISOString().slice(0, 16) : '';
export const fromLocalInput = (v: string) => (v ? new Date(v + ':00-03:00').toISOString() : null);
