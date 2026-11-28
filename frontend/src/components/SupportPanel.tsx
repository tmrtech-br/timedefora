'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Headphones, Send, X } from 'lucide-react';
import { ApiError, get, post } from '@/lib/api';
import { TICKET_STATUS, time } from '@/lib/format';
import { Alert } from './ui';

type Msg = { id: string; body: string; is_staff: boolean; author: string; created_at: string };
type Ticket = { id: string; subject: string; status: string; reservation_id: string | null; messages?: Msg[] };

const QUICK = ['A imagem está travando ou com atraso', 'O controle não responde', 'Estou sem áudio', 'O jogo errado está aberto', 'Outro problema'];

/**
 * Suporte durante a partida, num painel lateral: o jogo continua visível (e o tempo correndo) enquanto o jogador
 * fala com a equipe. Reaproveita o chamado aberto desta reserva; sem chamado, abre um já marcado como "Sessão".
 */
export default function SupportPanel({ open, onClose, reservationId, game, consoleName, onStaffReply }: {
  open: boolean; onClose: () => void; reservationId?: string; game?: string; consoleName?: string; onStaffReply?: (count: number) => void;
}) {
  const subject = reservationId ? `Sessão: ${game} em ${consoleName}`.slice(0, 140) : 'Portal do proprietário';
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const list = useRef<HTMLDivElement>(null);
  const seen = useRef(0);

  const load = useCallback(async () => {
    try {
      const all = await get<Ticket[]>('/support/tickets');
      const mine = all.find((t) => t.status !== 'closed' && (reservationId
        ? t.reservation_id === reservationId : !t.reservation_id && t.subject === subject));
      setTicket(mine ? await get<Ticket>(`/support/tickets/${mine.id}`) : null);
    } catch { /* mantém o que já está na tela */ }
    setLoaded(true);
  }, [reservationId, subject]);

  // Atualiza a conversa (5 s com o painel aberto; 20 s fechado, para avisar de resposta da equipe).
  useEffect(() => {
    if (!open && !reservationId) return;
    load();
    const t = setInterval(load, open ? 5000 : 20000);
    return () => clearInterval(t);
  }, [load, open, reservationId]);

  const staff = (ticket?.messages || []).filter((m) => m.is_staff).length;
  useEffect(() => {
    if (open) { seen.current = staff; onStaffReply?.(0); }
    else if (staff > seen.current) onStaffReply?.(staff - seen.current);
  }, [staff, open, onStaffReply]);
  useEffect(() => { if (open && list.current) list.current.scrollTop = list.current.scrollHeight; }, [open, ticket?.messages?.length]);

  async function send() {
    const body = text.trim();
    if (body.length < 3) { setErr('Descreva o problema (mínimo 3 caracteres).'); return; }
    setBusy(true); setErr('');
    try {
      if (ticket) await post(`/support/tickets/${ticket.id}/messages`, { body });
      else await post('/support/tickets', { subject, category: reservationId ? 'sessao' : 'geral', message: body, reservation_id: reservationId });
      setText('');
      await load();
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Não foi possível enviar. Tente de novo.'); }
    setBusy(false);
  }

  if (!open) return null;
  return (
    <aside className={`support-panel${reservationId ? '' : ' owner-support-panel'}`} role="dialog" aria-label={reservationId ? 'Suporte durante a partida' : 'Suporte do proprietário'}>
      <header>
        <div><b><Headphones size={16} aria-hidden /> Suporte</b>
          <small>{ticket ? `${TICKET_STATUS[ticket.status] || ticket.status} · resposta aqui mesmo` : reservationId ? 'Seu jogo continua rodando enquanto fala com a gente' : subject}</small></div>
        <button className="icon-btn" onClick={onClose} aria-label="Fechar suporte"><X size={18} /></button>
      </header>
      <div className="support-body" ref={list}>
        {!loaded ? <p className="small muted">Carregando…</p> : ticket ? (
          (ticket.messages || []).map((m) => (
            <div key={m.id} className={`support-msg ${m.is_staff ? 'staff' : 'me'}`}>
              <span className="who">{m.is_staff ? 'Equipe timedefora' : 'Você'} · {time(m.created_at)}</span>
              <p>{m.body}</p>
            </div>))
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            <p className="small muted" style={{ margin: 0 }}>{reservationId
              ? 'O que está acontecendo? O chamado já vai com o jogo, o console e o horário desta sessão.'
              : 'Conte para a equipe como podemos ajudar com o seu cadastro.'}</p>
            {reservationId && <div className="support-quick">{QUICK.map((q) => <button key={q} type="button" className="btn sm" onClick={() => setText(q === 'Outro problema' ? '' : q)}>{q}</button>)}</div>}
          </div>)}
        {ticket?.messages && !ticket.messages.some((m) => m.is_staff) && <p className="small dim" style={{ margin: 0 }}>Chamado recebido. A equipe responde aqui.</p>}
      </div>
      <footer>
        {err && <Alert kind="error">{err}</Alert>}
        <div className="support-input">
          <textarea rows={2} maxLength={5000} value={text} aria-label="Mensagem ao suporte" placeholder={ticket ? 'Escreva uma mensagem…' : 'Descreva o problema…'}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <button className="btn primary" onClick={send} disabled={busy || !text.trim()} aria-label="Enviar"><Send size={16} /></button>
        </div>
      </footer>
    </aside>
  );
}
