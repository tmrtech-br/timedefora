'use client';
import { useState } from 'react';
import { exportExcel } from '@/components/admin/exportReport';
import { ErrorBox, Field, PageHeader } from '@/components/ui';
import { DataTable } from '@/components/admin/common';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';

type O = { kpis: Record<string, number>; utilization_month: { name: string; minutes: number }[]; top_games_month: { title: string; reservations: number; revenue_cents: number }[];
  alerts: { id: string; kind: string; description: string; started_at: string }[] };
const K: [string, string, boolean?][] = [['users_total', 'Usuários'], ['users_online', 'Online (15 min)'], ['consoles_total', 'Consoles'], ['consoles_available', 'Disponíveis'],
  ['consoles_busy', 'Ocupados'], ['consoles_maintenance', 'Manutenção'], ['consoles_offline', 'Offline/degradados'], ['sessions_active', 'Sessões ativas'],
  ['queue_waiting', 'Aguardando na fila'], ['revenue_today', 'Receita hoje', true], ['revenue_month', 'Receita no mês', true], ['minutes_sold_month', 'Minutos vendidos (mês)'],
  ['payments_pending', 'Pagamentos pendentes'], ['incidents_open', 'Incidentes abertos'], ['deliveries_failed', 'E-mails com falha'],
  ['reservations_needing_resolution', 'Reservas em resolução'], ['cancellation_requests_open', 'Cancelamentos a analisar']];

const INCIDENT: Record<string, string> = {
  console_failure: 'Falha no console', stream_failure: 'Falha na transmissão', agent_offline: 'Agente desconectado',
  platform_delay: 'Atraso na plataforma', other: 'Outro incidente',
};
const incidentName = (kind: string) => INCIDENT[kind] ?? 'Incidente';

function MetricBar({ value, max }: { value: number; max: number }) {
  return <div className="admin-metric"><b>{value.toLocaleString('pt-BR')}</b><meter min={0} max={Math.max(1, max)} value={value} aria-label="Valor em relação ao maior resultado exibido" /></div>;
}

export default function Overview() {
  const [month, setMonth] = useState('');
  const { data, error, reload, loading } = useApi<O>(month ? `/admin/overview?month=${month}` : '/admin/overview', 15000);
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const query = search.trim().toLocaleLowerCase('pt-BR');
  const consoles = data?.utilization_month.filter((r) => r.name.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const games = data?.top_games_month.filter((r) => r.title.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const alerts = data?.alerts.filter((r) => (!kind || r.kind === kind) && r.description.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const maxMinutes = Math.max(1, ...(consoles ?? []).map((r) => r.minutes));
  const maxReservations = Math.max(1, ...(games ?? []).map((r) => r.reservations));
  return (
    <div className="stack">
      <PageHeader title="Visão geral" subtitle="Indicadores da operação, reservas e receita.">
        <button className="btn" disabled={!data || loading || Boolean(error)} onClick={() => exportExcel('visao-geral', [
          { title: 'Indicadores', headers: ['Indicador', 'Valor'], rows: K.map(([key, label, currency]) => [label, currency ? data!.kpis[key] / 100 : data!.kpis[key]]) },
          { title: 'Consoles', headers: ['Console', 'Minutos'], rows: (consoles ?? []).map((r) => [r.name, r.minutes]) },
          { title: 'Jogos', headers: ['Jogo', 'Reservas', 'Receita em reais'], rows: (games ?? []).map((r) => [r.title, r.reservations, r.revenue_cents / 100]) },
          { title: 'Incidentes', headers: ['Tipo', 'Descrição', 'Desde'], rows: (alerts ?? []).map((r) => [incidentName(r.kind), r.description, dateTime(r.started_at)]) },
        ])}>Exportar dados</button>
      </PageHeader>
      <ErrorBox error={error} onRetry={reload} />
      <div className="kpis">{K.map(([k, l, m]) => <div key={k} className="card kpi"><span>{l}</span><strong>{data ? (m ? money(data.kpis[k]) : data.kpis[k]) : '…'}</strong></div>)}</div>
      <div className="card grid3">
        <Field label="Mês dos relatórios"><input type="month" value={month} max={new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date()).slice(0, 7)} onChange={(e) => setMonth(e.target.value)} /></Field>
        <Field label="Buscar nos relatórios"><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} /></Field>
        <Field label="Tipo de incidente"><select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Todos</option>{Object.entries(INCIDENT).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></Field>
      </div>
      <div className="grid2">
        <section className="card"><h2>Utilização por console (mês, minutos)</h2><DataTable rows={consoles} limit={5} cols={[['Console', (r) => r.name], ['Minutos', (r) => <MetricBar value={r.minutes} max={maxMinutes} />]]} /></section>
        <section className="card"><h2>Jogos (mês)</h2><DataTable rows={games} limit={5} cols={[['Jogo', (r) => r.title], ['Reservas', (r) => <MetricBar value={r.reservations} max={maxReservations} />], ['Receita', (r) => money(r.revenue_cents)]]} /></section>
      </div>
      <section className="card"><h2>Alertas e incidentes abertos</h2><DataTable rows={alerts} limit={5} empty="Nenhum alerta." cols={[['Tipo', (r) => incidentName(r.kind)], ['Descrição', (r) => r.description], ['Desde', (r) => dateTime(r.started_at)]]} /></section>
    </div>
  );
}
