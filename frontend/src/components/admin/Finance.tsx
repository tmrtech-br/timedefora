'use client';
import DateFilter from '@/components/DateFilter';
import { exportExcel } from './exportReport';
import { useState } from 'react';
import { Alert, PageHeader, StatusPill } from '@/components/ui';
import { get, post } from '@/lib/api';
import { downloadReportPdf } from '@/lib/reportPdf';
import { useApi } from '@/lib/hooks';
import { dateTime, money, PAYMENT_STATUS } from '@/lib/format';
import { DataTable, useAction, useAsk } from './common';

type R = Record<string, unknown>;
type Sum = { revenue_by_game: R[]; revenue_by_console: R[]; gross_cents: number; refunds_cents: number; net_cents: number; chargebacks: number; minutes_played: number; sessions: number; no_shows: number };

const CSV_REPORTS = { payments: 'Pagamentos', reservations: 'Reservas', sessions: 'Sessões', refunds: 'Reembolsos' };

function financialTables(report: Sum) {
  return [
    { title: 'Resumo financeiro', headers: ['Indicador', 'Valor'], rows: [
      ['Receita bruta', money(report.gross_cents)], ['Reembolsos', money(report.refunds_cents)], ['Receita líquida', money(report.net_cents)],
      ['Contestações', report.chargebacks], ['Sessões', report.sessions], ['Minutos jogados', report.minutes_played], ['Ausências', report.no_shows],
    ] },
    { title: 'Receita por jogo', headers: ['Jogo', 'Pagamentos', 'Receita'],
      rows: report.revenue_by_game.map((row) => [String(row.title), Number(row.payments), money(Number(row.revenue_cents))]) },
    { title: 'Receita por console', headers: ['Console', 'Minutos vendidos', 'Receita'],
      rows: report.revenue_by_console.map((row) => [String(row.name), Number(row.minutes_sold), money(Number(row.revenue_cents))]) },
  ];
}

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
  const { run, msg, busy } = useAction();
  const [ask, askDialog] = useAsk();
  return (
    <div className="stack">
      <PageHeader title="Financeiro e relatórios">
          <button className="btn primary" disabled={busy || Boolean(rangeErr)} onClick={() => run(async () => {
            const report = await get<Sum>(`/admin/reports/summary?${range}`);
            downloadReportPdf('Relatório financeiro', `${from.split('-').reverse().join('/')} a ${to.split('-').reverse().join('/')}`,
              financialTables(report), `timedefora-financeiro-${from}-${to}.pdf`);
          }, 'Relatório PDF gerado.')}>Exportar PDF</button>
          <button className="btn" disabled={busy || Boolean(rangeErr)} onClick={() => run(async () => {
            const report = await get<Sum>(`/admin/reports/summary?${range}`);
            exportExcel(`timedefora-financeiro-${from}-${to}`, financialTables(report), { title: 'Relatório financeiro',
              subtitle: `${from.split('-').reverse().join('/')} a ${to.split('-').reverse().join('/')}` });
          }, 'Planilha gerada.')}>Exportar Excel</button>
      </PageHeader>
      {msg}
      <section className="card stack"><h2>Resumo e exportação</h2>
        <div className="row finance-dates">
          <DateFilter label="Data inicial" max={to || undefined} value={from} onChange={setFrom} />
          <DateFilter label="Data final" min={from || undefined} value={to} onChange={setTo} />
          {!rangeErr && <div className="row finance-csv">{Object.entries(CSV_REPORTS).map(([kind, label]) =>
            <a key={kind} className="btn sm" href={`/api/admin/reports/export.csv?kind=${kind}&${range}`}>{label} (CSV)</a>)}</div>}
        </div>
        {rangeErr && <Alert kind="error">{rangeErr}</Alert>}
        {sum.data && !rangeErr && <div className="kpis">{[['Bruto', money(sum.data.gross_cents)], ['Reembolsos', money(sum.data.refunds_cents)], ['Líquido', money(sum.data.net_cents)], ['Contestações', sum.data.chargebacks],
          ['Minutos jogados', sum.data.minutes_played], ['Sessões', sum.data.sessions], ['Ausências', sum.data.no_shows]].map(([l, v]) => <div key={String(l)} className="card kpi"><span>{l}</span><strong>{v}</strong></div>)}</div>}
        <div className="grid2"><DataTable limit={5} rows={sum.data?.revenue_by_game || null} cols={[['Jogo', (r) => String(r.title)], ['Pagamentos', (r) => String(r.payments)], ['Receita', (r) => money(Number(r.revenue_cents))]]} />
          <DataTable limit={5} rows={sum.data?.revenue_by_console || null} cols={[['Console', (r) => String(r.name)], ['Minutos vendidos', (r) => String(r.minutes_sold)], ['Receita', (r) => money(Number(r.revenue_cents))]]} /></div>
      </section>
      <section className="card"><h2>Pagamentos</h2><DataTable rows={pays.data} error={pays.error?.message} cols={[['Data', (r) => dateTime(String(r.created_at))], ['Reserva', (r) => String(r.reservation_code)], ['Usuário', (r) => String(r.username)],
        ['Provedor', (r) => String(r.provider)], ['Valor', (r) => money(Number(r.amount_cents))], ['Status', (r) => <StatusPill status={String(r.status)} map={PAYMENT_STATUS} />],
        ['', (r) => <div className="row">{r.status === 'approved' && <button className="btn sm" onClick={async () => {
          const max = Number(r.amount_cents) / 100;
          const v = await ask({ title: `Reembolsar ${String(r.reservation_code)}?`, label: 'Valor do reembolso (R$)', inputMode: 'decimal', minLength: 1,
            defaultValue: max.toFixed(2).replace('.', ','), confirm: 'Continuar', message: `Pago: ${money(Number(r.amount_cents))}. Para reembolso parcial, informe um valor menor.`,
            validate: (x) => { const n = Number(x.replace(',', '.')); return !Number.isFinite(n) || n <= 0 ? 'Informe um valor maior que zero.' : n > max ? `O máximo é ${money(Number(r.amount_cents))}.` : null; } });
          if (v === null) return;
          const reason = await ask({ title: 'Motivo do reembolso', label: 'Motivo (registrado na auditoria)', danger: true, confirm: `Reembolsar R$ ${v}` });
          if (reason) run(async () => { await post(`/admin/payments/${r.id}/refund`, { amount_cents: Math.round(Number(v.replace(',', '.')) * 100), reason }); pays.reload(); refunds.reload(); }, 'Reembolso processado.');
        }}>Reembolsar</button>}
          {r.provider === 'mercadopago' && <button className="btn sm" onClick={() => run(async () => { await post(`/admin/payments/${r.id}/reconcile`); pays.reload(); }, 'Conciliado.')}>Conciliar</button>}</div>]]} /></section>
      <section className="card"><h2>Reembolsos</h2><DataTable rows={refunds.data} error={refunds.error?.message} cols={[['Data', (r) => dateTime(String(r.created_at))], ['Reserva', (r) => String(r.reservation_code)], ['Valor', (r) => money(Number(r.amount_cents))], ['Motivo', (r) => String(r.reason)], ['Status', (r) => String(r.status)]]} /></section>
      <section className="card"><h2>Webhooks recebidos</h2><DataTable rows={hooks.data} error={hooks.error?.message} cols={[['Recebido', (r) => dateTime(String(r.received_at))], ['Provedor', (r) => String(r.provider)], ['Recurso', (r) => String(r.resource_id)],
        ['Assinatura', (r) => (r.signature_valid ? 'válida' : 'inválida')], ['Processamento', (r) => String(r.processing_status)], ['Erro', (r) => String(r.error || '')]]} /></section>
      {askDialog}
    </div>
  );
}
