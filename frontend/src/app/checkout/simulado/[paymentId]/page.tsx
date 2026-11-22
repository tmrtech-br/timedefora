'use client';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Alert, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { money, PAYMENT_STATUS } from '@/lib/format';

type Pay = { id: string; status: string; method: string; amount_cents: number; reservation_id: string; code: string; title: string; simulated: boolean };

function Sim() {
  const { paymentId } = useParams<{ paymentId: string }>();
  const router = useRouter();
  const { data, error, reload } = useApi<Pay>(`/payments/${paymentId}`);
  const [err, setErr] = useState('');
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Skeleton h={200} />;
  async function notify(outcome: 'approved' | 'rejected') {
    try { await post(`/payments/simulated/${paymentId}/notify`, { outcome }); router.push(`/checkout/retorno?reserva=${data!.reservation_id}`); }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Erro'); reload(); }
  }
  return (
    <div className="stack" style={{ maxWidth: 620 }}>
      <PageHeader title="Pagamento SIMULADO" subtitle="Ambiente de desenvolvimento — nenhuma cobrança real." />
      <Alert kind="warn">Esta tela substitui o Mercado Pago apenas em desenvolvimento. O resultado é enviado ao backend pelo mesmo fluxo de webhook (registro idempotente e máquina de estados).</Alert>
      <div className="card"><dl className="kv"><dt>Reserva</dt><dd>{data.code} · {data.title}</dd><dt>Valor</dt><dd>{money(data.amount_cents)}</dd>
        <dt>Meio</dt><dd>{data.method === 'pix' ? 'Pix' : 'Cartão'}</dd><dt>Status</dt><dd>{PAYMENT_STATUS[data.status]}</dd></dl></div>
      {err && <Alert kind="error">{err}</Alert>}
      <div className="row"><button className="btn primary" onClick={() => notify('approved')} disabled={data.status === 'approved'}>Simular pagamento aprovado</button>
        <button className="btn danger" onClick={() => notify('rejected')} disabled={data.status === 'approved'}>Simular recusa</button></div>
    </div>
  );
}
export default function Page() { return <RequireAuth><Sim /></RequireAuth>; }
