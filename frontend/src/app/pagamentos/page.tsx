'use client';
import { useState, type FormEvent } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { dateTime, money, PAYMENT_STATUS } from '@/lib/format';
import styles from './payments.module.css';

type Payment = { id: string; status: string; method: string | null; provider: string; amount_cents: number; created_at: string; reservation_code: string; game_title: string; refunded_cents: number };
const METHODS: Record<string, string> = { pix: 'Pix', card: 'Cartão', unknown: 'Não informado' };
const INITIAL = { q: '', method: '', status: '', date_from: '', date_to: '' };

function Pagamentos() {
  const [filters, setFilters] = useState(INITIAL);
  const [query, setQuery] = useState('');
  const { data, error, loading, reload } = useApi<Payment[]>(query ? `/me/payments?${query}` : '/me/payments');

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value.trim()) params.set(key, value.trim());
    }
    setQuery(params.toString());
  }

  return (
    <>
      <PageHeader title="Pagamentos" subtitle="Histórico de compras e reembolsos." />
      <form className={styles.filters} onSubmit={apply}>
        <label className="field">Reserva ou jogo
          <input type="search" maxLength={120} placeholder="Código da reserva ou nome do jogo" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
        </label>
        <label className="field">Meio de pagamento
          <select value={filters.method} onChange={(e) => setFilters({ ...filters, method: e.target.value })}>
            <option value="">Todos</option>
            {Object.entries(METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="field">Status
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">Todos</option>
            {Object.entries(PAYMENT_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="field">Data inicial
          <input type="date" max={filters.date_to || undefined} value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} />
        </label>
        <label className="field">Data final
          <input type="date" min={filters.date_from || undefined} value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} />
        </label>
        <div className="row">
          <button className="btn primary" type="submit">Filtrar</button>
          <button className="btn" type="button" disabled={!query && !Object.values(filters).some(Boolean)} onClick={() => { setFilters(INITIAL); setQuery(''); }}>Limpar filtros</button>
        </div>
      </form>

      <ErrorBox error={error} onRetry={reload} />
      {loading ? <Skeleton h={160} /> : !error && (data?.length ? (
        <div key={query} className={`card table-wrap max10 ${styles.scroll}`} tabIndex={0} role="region" aria-label="Tabela de pagamentos">
          <table className="table">
            <thead><tr><th>Data</th><th>Reserva</th><th>Meio</th><th>Valor</th><th>Reembolsado</th><th>Status</th></tr></thead>
            <tbody>{data.map((payment) => (
              <tr key={payment.id}>
                <td>{dateTime(payment.created_at)}</td>
                <td>{payment.reservation_code} · {payment.game_title}</td>
                <td><div className={styles.method}>
                  <span>{METHODS[payment.method ?? 'unknown'] || METHODS.unknown}</span>
                  {payment.provider === 'simulated' && <span className="pill amber">simulado</span>}
                </div></td>
                <td>{money(payment.amount_cents)}</td>
                <td>{payment.refunded_cents ? money(payment.refunded_cents) : '—'}</td>
                <td><StatusPill status={payment.status} map={PAYMENT_STATUS} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <Empty>{query ? 'Nenhum pagamento encontrado para esses filtros.' : 'Nenhum pagamento.'}</Empty>)}
    </>
  );
}

export default function Page() {
  return <RequireAuth><Pagamentos /></RequireAuth>;
}
