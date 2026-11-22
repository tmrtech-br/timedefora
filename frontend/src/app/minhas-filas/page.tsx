'use client';
import Link from 'next/link';
import QueueList from '@/components/QueueList';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { dateTime, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

function Filas() {
  const { data, error, reload } = useApi<Reservation[]>('/me/queues', 5000);
  return (
    <>
      <PageHeader title="Minhas filas" subtitle="Posições e estimativas atualizadas automaticamente pelo servidor." />
      <ErrorBox error={error} onRetry={reload} />
      {!data ? <Skeleton h={200} /> : !data.length ? <Empty>Você não está em nenhuma fila. <Link className="link-purple" href="/jogos">Escolha um jogo</Link>.</Empty> : (
        <div className="stack">
          {data.map((r) => (
            <section key={r.id} className="card">
              <div className="spread"><h2 style={{ margin: 0 }}>{r.game.title} · {r.console_name}</h2>
                <span className="pill purple">Sua posição: {r.queue?.position}º</span></div>
              <p className="muted">{r.mode === 'queue' ? 'Início estimado' : 'Horário reservado'}: {dateTime(r.starts_at)} – {time(r.ends_at)} · {r.minutes} min · reserva {r.code}</p>
              <QueueList items={r.public_queue || []} />
              <div className="row" style={{ marginTop: 10 }}><Link className="btn primary" href={`/sessoes/${r.id}`}>Sala de espera</Link></div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Filas /></RequireAuth>; }
