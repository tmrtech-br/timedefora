'use client';

import { useState, type FormEvent } from 'react';
import { Trash2 } from 'lucide-react';
import { Alert, ErrorBox, Field, PageHeader, Skeleton } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { TICKET_CATEGORY, TICKET_STATUS, dateTime } from '@/lib/format';
import styles from './support.module.css';

type Ticket = {
  subject: string;
  status: string;
  category: string;
  messages: { id: string; body: string; is_staff: boolean; author: string; created_at: string }[];
};

export default function TicketConversation({ id, audit = false, inDialog = false, onDelete }: { id: string; audit?: boolean; inDialog?: boolean; onDelete?: () => void }) {
  const ticketPath = `${audit ? '/admin' : ''}/support/tickets/${id}`;
  const { data, error, reload } = useApi<Ticket>(ticketPath, 15000);
  const [body, setBody] = useState('');
  const [err, setErr] = useState('');
  const [sending, setSending] = useState(false);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending || !body.trim()) return;
    setSending(true);
    setErr('');
    try {
      await post(`${ticketPath}/messages`, { body });
      setBody('');
      void reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Não foi possível enviar a resposta.');
    } finally {
      setSending(false);
    }
  }

  const deleteButton = onDelete && (
    <button type="button" className={`btn danger ${styles.dialogButton}`} onClick={onDelete}><Trash2 size={15} aria-hidden /> Excluir</button>
  );
  if (error || !data) return <div className="stack">
    {error ? <ErrorBox error={error} onRetry={reload} /> : <Skeleton h={200} />}
    {deleteButton && <div>{deleteButton}</div>}
  </div>;
  const subtitle = `${TICKET_CATEGORY[data.category] || data.category} · ${TICKET_STATUS[data.status] || data.status}`;
  return (
    <div className="stack">
      {inDialog ? <p className={styles.conversationMeta}>{subtitle}</p> : (
        <PageHeader title={data.subject} subtitle={audit ? `Histórico para auditoria · ${subtitle}` : subtitle} />
      )}
      <div className={inDialog ? styles.conversationScroll : 'stack'} role="region" aria-label="Mensagens do chamado" tabIndex={inDialog ? 0 : undefined}>
        {data.messages.map((message) => (
          <article key={message.id} className={`card ${styles.message}`} data-staff={message.is_staff}>
            <div className="spread small"><b>{message.is_staff ? 'Equipe timedefora' : message.author}</b><time className="dim" dateTime={message.created_at}>{dateTime(message.created_at)}</time></div>
            <p>{message.body}</p>
          </article>
        ))}
      </div>
      {err && <Alert kind="error">{err}</Alert>}
      {data.status === 'closed' ? (deleteButton && <div>{deleteButton}</div>) : (
        <form className="stack" onSubmit={send}>
          <Field label={audit ? 'Adicionar mensagem ao histórico' : 'Responder'}><textarea maxLength={5000} rows={3} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
          <div className={inDialog ? styles.conversationActions : undefined}>
            {deleteButton}
            <button type="submit" className={`btn primary ${inDialog ? styles.dialogButton : ''}`} disabled={sending || !body.trim()}>{sending ? 'Enviando…' : 'Enviar'}</button>
          </div>
        </form>
      )}
    </div>
  );
}
