'use client';
import Link from 'next/link';
import { useState } from 'react';
import QueueList from '@/components/QueueList';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, Modal, PageHeader, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { dateTime, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';
import styles from './queues.module.css';

type QueuedReservation = Reservation & { console_id: string; queue: NonNullable<Reservation['queue']> };

function Filas() {
  const { data, error, reload } = useApi<QueuedReservation[]>('/me/queues', 5000);
  const [selectedConsole, setSelectedConsole] = useState<string | null>(null);
  const selected = data?.find((reservation) => reservation.console_id === selectedConsole);
  const hasMore = (data?.length ?? 0) > 5;

  return (
    <>
      <PageHeader title="Minhas filas" subtitle="Acompanhe cada reserva pelo código, horário e posição na fila." />
      <ErrorBox error={error} onRetry={reload} />
      {!data ? <Skeleton h={200} /> : !data.length ? (
        <Empty>Você não está em nenhuma fila. <Link className="link-purple" href="/jogos">Escolha um jogo</Link> ou <Link className="link-purple" href="/sessoes">consulte suas reservas</Link>.</Empty>
      ) : (
        <div className={styles.scroll} data-scrollable={hasMore} role="region" aria-label="Minhas reservas na fila" tabIndex={hasMore ? 0 : undefined}>
          <ul className={styles.list}>
            {data.map((reservation) => (
              <li key={reservation.id} className={`card ${styles.reservation}`}>
                <div className={styles.summary}>
                  <div className={styles.title}>
                    <h2 title={reservation.game.title}>{reservation.game.title}</h2>
                    <span className="pill purple">{reservation.queue.status === 'playing' ? 'Jogando' : `Posição: ${reservation.queue.position}º`}</span>
                  </div>
                  <div className={`muted ${styles.console}`} title={reservation.console_name}>{reservation.console_name} · {reservation.code}</div>
                  <div className={`small muted ${styles.schedule}`}>{reservation.mode === 'queue' ? 'Estimativa' : 'Horário reservado'} · {dateTime(reservation.starts_at)}–{time(reservation.ends_at)} · {reservation.minutes} min</div>
                </div>
                <div className={styles.actions}>
                  <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setSelectedConsole(reservation.console_id)}>Ver fila do console</button>
                  <Link className="btn primary" href={`/sessoes/${reservation.id}`}>Sala de espera</Link>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {selectedConsole && <Modal title={selected ? `Fila do console · ${selected.console_name}` : 'Fila do console'} onClose={() => setSelectedConsole(null)}>
        <QueueList items={selected?.public_queue || []} maxVisible={5} />
      </Modal>}
    </>
  );
}
export default function Page() { return <RequireAuth><Filas /></RequireAuth>; }
