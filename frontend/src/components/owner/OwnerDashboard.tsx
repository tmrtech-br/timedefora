'use client';
import { useMemo, useState } from 'react';
import { FileDown } from 'lucide-react';
import { Alert } from '@/components/ui';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { downloadReportPdf } from '@/lib/reportPdf';
import { DataTable } from '@/components/admin/common';
import DateFilter from '@/components/DateFilter';
import { BarChart } from './shared';

type Row = { code: string; status: string; minutes: number; total_cents: number; starts_at: string; game: string; console: string; day: string;
  seconds_used: number | null; end_reason: string | null; owner_cents: number | null; settlement_status: string | null; payout_status: string | null };
type Report = { date_from: string; date_to: string; consoles: { id: string; name: string }[]; rows: Row[] };
const STATUS: Record<string, string> = { confirmed: 'Na fila', active: 'Jogando', completed: 'Concluída', no_show: 'Ausência', cancelled: 'Cancelada',
  needs_resolution: 'Em resolução', refunded: 'Reembolsada' };
const day = (iso: string) => iso.split('-').reverse().slice(0, 2).join('/');

/** Dashboard do proprietário: indicadores, gráficos e reservas do período, com filtros e exportação em PDF. */
export default function OwnerDashboard() {
  const [filters, setFilters] = useState({ date_from: '', date_to: '', console_id: '' });
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
  const rep = useApi<Report>(`/owner/report${qs ? `?${qs}` : ''}`, 60000);
  const rows = rep.data?.rows ?? [];
  const k = useMemo(() => {
    const done = rows.filter((r) => r.status === 'completed');
    const earned = rows.reduce((s, r) => s + (['eligible', 'paid'].includes(r.settlement_status ?? '') ? r.owner_cents ?? 0 : 0), 0);
    const received = rows.reduce((s, r) => s + (r.settlement_status === 'paid' ? r.owner_cents ?? 0 : 0), 0);
    return {
      reservas: rows.length, sessoes: done.length,
      minutos: Math.round(rows.reduce((s, r) => s + (r.seconds_used ?? 0), 0) / 60),
      faturamento: rows.filter((r) => !['cancelled', 'refunded'].includes(r.status)).reduce((s, r) => s + r.total_cents, 0),
      ganho: earned, recebido: received, aReceber: earned - received,
      ocupacaoMedia: done.length ? Math.round(done.reduce((s, r) => s + Math.min(1, (r.seconds_used ?? 0) / (r.minutes * 60)), 0) / done.length * 100) : 0,
    };
  }, [rows]);
  const byDay = useMemo(() => {
    const m = new Map<string, { n: number; c: number }>();
    rows.forEach((r) => { const x = m.get(r.day) ?? { n: 0, c: 0 }; x.n += 1; x.c += r.owner_cents ?? 0; m.set(r.day, x); });
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([d, x]) => ({ day: d, ...x }));
  }, [rows]);
  const byGame = useMemo(() => {
    const m = new Map<string, { min: number; c: number }>();
    rows.forEach((r) => { const x = m.get(r.game) ?? { min: 0, c: 0 }; x.min += Math.round((r.seconds_used ?? 0) / 60); x.c += r.owner_cents ?? 0; m.set(r.game, x); });
    return [...m.entries()].sort((a, b) => b[1].c - a[1].c);
  }, [rows]);
  const byStatus = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r) => m.set(STATUS[r.status] ?? r.status, (m.get(STATUS[r.status] ?? r.status) ?? 0) + 1));
    return [...m.entries()].map(([label, value]) => ({ label, value }));
  }, [rows]);

  function exportPdf() {
    if (!rep.data) return;
    const period = `${day(rep.data.date_from)} a ${day(rep.data.date_to)}${filters.console_id ? ` · ${rep.data.consoles.find((c) => c.id === filters.console_id)?.name ?? ''}` : ''}`;
    downloadReportPdf('Relatório do proprietário', `Período: ${period}`, [
      { title: 'Resumo', headers: ['Indicador', 'Valor'], rows: [
        ['Reservas', k.reservas], ['Sessões concluídas', k.sessoes], ['Minutos jogados', k.minutos],
        ['Faturamento das reservas', money(k.faturamento)], ['Meu ganho', money(k.ganho)], ['Recebido', money(k.recebido)],
        ['A receber', money(k.aReceber)], ['Aproveitamento médio do tempo', `${k.ocupacaoMedia}%`]] },
      { title: 'Por dia', headers: ['Dia', 'Reservas', 'Meu ganho'], rows: byDay.map((d) => [day(d.day), d.n, money(d.c)]) },
      { title: 'Por jogo', headers: ['Jogo', 'Minutos', 'Meu ganho'], rows: byGame.map(([g, x]) => [g, x.min, money(x.c)]) },
      { title: 'Reservas', headers: ['Reserva · jogo · console', 'Início', 'Situação · valor'],
        rows: rows.map((r) => [`${r.code} · ${r.game} · ${r.console}`, dateTime(r.starts_at), `${STATUS[r.status] ?? r.status} · ${money(r.total_cents)}`]) },
    ], `relatorio-proprietario-${rep.data.date_from}-${rep.data.date_to}.pdf`);
  }

  return <section className="stack" id="dashboard">
    <div className="card owner-filters">
      <DateFilter label="De" value={filters.date_from} max={filters.date_to || undefined} onChange={(v) => setFilters({ ...filters, date_from: v })} />
      <DateFilter label="Até" value={filters.date_to} min={filters.date_from || undefined} onChange={(v) => setFilters({ ...filters, date_to: v })} />
      <label className="field">Console<select value={filters.console_id} onChange={(e) => setFilters({ ...filters, console_id: e.target.value })}>
        <option value="">Todos</option>{rep.data?.consoles.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <button className="btn" disabled={!rep.data} onClick={exportPdf}><FileDown size={16} aria-hidden />Exportar PDF</button>
    </div>
    {rep.error && <Alert kind="error">{rep.error.message}</Alert>}
    {rep.data && <p className="small muted" style={{ margin: 0 }}>Período: {day(rep.data.date_from)} a {day(rep.data.date_to)} (padrão: últimos 30 dias)</p>}
    <div className="kpis owner-kpis">
      <div className="card kpi"><span>Reservas</span><strong>{k.reservas}</strong></div>
      <div className="card kpi"><span>Sessões concluídas</span><strong>{k.sessoes}</strong></div>
      <div className="card kpi"><span>Minutos jogados</span><strong>{k.minutos}</strong></div>
      <div className="card kpi"><span>Faturamento</span><strong>{money(k.faturamento)}</strong></div>
      <div className="card kpi"><span>Meu ganho</span><strong>{money(k.ganho)}</strong></div>
      <div className="card kpi"><span>Recebido</span><strong>{money(k.recebido)}</strong></div>
      <div className="card kpi"><span>A receber</span><strong>{money(k.aReceber)}</strong></div>
      <div className="card kpi"><span>Aproveitamento do tempo</span><strong>{k.ocupacaoMedia}%</strong></div>
    </div>
    <div className="grid2">
      <div className="card"><BarChart title="Meu ganho por dia" data={byDay.map((d) => ({ label: day(d.day), value: d.c }))} format={money} /></div>
      <div className="card"><BarChart title="Meu ganho por jogo" data={byGame.map(([g, x]) => ({ label: g, value: x.c }))} format={money} /></div>
      <div className="card"><BarChart title="Minutos jogados por jogo" data={byGame.map(([g, x]) => ({ label: g, value: x.min }))} format={(v) => `${v} min`} /></div>
      <div className="card"><BarChart title="Reservas por situação" data={byStatus} format={(v) => String(v)} /></div>
    </div>
    <div className="card"><h3 style={{ marginTop: 0 }}>Reservas do período</h3>
      <DataTable limit={10} rows={rep.data?.rows ?? null} error={rep.error?.message} empty="Nenhuma reserva no período."
        cols={[['Reserva', (r) => r.code], ['Jogo', (r) => r.game], ['Console', (r) => r.console], ['Início', (r) => dateTime(r.starts_at)],
          ['Tempo', (r) => `${r.minutes} min`], ['Situação', (r) => STATUS[r.status] ?? r.status], ['Valor', (r) => money(r.total_cents)],
          ['Meu ganho', (r) => (r.owner_cents != null ? money(r.owner_cents) : '—')]]} /></div>
  </section>;
}
