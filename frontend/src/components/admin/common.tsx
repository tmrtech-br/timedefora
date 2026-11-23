'use client';
import { useState } from 'react';
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
};

export function useAction() {
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string; extra?: unknown } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setBusy(true); setMsg(null);
    try { const r = await fn(); if (ok) { setMsg({ k: 'ok', t: ok }); toast('ok', ok); } return r; }
    catch (e) {
      const a = e as ApiError;
      const fields = a.fields && Object.keys(a.fields).length
        ? ' ' + Object.entries(a.fields).map(([k, v]) => `${FIELD_LABELS[k] || k}: ${String(v).replace(/^Valor inválido\.?$/, 'preencha corretamente')}`).join(' · ') : '';
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

export const toLocalInput = (iso?: string | null) => iso ? new Date(new Date(iso).getTime() - 3 * 3600 * 1000).toISOString().slice(0, 16) : '';
export const fromLocalInput = (v: string) => (v ? new Date(v + ':00-03:00').toISOString() : null);
