'use client';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, Modal, PageHeader, Skeleton } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { ApiError, del, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import styles from './notifications.module.css';

type Notification = { id: string; title: string; body: string; link: string | null; read_at: string | null; created_at: string };
const VISIBLE_COUNT = 5;

function NotificationCard({ item, onOpen }: { item: Notification; onOpen: (item: Notification) => void }) {
  return (
    <article className={`card ${styles.notification}`} data-unread={!item.read_at}>
      <div className="spread"><b>{item.title}</b><time className="small dim" dateTime={item.created_at}>{dateTime(item.created_at)}</time></div>
      <p className="muted">{item.body}</p>
      {item.link && <Link className="link-purple small" href={item.link} onClick={() => onOpen(item)}>Abrir</Link>}
    </article>
  );
}

function NotificationList({ items, onOpen }: { items: Notification[]; onOpen: (item: Notification) => void }) {
  const firstGroup = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number>();
  const hasMore = items.length > VISIBLE_COUNT;

  useEffect(() => {
    const group = firstGroup.current;
    if (!group || !hasMore) return;
    const measure = () => setHeight(group.getBoundingClientRect().height);
    const observer = new ResizeObserver(measure);
    observer.observe(group);
    measure();
    return () => observer.disconnect();
  }, [hasMore]);

  return (
    <div className={`stack ${styles.list}`} style={{ maxHeight: hasMore ? height : undefined }} data-scrollable={hasMore}
      role="region" aria-label="Lista de notificações" tabIndex={hasMore ? 0 : undefined}>
      <div className="stack" ref={firstGroup}>
        {items.slice(0, VISIBLE_COUNT).map((item) => <NotificationCard key={item.id} item={item} onOpen={onOpen} />)}
      </div>
      {hasMore && <div className="stack">
        {items.slice(VISIBLE_COUNT).map((item) => <NotificationCard key={item.id} item={item} onOpen={onOpen} />)}
      </div>}
    </div>
  );
}

function Notificacoes() {
  const { data, error, reload, setData } = useApi<Notification[]>('/me/notifications', 10000);
  const { me, refresh } = useAuth();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  async function readAll() {
    setBusy(true);
    try {
      await post('/me/notifications/read-all');
      await Promise.all([reload(), refresh()]);
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Não foi possível marcar as notificações como lidas.');
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    try {
      await del('/me/notifications');
      setData([]);
      setConfirm(false);
      toast('ok', 'Notificações limpas.');
      await Promise.all([reload(), refresh()]);
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Não foi possível limpar as notificações.');
    } finally {
      setBusy(false);
    }
  }

  async function open(item: Notification) {
    if (item.read_at) return;
    try {
      await post(`/me/notifications/${item.id}/read`);
      await Promise.all([reload(), refresh()]);
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Não foi possível marcar a notificação como lida.');
    }
  }

  return (
    <>
      <PageHeader title="Notificações" subtitle="Avisos de fila, pagamentos, sessões e segurança.">
        <div className="row">
          <button className="btn" disabled={busy || (!me?.unread_notifications && !data?.some((item) => !item.read_at))} onClick={readAll}>Marcar todas como lidas</button>
          <button className="btn danger" disabled={busy || !data?.length} onClick={() => setConfirm(true)}>Limpar notificações</button>
        </div>
      </PageHeader>
      <ErrorBox error={error} onRetry={reload} />
      {data?.length ? <NotificationList items={data} onOpen={open} /> : !error && (
        data ? <Empty>Nenhuma notificação.</Empty> : <Skeleton h={200} />
      )}
      {confirm && <Modal title="Limpar notificações?" showCloseButton={false} onClose={() => setConfirm(false)}>
        <div className="stack">
          <p>As notificações atuais sairão da sua lista. O histórico ficará disponível para auditoria.</p>
          <div className="row">
            <button className="btn" onClick={() => setConfirm(false)} autoFocus disabled={busy}>Cancelar</button>
            <button className="btn danger" onClick={clear} disabled={busy}>{busy ? 'Limpando…' : 'Limpar'}</button>
          </div>
        </div>
      </Modal>}
    </>
  );
}
export default function Page() { return <RequireAuth><Notificacoes /></RequireAuth>; }
