'use client';
import { useState } from 'react';
import { Activity, CircleAlert, Download, FileText, Wallet } from 'lucide-react';
import { toast } from '@/components/Toaster';
import { exportExcel, printReports } from '@/components/admin/exportReport';
import { Empty, ErrorBox, Field, PageHeader, Skeleton } from '@/components/ui';
import { DataTable } from '@/components/admin/common';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';

type O = { period: string; kpis: Record<string, number>; utilization_month: { name: string; minutes: number }[]; top_games_month: { title: string; reservations: number; revenue_cents: number }[];
  alerts: { id: string; kind: string; description: string; started_at: string }[] };
const K: [string, string, boolean?][] = [['users_total', 'Usuários'], ['users_online', 'Online (15 min)'], ['consoles_total', 'Consoles'], ['consoles_available', 'Disponíveis'],
  ['consoles_busy', 'Ocupados'], ['consoles_maintenance', 'Manutenção'], ['consoles_offline', 'Offline/degradados'], ['sessions_active', 'Sessões ativas'],
  ['queue_waiting', 'Aguardando na fila'], ['revenue_today', 'Receita hoje', true], ['revenue_month', 'Receita no mês', true], ['minutes_sold_month', 'Minutos vendidos (mês)'],
  ['payments_pending', 'Pagamentos pendentes'], ['incidents_open', 'Incidentes abertos'], ['deliveries_failed', 'E-mails com falha'],
  ['reservations_needing_resolution', 'Reservas em resolução'], ['cancellation_requests_open', 'Cancelamentos a analisar']];

const MONTHLY_METRICS = K.filter(([key]) => key === 'revenue_month' || key === 'minutes_sold_month');

const GROUPS = [
  { title: 'Operação', Icon: Activity, metrics: K.slice(0, 9), tone: 'purple' },
  { title: 'Receita e pagamentos', Icon: Wallet, metrics: K.slice(9, 13), tone: 'green' },
  { title: 'Acompanhamento', Icon: CircleAlert, metrics: K.slice(13), tone: 'amber' },
];

const MONTHS = Array.from({ length: 12 }, (_, month) =>
  new Intl.DateTimeFormat('pt-BR', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2000, month, 1))));
const number = new Intl.NumberFormat('pt-BR');
const currentPeriod = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Sao_Paulo' }).format(new Date()).slice(0, 7);

const INCIDENT: Record<string, string> = {
  console_failure: 'Falha no console', stream_failure: 'Falha na transmissão', agent_offline: 'Agente desconectado',
  platform_delay: 'Atraso na plataforma', other: 'Outro incidente',
};
const incidentName = (kind: string) => INCIDENT[kind] ?? 'Incidente';

function MetricBar({ value, max }: { value: number; max: number }) {
  return <div className="admin-metric"><b>{value.toLocaleString('pt-BR')}</b><meter min={0} max={Math.max(1, max)} value={value} aria-label="Valor em relação ao maior resultado exibido" /></div>;
}

