'use client';
import { useState } from 'react';
import { Alert } from '@/components/ui';
import type { ApiError } from '@/lib/api';

export function useAction() {
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string; extra?: unknown } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setBusy(true); setMsg(null);
    try { const r = await fn(); if (ok) setMsg({ k: 'ok', t: ok }); return r; }
    catch (e) {
      const a = e as ApiError;
      const fields = a.fields && Object.keys(a.fields).length ? ' ' + Object.entries(a.fields).map(([k, v]) => `${k}: ${v}`).join(' · ') : '';
      setMsg({ k: 'error', t: a.message + fields, extra: a.data });
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
