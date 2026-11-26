'use client';
import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { ArrowUpRight, ChevronDown, Gamepad2, LifeBuoy, ListOrdered, MessagesSquare, Send, Ticket, Timer, Trash2, Wrench } from 'lucide-react';
import { Alert, Empty, ErrorBox, Field, Loading, Modal, PageHeader } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { ApiError, del, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { TICKET_CATEGORY, TICKET_STATUS, dateTime } from '@/lib/format';
import { useFeatures } from '@/lib/features';
import TicketConversation from './TicketConversation';
import styles from './support.module.css';

type SupportTicket = { id: string; subject: string; category: string; status: string; updated_at: string };
const INITIAL_FORM = { subject: '', category: 'geral', message: '' };

const FAQ = [
  { icon: ListOrdered, title: 'Como funciona a fila?', answer: 'Ao comprar em modo fila, você recebe um horário estimado. Se alguém antes de você cancelar ou terminar mais cedo, sua vez pode ser antecipada. Avisamos por notificação. Depois da confirmação, o horário nunca é adiado.' },
  { icon: Timer, title: 'Cheguei atrasado. Ganho mais tempo?', answer: 'Seu intervalo termina no horário contratado. Você pode reconectar e jogar até o fim da reserva.' },
  { icon: Wrench, title: 'Deu problema no console. E agora?', answer: 'Abra um chamado na categoria Sessão de jogo e descreva o que aconteceu. Em caso de falha da plataforma, a equipe pode oferecer extensão, quando houver disponibilidade, remarcação ou reembolso.' },
  { icon: Gamepad2, title: 'Posso usar controle?', answer: 'Sim. Use um controle USB ou Bluetooth compatível com seu navegador. Você pode testá-lo na sala de espera. No celular, a compatibilidade é limitada.' },
];

export default function Suporte() {
  const { me, loading: loadingAccount } = useAuth();
  const features = useFeatures();
  const { data: tickets, error, loading, reload, setData } = useApi<SupportTicket[]>(me ? '/support/tickets' : null);
  const [form, setForm] = useState(INITIAL_FORM);
  const [formVersion, setFormVersion] = useState(0);
  const [sending, setSending] = useState(false);
  const [opened, setOpened] = useState<SupportTicket | null>(null);
  const [selected, setSelected] = useState<SupportTicket | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState('');

  async function open(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending || form.subject.trim().length < 3 || form.message.trim().length < 3) return;
    setSending(true);
    try {
      await post('/support/tickets', { ...form, subject: form.subject.trim(), message: form.message.trim() });
      setForm(INITIAL_FORM);
      setFormVersion((version) => version + 1);
      toast('ok', 'Chamado aberto. Você será notificado quando a equipe responder.');
      void reload();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Não foi possível abrir o chamado.');
    } finally {
      setSending(false);
    }
  }

  async function remove() {
    if (!selected || removing) return;
    setRemoving(true);
    setRemoveError('');
    try {
      await del(`/support/tickets/${selected.id}`);
      setData((items) => items?.filter((ticket) => ticket.id !== selected.id) ?? null);
      setOpened(null);
      setSelected(null);
      toast('ok', 'Chamado removido da sua lista.');
      void reload();
    } catch (e) {
      setRemoveError(e instanceof ApiError ? e.message : 'Não foi possível remover o chamado.');
    } finally {
      setRemoving(false);
    }
  }

  return (
    <>
      <PageHeader title="Central de suporte" subtitle="Encontre respostas rápidas ou fale com a nossa equipe em horário comercial de Fortaleza." />
      <div className={styles.page}>
        <div className={styles.columns}>
          <section className={styles.panel} aria-labelledby="support-faq">
            <h2 id="support-faq"><LifeBuoy aria-hidden /> Perguntas frequentes</h2>
            <div className={styles.faq}>
              {FAQ.map(({ icon: Icon, title, answer }) => (
                <details key={title} name="support-faq" className={styles.question}>
                  <summary><span className={styles.questionIcon}><Icon aria-hidden /></span><span>{title}</span><ChevronDown className={styles.chevron} aria-hidden /></summary>
                  <p>{answer}</p>
                </details>
              ))}
            </div>
          </section>

          <section className={styles.panel} aria-labelledby="support-new">
            <h2 id="support-new"><MessagesSquare aria-hidden /> Abrir chamado</h2>
            {features?.support_tickets_enabled === false ? (
              <Alert kind="warn">A abertura de novos chamados está temporariamente desativada.</Alert>
            ) : loadingAccount ? <Loading /> : !me ? (
              <div className={styles.signIn}>
                <p>Entre para enviar uma mensagem e acompanhar as respostas da equipe.</p>
                <Link className="btn primary" href="/entrar?proximo=/suporte">Entrar na conta <ArrowUpRight size={15} aria-hidden /></Link>
              </div>
            ) : (
              <form key={formVersion} className={styles.form} onSubmit={open}>
                <Field label="Assunto" required><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder="Resuma o que aconteceu" maxLength={140} /></Field>
                <Field label="Categoria"><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {Object.entries(TICKET_CATEGORY).map(([value, label]) => <option key={value} value={value}>{value === 'sessao' ? 'Sessão de jogo' : label}</option>)}
                </select></Field>
                <Field label="Mensagem" required><textarea value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} placeholder="Conte os detalhes para a equipe" rows={4} maxLength={5000} /></Field>
                <button className="btn primary" type="submit" disabled={sending || form.subject.trim().length < 3 || form.message.trim().length < 3}><Send size={15} aria-hidden /> {sending ? 'Enviando…' : 'Enviar chamado'}</button>
              </form>
            )}
          </section>
        </div>

        {me && <section className={styles.panel} aria-labelledby="support-tickets">
          <h2 id="support-tickets"><Ticket aria-hidden /> Meus chamados</h2>
          <ErrorBox error={error} onRetry={reload} />
          {loading ? <Loading label="Carregando chamados…" /> : tickets?.length ? (
            <div className={styles.ticketScroll} tabIndex={tickets.length > 5 ? 0 : undefined} role="region" aria-labelledby="support-tickets">
              <ul className={styles.tickets}>
                {tickets.map((ticket) => (
                  <li className={styles.ticket} key={ticket.id}>
                    <button type="button" className={styles.ticketLink} title={ticket.subject} aria-haspopup="dialog" onClick={() => setOpened(ticket)}>
                      <strong>{ticket.subject}</strong>
                      <span>{TICKET_CATEGORY[ticket.category] || ticket.category} · {dateTime(ticket.updated_at)}</span>
                    </button>
                    <span className={styles.ticketStatus} data-status={ticket.status}>{TICKET_STATUS[ticket.status] || ticket.status}</span>
                    <button type="button" className={styles.remove} aria-label={`Remover chamado: ${ticket.subject}`} onClick={() => { setRemoveError(''); setSelected(ticket); }}><Trash2 size={17} aria-hidden /></button>
                  </li>
                ))}
              </ul>
            </div>
          ) : !error && <Empty>Você ainda não tem chamados.</Empty>}
        </section>}

        {(opened || selected) && <Modal title={selected ? 'Remover chamado da sua lista?' : opened?.subject ?? ''} showCloseButton={!selected} closeButtonClassName={`${styles.dialogButton} ${styles.closeButton}`} onClose={() => {
          if (removing) return;
          setOpened(null);
          setSelected(null);
        }}>
          {opened && <div hidden={!!selected}>
            <TicketConversation key={opened.id} id={opened.id} inDialog onDelete={() => { setRemoveError(''); setSelected(opened); }} />
          </div>}
          {selected && <div className="stack">
            <p>O chamado <strong>{selected.subject}</strong> sairá da sua lista. A equipe poderá consultar o histórico para auditoria.</p>
            {removeError && <Alert kind="error">{removeError}</Alert>}
            <div className="row">
              <button type="button" className={`btn ${styles.dialogButton}`} autoFocus disabled={removing} onClick={() => setSelected(null)}>Cancelar</button>
              <button type="button" className={`btn danger ${styles.dialogButton}`} disabled={removing} onClick={remove}>{removing ? 'Removendo…' : 'Excluir'}</button>
            </div>
          </div>}
        </Modal>}
      </div>
    </>
  );
}