export default function Overview() {
  const [period, setPeriod] = useState(currentPeriod);
  const [year, month] = period.split('-');
  const [yearDraft, setYearDraft] = useState(year);
  const [monthDraft, setMonthDraft] = useState(month);
  const [currentYear, currentMonth] = currentPeriod().split('-');
  const { data: overview, error, reload } = useApi<O>(`/admin/overview?month=${period}`, 15000);
  const data = overview?.period === period && !error ? overview : null;
  const isCurrentPeriod = period === `${currentYear}-${currentMonth}`;
  const groups = isCurrentPeriod ? GROUPS : [{ ...GROUPS[1], title: 'Indicadores do mês', metrics: MONTHLY_METRICS }];
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [kindDraft, setKindDraft] = useState('');
  const query = search.trim().toLocaleLowerCase('pt-BR');
  const consoles = data?.utilization_month.filter((r) => r.name.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const games = data?.top_games_month.filter((r) => r.title.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const alerts = data?.alerts.filter((r) => (!kind || r.kind === kind) && r.description.toLocaleLowerCase('pt-BR').includes(query)) ?? null;
  const maxMinutes = Math.max(1, ...(consoles ?? []).map((r) => r.minutes));
  const maxReservations = Math.max(1, ...(games ?? []).map((r) => r.reservations));
  const periodLabel = `${MONTHS[Number(month) - 1]} de ${year}`;
  const exportHeader = { title: 'Visão geral da operação', subtitle: `Período dos indicadores mensais: ${periodLabel} · Emitido em ${dateTime(new Date().toISOString())}` };
  const reportData = data ? [
    { title: 'Indicadores', headers: ['Indicador', 'Valor'], rows: (isCurrentPeriod ? K : MONTHLY_METRICS).map(([key, label, currency]) => [label, currency ? money(data.kpis[key]) : data.kpis[key]]) },
    { title: 'Utilização por console', headers: ['Console', 'Minutos'], rows: (consoles ?? []).map((r) => [r.name, r.minutes]) },
    { title: 'Jogos', headers: ['Jogo', 'Reservas', 'Receita'], rows: (games ?? []).map((r) => [r.title, r.reservations, money(r.revenue_cents)]) },
    { title: 'Alertas e incidentes', headers: ['Tipo', 'Descrição', 'Desde'], rows: (alerts ?? []).map((r) => [incidentName(r.kind), r.description, dateTime(r.started_at)]) },
  ] : [];
  const exportDisabled = !data;
  const noPeriodData = Boolean(data && !data.utilization_month.length && !data.top_games_month.length
    && !data.alerts.length && !MONTHLY_METRICS.some(([key]) => data.kpis[key]));

  return (
    <div className="stack">
      <PageHeader title="Visão geral" subtitle="Indicadores da operação, reservas e receita.">
        <button className="btn primary" disabled={exportDisabled} onClick={() => {
          if (!printReports(exportHeader, reportData)) toast('error', 'Permita a abertura da janela para salvar o relatório em PDF.');
        }}><FileText size={16} aria-hidden />Exportar PDF</button>
        <button className="btn" disabled={exportDisabled} onClick={() => exportExcel(`visao-geral-${period}`, reportData, exportHeader)}>
          <Download size={16} aria-hidden />Exportar XML
        </button>
      </PageHeader>
      <ErrorBox error={error} onRetry={reload} />
      <form className="card overview-filters" onSubmit={(e) => {
        e.preventDefault();
        const nextYear = String(Number(yearDraft)).padStart(4, '0');
        const nextMonth = nextYear === currentYear && monthDraft > currentMonth ? currentMonth : monthDraft;
        setMonthDraft(nextMonth);
        setPeriod(`${nextYear}-${nextMonth}`);
        setSearch(searchDraft);
        setKind(kindDraft);
      }}>
        <Field label="Mês dos relatórios"><select className="overview-month" value={monthDraft} onChange={(e) => setMonthDraft(e.target.value)}>
          {MONTHS.map((name, i) => {
            const code = String(i + 1).padStart(2, '0');
            return <option key={code} value={code} disabled={Number(yearDraft) === Number(currentYear) && code > currentMonth}>{name}</option>;
          })}
        </select></Field>
        <Field label="Ano"><input type="number" required min={1} max={currentYear} value={yearDraft} onChange={(e) => setYearDraft(e.target.value)} /></Field>
        <Field label="Buscar nos relatórios"><input type="search" value={searchDraft} onChange={(e) => setSearchDraft(e.target.value)} /></Field>
        <Field label="Tipo de incidente"><select value={kindDraft} onChange={(e) => setKindDraft(e.target.value)}>
          <option value="">Todos</option>{Object.entries(INCIDENT).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></Field>
        <div className="overview-filter-actions"><button className="btn primary" type="submit">Filtrar</button></div>
      </form>
      {!data && !error && <Skeleton h={230} />}
      {noPeriodData && <Empty>Nenhum registro em {periodLabel}.</Empty>}
      {data && groups.map(({ title, Icon, metrics, tone }) => <section key={title} className={`overview-group overview-${tone}`}>
        <h2><span className="overview-icon"><Icon size={17} aria-hidden /></span>{title}</h2>
        <dl className="overview-metrics">
          {metrics.map(([key, label, currency]) => <div key={key} className="card overview-metric">
            <dt>{label}</dt>
            <dd>{data ? (currency ? money(data.kpis[key]) : number.format(data.kpis[key])) : '…'}</dd>
          </div>)}
        </dl>
      </section>)}
      {data && <><div className="grid2">
        <section className="card"><h2>Utilização por console (mês, minutos)</h2><DataTable rows={consoles} limit={5} cols={[['Console', (r) => r.name], ['Minutos', (r) => <MetricBar value={r.minutes} max={maxMinutes} />]]} /></section>
        <section className="card"><h2>Jogos (mês)</h2><DataTable rows={games} limit={5} cols={[['Jogo', (r) => r.title], ['Reservas', (r) => <MetricBar value={r.reservations} max={maxReservations} />], ['Receita', (r) => money(r.revenue_cents)]]} /></section>
      </div>
      <section className="card"><h2>Alertas e incidentes abertos</h2><DataTable rows={alerts} limit={5} empty="Nenhum alerta." cols={[['Tipo', (r) => incidentName(r.kind)], ['Descrição', (r) => r.description], ['Desde', (r) => dateTime(r.started_at)]]} /></section></>}
    </div>
  );
}
