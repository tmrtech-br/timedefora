'use client';
import { useEffect, useState } from 'react';
import DateFilter from '@/components/DateFilter';
import styles from '../pagamentos/payments.module.css';
import Link from 'next/link';
import RequireAuth from '@/components/RequireAuth';
import { Alert, Empty, ErrorBox, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { ApiError, post } from '@/lib/api';
import { toast } from '@/components/Toaster';
import { RESERVATION_STATUS, dateTime, money, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

const initialFilters = { search: '', status: '', mode: '', from: '', to: '' };
const localDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' });

/** Por que a reserva não está mais disponível (aberta a partir de um e-mail/notificação antigo). */
function endedReason(r: Reservation): string {
  switch (r.status) {
    case 'completed': return 'já foi concluída: o tempo contratado terminou.';
    case 'no_show': return 'foi encerrada por ausência: o console ficou pronto, mas a sessão não foi iniciada dentro do período.';
    case 'cancelled': return `foi cancelada${r.cancel_reason ? ` (${r.cancel_reason})` : ''}.`;
    case 'expired': return 'expirou porque o pagamento não foi concluído dentro do prazo.';
    case 'refunded': return 'foi reembolsada.';
    case 'needs_resolution': return `está em resolução pela equipe. ${r.resolution_notes || ''}`.trim();
    default: return `está ${(RESERVATION_STATUS[r.status] || r.status).toLowerCase()}.`;
  }
}

function Sessoes() {
  const res = useApi<Reservation[]>('/me/reservations', 10000);
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [endedId, setEndedId] = useState<string | null>(null);
  useEffect(() => { try { setEndedId(new URLSearchParams(window.location.search).get('encerrada')); } catch { /* sem URL */ } }, []);
  const ended = endedId ? res.data?.find((r) => r.id === endedId) : undefined;
  const rows = res.data?.filter((r) => {
    const date = localDate.format(new Date(r.starts_at));
    return (!filters.search || [r.code, r.game.title, r.console_name].some((value) => value?.toLowerCase().includes(filters.search)))
      && (!filters.status || r.status === filters.status) && (!filters.mode || r.mode === filters.mode)
      && (!filters.from || date >= filters.from) && (!filters.to || date <= filters.to);
  });
  return (
    <>
      <PageHeader title="Minhas sessões" subtitle="Acompanhe suas reservas e sessões em andamento.">
        <Link className="btn" href="/sessoes/historico">Histórico de sessões</Link>
      </PageHeader>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {ended && <Alert kind={ended.status === 'needs_resolution' ? 'warn' : 'info'}>
        A reserva <b>{ended.code}</b> ({ended.game.title}) {endedReason(ended)}</Alert>}
      <h2>Reservas</h2>
      <form className={styles.filters} onSubmit={(e) => { e.preventDefault(); setFilters({ ...draft, search: draft.search.trim().toLowerCase() }); }}>
        <label className="field">Buscar
          <input type="search" maxLength={50} placeholder="Código, jogo ou console" value={draft.search} onChange={(e) => setDraft({ ...draft, search: e.target.value })} />
        </label>
        <label className="field">Status
          <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
          <option value="">Todos</option>{Object.entries(RESERVATION_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="field">Tipo de reserva
          <select value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value })}>
          <option value="">Todos</option><option value="queue">Fila</option><option value="scheduled">Horário fixo</option>
          </select>
        </label>
        <DateFilter label="Data inicial" max={draft.to} value={draft.from} onChange={(from) => setDraft({ ...draft, from })} />
        <DateFilter label="Data final" min={draft.from} value={draft.to} onChange={(to) => setDraft({ ...draft, to })} />
        <div className="row">
          <button className="btn primary">Filtrar</button>
          <button type="button" className="btn" onClick={() => { setDraft(initialFilters); setFilters(initialFilters); }}>Limpar filtros</button>
        </div>
      </form>
      {!rows ? <Skeleton h={160} /> : !rows.length ? <Empty>Nenhuma reserva encontrada. <Link className="link-purple" href="/jogos">Ver catálogo</Link></Empty> : (
        <div className="table-wrap card max10"><table className="table"><thead><tr><th>Reserva</th><th>Jogo</th><th>Período</th><th>Valor</th><th>Status</th><th /></tr></thead>
          <tbody>{rows.map((r) => (
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
    </>
  );
}
export default function Page() { return <RequireAuth><Sessoes /></RequireAuth>; }
