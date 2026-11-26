'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Alert, Empty, Field, PageHeader } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { TICKET_CATEGORY, TICKET_STATUS, dateTime } from '@/lib/format';
import { useFeatures } from '@/lib/features';

type T = { id: string; subject: string; category: string; status: string; updated_at: string };
const FAQ = [
  ['Como funciona a fila?', 'Ao comprar em modo fila você recebe um início estimado. Se alguém antes de você cancelar ou terminar mais cedo, sua vez pode ser antecipada (avisamos por notificação). Ela nunca é atrasada depois da confirmação.'],
  ['Cheguei atrasado. Ganho mais tempo?', 'Não. O intervalo é exclusivo e termina no horário contratado. Você pode reconectar até o fim.'],
  ['Deu problema no console. E agora?', 'Falhas da plataforma não consomem seu tempo injustamente: abra um chamado e oferecemos extensão (se houver capacidade), remarcação ou reembolso.'],
  ['Posso usar controle?', 'Sim, controles USB/Bluetooth compatíveis com o navegador (Gamepad API). Teste na sala de espera. No celular a compatibilidade é limitada.'],
];

export default function Suporte() {
  const { me } = useAuth();
  const features = useFeatures();
  const tickets = useApi<T[]>(me ? '/support/tickets' : null);
  const [f, setF] = useState({ subject: '', category: 'geral', message: '' });
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  async function open() {
    try { await post('/support/tickets', f); setF({ subject: '', category: 'geral', message: '' }); setMsg({ k: 'ok', t: 'Chamado aberto. Você será notificado quando a equipe responder.' }); tickets.reload(); }
    catch (e) { setMsg({ k: 'error', t: (e as ApiError).message }); }
  }
  return (
    <div className="stack">
      <PageHeader title="Suporte" subtitle="Atendimento por chamado. Resposta em horário comercial (Fortaleza)." />
      <div className="grid2">
        <section className="card stack">
          <h2>Abrir chamado</h2>
          {features?.support_tickets_enabled === false ? <Alert kind="warn">A abertura de novos chamados está temporariamente desativada.</Alert> : !me ? <p>Para abrir um chamado, <Link className="link-purple" href="/entrar?proximo=/suporte">entre na sua conta</Link>.</p> : <>
            {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
            <Field label="Assunto" required><input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} maxLength={140} /></Field>
            <Field label="Categoria"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
              <option value="geral">Geral</option><option value="sessao">Sessão de jogo</option><option value="pagamento">Pagamento</option><option value="reembolso">Reembolso</option><option value="conta">Conta</option><option value="tecnico">Técnico</option></select></Field>
            <Field label="Mensagem" required><textarea value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} maxLength={5000} /></Field>
            <button className="btn primary" disabled={f.subject.length < 3 || f.message.length < 3} onClick={open}>Enviar</button>
          </>}
        </section>
        <section className="card"><h2>Perguntas frequentes</h2>{FAQ.map(([q, a]) => <details key={q} style={{ marginBottom: 8 }}><summary><b>{q}</b></summary><p className="muted">{a}</p></details>)}</section>
      </div>
      {me && <section className="card"><h2>Meus chamados</h2>
        {!tickets.data?.length ? <Empty>Nenhum chamado.</Empty> : tickets.data.map((t) => (
          <div key={t.id} className="spread" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
            <Link className="link-purple" href={`/suporte/${t.id}`}>{t.subject}</Link><span className="small muted">{TICKET_CATEGORY[t.category] || t.category} · {TICKET_STATUS[t.status] || t.status} · {dateTime(t.updated_at)}</span></div>))}
      </section>}
    </div>
  );
}
