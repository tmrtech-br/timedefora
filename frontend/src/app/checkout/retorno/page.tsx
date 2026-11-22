'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Alert, Loading, PageHeader } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { dateTime, RESERVATION_STATUS } from '@/lib/format';
import type { Reservation } from '@/lib/types';

function Retorno() {
  const id = useSearchParams().get('reserva');
  const { data: r } = useApi<Reservation>(id ? `/reservations/${id}` : null, 3000);   // aguarda confirmação do servidor
  if (!id) return <Alert kind="error">Reserva não informada.</Alert>;
  if (!r) return <Loading label="Consultando o status do pagamento no servidor…" />;
  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <PageHeader title="Retorno do pagamento" />
      {r.status === 'confirmed' || r.status === 'active' ? (
        <Alert kind="ok">Pagamento confirmado! {r.game.title} — {r.mode === 'queue' ? 'início estimado' : 'início'} {dateTime(r.starts_at)}. Avisaremos 5 minutos antes.</Alert>
      ) : r.status === 'pending_payment' ? (
        <Alert kind="info">Aguardando a confirmação do provedor de pagamento. Esta página atualiza sozinha.</Alert>
      ) : <Alert kind="warn">Status: {RESERVATION_STATUS[r.status]}. {r.resolution_notes}</Alert>}
      <div className="row"><Link className="btn primary" href={`/sessoes/${r.id}`}>Sala de espera</Link><Link className="btn" href="/minhas-filas">Minhas filas</Link></div>
    </div>
  );
}
export default function Page() { return <RequireAuth><Suspense><Retorno /></Suspense></RequireAuth>; }
