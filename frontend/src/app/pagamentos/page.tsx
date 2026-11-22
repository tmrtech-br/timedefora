'use client';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { dateTime, money, PAYMENT_STATUS } from '@/lib/format';

type P = { id: string; status: string; method: string; provider: string; amount_cents: number; created_at: string; reservation_code: string; game_title: string; refunded_cents: number };

function Pagamentos() {
  const { data, error, reload } = useApi<P[]>('/me/payments');
  return (
    <>
      <PageHeader title="Pagamentos" subtitle="Histórico de compras e reembolsos." />
      <ErrorBox error={error} onRetry={reload} />
      {!data ? <Skeleton h={160} /> : !data.length ? <Empty>Nenhum pagamento.</Empty> : (
        <div className="card table-wrap"><table className="table"><thead><tr><th>Data</th><th>Reserva</th><th>Meio</th><th>Valor</th><th>Reembolsado</th><th>Status</th></tr></thead>
          <tbody>{data.map((p) => <tr key={p.id}><td>{dateTime(p.created_at)}</td><td>{p.reservation_code} · {p.game_title}</td>
            <td>{p.method === 'pix' ? 'Pix' : p.method === 'card' ? 'Cartão' : '—'}{p.provider === 'simulated' && <span className="pill amber" style={{ marginLeft: 6 }}>simulado</span>}</td>
            <td>{money(p.amount_cents)}</td><td>{p.refunded_cents ? money(p.refunded_cents) : '—'}</td><td><StatusPill status={p.status} map={PAYMENT_STATUS} /></td></tr>)}</tbody></table></div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Pagamentos /></RequireAuth>; }
