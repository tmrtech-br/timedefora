'use client';
import { useState } from 'react';
import { Alert, PageHeader, StatusPill } from '@/components/ui';
import { post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime, money, PAYMENT_STATUS } from '@/lib/format';
import { DataTable, useAction } from './common';

type R = Record<string, unknown>;
type Sum = { revenue_by_game: R[]; revenue_by_console: R[]; gross_cents: number; refunds_cents: number; net_cents: number; chargebacks: number; minutes_played: number; sessions: number; no_shows: number };

export default function Finance() {
  const today = new Date(Date.now() - 3 * 3600e3).toISOString().slice(0, 10);
  const [from, setFrom] = useState(today.slice(0, 8) + '01');
  const [to, setTo] = useState(today);
  const rangeErr = !from || !to ? 'Informe as duas datas.' : from > to ? 'A data inicial não pode ser maior que a data final.' : '';
  const range = rangeErr ? '' : `date_from=${new Date(from + 'T00:00:00-03:00').toISOString()}&date_to=${new Date(to + 'T23:59:59-03:00').toISOString()}`;
  const sum = useApi<Sum>(rangeErr ? null : `/admin/reports/summary?${range}`);
  const pays = useApi<R[]>('/admin/payments');
  const refunds = useApi<R[]>('/admin/refunds');
  const hooks = useApi<R[]>('/admin/webhooks');
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Financeiro e relatórios" />
      {msg}
      <section className="card stack">
        <div className="row"><input className="btn" type="date" aria-label="Data inicial" max={to || undefined} value={from} onChange={(e) => setFrom(e.target.value)} /> até <input className="btn" type="date" aria-label="Data final" min={from || undefined} value={to} onChange={(e) => setTo(e.target.value)} />
          {!rangeErr && ['payments', 'reservations', 'sessions', 'refunds'].map((k) => <a key={k} className="btn sm" href={`/api/admin/reports/export.csv?kind=${k}&${range}`}>CSV {k}</a>)}</div>
        {rangeErr && <Alert kind="error">{rangeErr}</Alert>}
        {sum.data && !rangeErr && <div className="kpis">{[['Bruto', money(sum.data.gross_cents)], ['Reembolsos', money(sum.data.refunds_cents)], ['Líquido', money(sum.data.net_cents)], ['Contestações', sum.data.chargebacks],
          ['Minutos jogados', sum.data.minutes_played], ['Sessões', sum.data.sessions], ['Ausências', sum.data.no_shows]].map(([l, v]) => <div key={String(l)} className="card kpi"><span>{l}</span><strong>{v}</strong></div>)}</div>}
        <div className="grid2"><DataTable rows={sum.data?.revenue_by_game || null} cols={[['Jogo', (r) => String(r.title)], ['Pagamentos', (r) => String(r.payments)], ['Receita', (r) => money(Number(r.revenue_cents))]]} />
          <DataTable rows={sum.data?.revenue_by_console || null} cols={[['Console', (r) => String(r.name)], ['Minutos vendidos', (r) => String(r.minutes_sold)], ['Receita', (r) => money(Number(r.revenue_cents))]]} /></div>
      </section>
      <section className="card"><h2>Pagamentos</h2><DataTable rows={pays.data} cols={[['Data', (r) => dateTime(String(r.created_at))], ['Reserva', (r) => String(r.reservation_code)], ['Usuário', (r) => String(r.username)],
        ['Provedor', (r) => String(r.provider)], ['Valor', (r) => money(Number(r.amount_cents))], ['Status', (r) => <StatusPill status={String(r.status)} map={PAYMENT_STATUS} />],
        ['', (r) => <div className="row">{r.status === 'approved' && <button className="btn sm" onClick={() => { const v = prompt('Valor do reembolso em R$:', String(Number(r.amount_cents) / 100)); const reason = v && prompt('Motivo:'); if (v && reason) run(async () => { await post(`/admin/payments/${r.id}/refund`, { amount_cents: Math.round(Number(v.replace(',', '.')) * 100), reason }); pays.reload(); refunds.reload(); }, 'Reembolso processado.'); }}>Reembolsar</button>}
          {r.provider === 'mercadopago' && <button className="btn sm" onClick={() => run(async () => { await post(`/admin/payments/${r.id}/reconcile`); pays.reload(); }, 'Conciliado.')}>Conciliar</button>}</div>]]} /></section>
      <section className="card"><h2>Reembolsos</h2><DataTable rows={refunds.data} cols={[['Data', (r) => dateTime(String(r.created_at))], ['Reserva', (r) => String(r.reservation_code)], ['Valor', (r) => money(Number(r.amount_cents))], ['Motivo', (r) => String(r.reason)], ['Status', (r) => String(r.status)]]} /></section>
      <section className="card"><h2>Webhooks recebidos</h2><DataTable rows={hooks.data} cols={[['Recebido', (r) => dateTime(String(r.received_at))], ['Provedor', (r) => String(r.provider)], ['Recurso', (r) => String(r.resource_id)],
        ['Assinatura', (r) => (r.signature_valid ? 'válida' : 'inválida')], ['Processamento', (r) => String(r.processing_status)], ['Erro', (r) => String(r.error || '')]]} /></section>
    </div>
  );
}
