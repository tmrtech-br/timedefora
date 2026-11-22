'use client';
import Link from 'next/link';
import RequireAuth from '@/components/RequireAuth';
import { Empty, PageHeader, Skeleton } from '@/components/ui';
import { post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';

type N = { id: string; title: string; body: string; link: string | null; read_at: string | null; created_at: string };

function Notificacoes() {
  const { data, reload } = useApi<N[]>('/me/notifications', 10000);
  const { refresh } = useAuth();
  async function readAll() { await post('/me/notifications/read-all'); reload(); refresh(); }
  async function open(n: N) { if (!n.read_at) { await post(`/me/notifications/${n.id}/read`); refresh(); } }
  return (
    <>
      <PageHeader title="Notificações" subtitle="Avisos de fila, pagamentos, sessões e segurança."><button className="btn" onClick={readAll}>Marcar todas como lidas</button></PageHeader>
      {!data ? <Skeleton h={200} /> : !data.length ? <Empty>Nenhuma notificação.</Empty> : (
        <div className="stack">{data.map((n) => (
          <article key={n.id} className="card" style={{ borderColor: n.read_at ? undefined : 'rgba(177,60,255,.6)' }}>
            <div className="spread"><b>{n.title}</b><span className="small dim">{dateTime(n.created_at)}</span></div>
            <p className="muted" style={{ margin: '6px 0' }}>{n.body}</p>
            {n.link && <Link className="link-purple small" href={n.link} onClick={() => open(n)}>Abrir</Link>}
          </article>))}</div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Notificacoes /></RequireAuth>; }
