'use client';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Alert, ErrorBox, Field, PageHeader, Skeleton } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';

type Ticket = { subject: string; status: string; category: string; messages: { id: string; body: string; is_staff: boolean; author: string; created_at: string }[] };

function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, reload } = useApi<Ticket>(`/support/tickets/${id}`, 15000);
  const [body, setBody] = useState('');
  const [err, setErr] = useState('');
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Skeleton h={200} />;
  return (
    <div className="stack" style={{ maxWidth: 800 }}>
      <PageHeader title={data.subject} subtitle={`${data.category} · ${data.status}`} />
      {data.messages.map((m) => <div key={m.id} className="card" style={{ borderColor: m.is_staff ? 'rgba(41,214,240,.5)' : undefined }}>
        <div className="spread small"><b>{m.is_staff ? 'Equipe LocaPlay' : m.author}</b><span className="dim">{dateTime(m.created_at)}</span></div>
        <p style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0' }}>{m.body}</p></div>)}
      {err && <Alert kind="error">{err}</Alert>}
      {data.status !== 'closed' && <><Field label="Responder"><textarea value={body} onChange={(e) => setBody(e.target.value)} /></Field>
        <button className="btn primary" disabled={!body.trim()} onClick={async () => { try { await post(`/support/tickets/${id}/messages`, { body }); setBody(''); reload(); } catch (e) { setErr((e as ApiError).message); } }}>Enviar</button></>}
    </div>
  );
}
export default function Page() { return <RequireAuth><TicketPage /></RequireAuth>; }
