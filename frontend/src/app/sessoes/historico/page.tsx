'use client';
import Link from 'next/link';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { SESSION_STATUS, dateTime, duration, time } from '@/lib/format';

type HistoryEntry = {
  id: string;
  status: string;
  title: string;
  code: string;
  contract_starts_at: string;
  contract_ends_at: string;
  first_connected_at: string | null;
  end_reason: string | null;
  seconds_used: number;
};

const END_REASON: Record<string, string> = {
  time_up: 'tempo encerrado', user_ended: 'encerrada por você', admin: 'encerrada pela operação', failure: 'falha', no_show: 'ausência',
};

function Historico() {
  const { data, error, reload } = useApi<HistoryEntry[]>('/me/sessions-history');
  return (
    <>
      <PageHeader title="Histórico de sessões" subtitle="Consulte o tempo contratado e utilizado nas suas sessões.">
        <Link className="btn" href="/sessoes">Voltar para minhas sessões</Link>
      </PageHeader>
      <ErrorBox error={error} onRetry={reload} />
      {data?.length ? (
        <div className="table-wrap card max10">
          <table className="table">
            <thead><tr><th>Jogo</th><th>Contratado</th><th>Primeira conexão</th><th>Tempo usado</th><th>Encerramento</th></tr></thead>
            <tbody>
              {data.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.title}<div className="small dim">{entry.code}</div></td>
                  <td>{dateTime(entry.contract_starts_at)} – {time(entry.contract_ends_at)}</td>
                  <td>{dateTime(entry.first_connected_at)}</td>
                  <td>{duration(entry.seconds_used)}</td>
                  <td>{entry.end_reason ? END_REASON[entry.end_reason] || entry.end_reason : SESSION_STATUS[entry.status] || entry.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : !error && (data ? <Empty>Nenhuma sessão jogada.</Empty> : <Skeleton h={100} />)}
    </>
  );
}

export default function Page() {
  return <RequireAuth><Historico /></RequireAuth>;
}
