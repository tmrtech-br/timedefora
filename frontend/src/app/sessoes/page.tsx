'use client';
import Link from 'next/link';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { ApiError, post } from '@/lib/api';
import { toast } from '@/components/Toaster';
import { RESERVATION_STATUS, SESSION_STATUS, dateTime, duration, money, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

type Hist = { id: string; status: string; title: string; code: string; minutes: number; contract_starts_at: string; contract_ends_at: string;
  first_connected_at: string | null; ended_at: string | null; end_reason: string | null; seconds_used: number; reservation_id: string };
const END: Record<string, string> = { time_up: 'tempo encerrado', user_ended: 'encerrada por você', admin: 'encerrada pela operação', failure: 'falha', no_show: 'ausência' };

function Sessoes() {
  const res = useApi<Reservation[]>('/me/reservations', 10000);
  const hist = useApi<Hist[]>('/me/sessions-history');
  return (
    <>
      <PageHeader title="Minhas sessões" subtitle="Reservas, sessões em andamento e histórico." />
      <ErrorBox error={res.error} onRetry={res.reload} />
      <h2>Reservas</h2>
      {!res.data ? <Skeleton h={160} /> : !res.data.length ? <Empty>Nenhuma reserva ainda. <Link className="link-purple" href="/jogos">Ver catálogo</Link></Empty> : (
        <div className="table-wrap card max10"><table className="table"><thead><tr><th>Reserva</th><th>Jogo</th><th>Período</th><th>Valor</th><th>Status</th><th /></tr></thead>
          <tbody>{res.data.map((r) => (
            <tr key={r.id}><td>{r.code}</td><td>{r.game.title}<div className="small dim">{r.console_name}</div></td>
              <td>{dateTime(r.starts_at)} – {time(r.ends_at)}<div className="small dim">{r.mode === 'queue' ? 'início estimado' : 'horário fixo'}</div></td>
              <td>{money(r.total_cents)}</td><td><StatusPill status={r.status} map={RESERVATION_STATUS} /></td>
              <td>{r.status === 'pending_payment' ? <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                  <Link className="btn sm primary" href={`/checkout/${r.id}`}>Pagar</Link>
                  <button className="btn sm" title="Libera o horário para outros jogadores" onClick={async () => {
                    try { await post(`/reservations/${r.id}/cancel`, { reason: 'Desistiu antes de pagar' }); toast('ok', 'Reserva provisória cancelada. O horário foi liberado.'); res.reload(); }
                    catch (e) { toast('error', e instanceof ApiError ? e.message : 'Não foi possível cancelar.'); }
                  }}>Desistir</button></div>
                : ['confirmed', 'active'].includes(r.status) ? <Link className="btn sm primary" href={`/sessoes/${r.id}`}>Sala de espera</Link>
                : <Link className="btn sm" href={`/sessoes/${r.id}`}>Detalhes</Link>}</td></tr>
          ))}</tbody></table></div>
      )}
      <h2 style={{ marginTop: 24 }}>Histórico de sessões</h2>
      {!hist.data ? <Skeleton h={100} /> : !hist.data.length ? <Empty>Nenhuma sessão jogada.</Empty> : (
        <div className="table-wrap card max10"><table className="table"><thead><tr><th>Jogo</th><th>Contratado</th><th>Primeira conexão</th><th>Tempo usado</th><th>Encerramento</th></tr></thead>
          <tbody>{hist.data.map((h) => (
            <tr key={h.id}><td>{h.title}<div className="small dim">{h.code}</div></td><td>{dateTime(h.contract_starts_at)} – {time(h.contract_ends_at)}</td>
              <td>{dateTime(h.first_connected_at)}</td><td>{duration(h.seconds_used)}</td><td>{h.end_reason ? END[h.end_reason] || h.end_reason : SESSION_STATUS[h.status] || h.status}</td></tr>
          ))}</tbody></table></div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Sessoes /></RequireAuth>; }
