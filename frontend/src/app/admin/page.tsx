'use client';
import { CollapsibleCard } from '@/components/admin/CollapsibleCard';
import { ErrorBox, PageHeader } from '@/components/ui';
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

export default function Overview() {
  const { data, error, reload } = useApi<O>('/admin/overview', 15000);
  return (
    <div className="stack">
      <PageHeader title="Visão geral" subtitle="Indicadores calculados a partir do banco de dados." />
      <ErrorBox error={error} onRetry={reload} />
      <div className="kpis">{K.map(([k, l, m]) => <div key={k} className="card kpi"><span>{l}</span><strong>{data ? (m ? money(data.kpis[k]) : data.kpis[k]) : '…'}</strong></div>)}</div>
      <div className="grid2">
        <CollapsibleCard title="Utilização por console (mês, minutos)" className="card"><DataTable rows={data?.utilization_month || null} cols={[['Console', (r) => r.name], ['Minutos', (r) => r.minutes]]} /></CollapsibleCard>
        <CollapsibleCard title="Jogos (mês)" className="card"><DataTable rows={data?.top_games_month || null} cols={[['Jogo', (r) => r.title], ['Reservas', (r) => r.reservations], ['Receita', (r) => money(r.revenue_cents)]]} /></CollapsibleCard>
      </div>
      <CollapsibleCard title="Alertas e incidentes abertos" className="card"><DataTable rows={data?.alerts || null} empty="Nenhum alerta." cols={[['Tipo', (r) => r.kind], ['Descrição', (r) => r.description], ['Desde', (r) => dateTime(r.started_at)]]} /></CollapsibleCard>
    </div>
  );
}
