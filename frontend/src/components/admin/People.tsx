'use client';
import { useState } from 'react';
import { Copy } from 'lucide-react';
import { Alert, Field, Modal, PageHeader } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { patch, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, useAction } from './common';

type R = Record<string, unknown>;

export function Users() {
  const [q, setQ] = useState('');
  const { me } = useAuth();
  const list = useApi<R[]>(`/admin/users?q=${encodeURIComponent(q)}`);
  const { run, msg } = useAction();
  const sup = me?.roles.includes('superadmin');
  return (
    <div className="stack">
      <PageHeader title="Usuários e permissões" subtitle="Senhas, tokens e dados sensíveis nunca são exibidos." />
      {msg}
      <input className="btn" placeholder="Buscar por usuário, e-mail ou nome" value={q} onChange={(e) => setQ(e.target.value)} />
      <section className="card"><DataTable rows={list.data} cols={[['Usuário', (r) => String(r.username)], ['Nome', (r) => String(r.full_name)], ['E-mail', (r) => String(r.email)],
        ['Papéis', (r) => (r.roles as string[]).join(', ')], ['Status', (r) => String(r.status)], ['Último acesso', (r) => dateTime(r.last_login_at as string)],
        ['Ações', (r) => <div className="row">
          <button className="btn sm" onClick={() => { const reason = prompt(r.status === 'suspended' ? 'Motivo da reativação:' : 'Motivo da suspensão:'); if (reason) run(async () => { await post(`/admin/users/${r.id}/suspension`, { suspend: r.status !== 'suspended', reason }); list.reload(); }, 'Atualizado.'); }}>{r.status === 'suspended' ? 'Reativar' : 'Suspender'}</button>
          {sup && <select className="btn sm" value="" onChange={(e) => { const [g, role] = e.target.value.split(':'); if (role) run(async () => { await post(`/admin/users/${r.id}/roles`, { role, grant: g === '+' }); list.reload(); }, 'Papéis atualizados.'); }}>
            <option value="">Papéis…</option>{['operator', 'admin', 'superadmin'].map((x) => <option key={x} value={`${(r.roles as string[]).includes(x) ? '-' : '+'}:${x}`}>{(r.roles as string[]).includes(x) ? 'Remover' : 'Conceder'} {x}</option>)}</select>}</div>]]} /></section>
    </div>
  );
}

export function Notifications() {
  const t = useApi<R[]>('/admin/notification-templates');
  const d = useApi<R[]>('/admin/notification-deliveries');
  const [edit, setEdit] = useState<R | null>(null);
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Notificações" subtitle="Templates HTML/texto, entregas, falhas e reenvio. Variáveis entre chaves, ex.: {nome_usuario}." />
      {msg}
      {edit && <section className="card stack"><h2>{String(edit.code)} · {String(edit.channel)}</h2>
        <Field label="Assunto / título"><input maxLength={200} value={String(edit.subject)} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} /></Field>
        <Field label="Texto"><textarea maxLength={50000} value={String(edit.body_text)} onChange={(e) => setEdit({ ...edit, body_text: e.target.value })} /></Field>
        {edit.channel === 'email' && <Field label="HTML"><textarea maxLength={50000} value={String(edit.body_html)} onChange={(e) => setEdit({ ...edit, body_html: e.target.value })} /></Field>}
        <div className="row"><button className="btn primary" onClick={() => run(async () => { await put(`/admin/notification-templates/${edit.id}`, { subject: edit.subject, body_text: edit.body_text, body_html: edit.body_html, active: edit.active }); setEdit(null); t.reload(); }, 'Template salvo.')}>Salvar</button>
          <button className="btn" onClick={() => setEdit(null)}>Fechar</button></div></section>}
      <section className="card"><h2>Templates</h2><DataTable rows={t.data} cols={[['Código', (r) => String(r.code)], ['Canal', (r) => String(r.channel)], ['Assunto', (r) => String(r.subject)], ['Versão', (r) => String(r.version)],
        ['', (r) => <button className="btn sm" onClick={() => setEdit(r)}>Editar</button>]]} /></section>
      <section className="card"><h2>Entregas de e-mail</h2><DataTable rows={d.data} cols={[['Quando', (r) => dateTime(String(r.created_at))], ['Evento', (r) => String(r.event_code)], ['Para', (r) => String(r.to_address)],
        ['Status', (r) => String(r.status)], ['Tentativas', (r) => String(r.attempts)], ['Erro', (r) => String(r.last_error || '')],
        ['', (r) => r.status === 'failed' ? <button className="btn sm" onClick={() => run(async () => { await post(`/admin/notification-deliveries/${r.id}/retry`); d.reload(); }, 'Reenvio solicitado.')}>Reenviar</button> : null]]} /></section>
    </div>
  );
}

export function Support() {
  const [status, setStatus] = useState('open');
  const list = useApi<R[]>(`/admin/support/tickets?status=${status}`);
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Suporte" />
      {msg}
      <select className="btn" value={status} onChange={(e) => setStatus(e.target.value)}><option value="open">Abertos</option><option value="in_progress">Em andamento</option><option value="resolved">Resolvidos</option><option value="closed">Fechados</option><option value="">Todos</option></select>
      <section className="card"><DataTable rows={list.data} cols={[['Assunto', (r) => <a className="link-purple" href={`/suporte/${r.id}`}>{String(r.subject)}</a>], ['Usuário', (r) => String(r.username)], ['Categoria', (r) => String(r.category)],
        ['Prioridade', (r) => String(r.priority)], ['Atualizado', (r) => dateTime(String(r.updated_at))],
        ['Status', (r) => <select className="btn sm" value={String(r.status)} onChange={(e) => run(async () => { await patch(`/admin/support/tickets/${r.id}`, { status: e.target.value }); list.reload(); })}>
          {['open', 'in_progress', 'resolved', 'closed'].map((s) => <option key={s}>{s}</option>)}</select>]]} /></section>
    </div>
  );
}

export function Lgpd() {
  const list = useApi<R[]>('/admin/data-requests');
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Solicitações LGPD" subtitle="Exclusão anonimiza dados pessoais e preserva registros financeiros obrigatórios." />
      {msg}
      <section className="card"><DataTable rows={list.data} cols={[['Usuário', (r) => String(r.username)], ['Tipo', (r) => String(r.request_type)], ['Detalhes', (r) => String(r.details)],
        ['Status', (r) => String(r.status)], ['Criada', (r) => dateTime(String(r.created_at))],
        ['', (r) => ['open', 'in_progress'].includes(String(r.status)) ? <div className="row">{['in_progress', 'completed', 'rejected'].map((s) => <button key={s} className="btn sm" onClick={() => { const resolution = prompt('Registro da resolução:'); if (resolution) run(async () => { await post(`/admin/data-requests/${r.id}/resolve`, { status: s, resolution }); list.reload(); }, 'Atualizado.'); }}>{s}</button>)}</div> : String(r.resolution || '')]]} /></section>
    </div>
  );
}

export function Audit() {
  const [table, setTable] = useState('');
  const [record, setRecord] = useState('');
  const list = useApi<R[]>(`/admin/audit?limit=300${table ? `&table_name=${table}` : ''}${record ? `&record_id=${record}` : ''}`);
  const [detail, setDetail] = useState<{ title: string; json: string } | null>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="stack">
      <PageHeader title="Auditoria" subtitle="Toda inserção, alteração e exclusão (trigger no banco) e ações de negócio. Registros imutáveis; segredos mascarados." />
      <div className="row"><input className="btn" placeholder="Tabela (ex.: reservations)" value={table} onChange={(e) => setTable(e.target.value)} />
        <input className="btn" placeholder="ID do registro" value={record} onChange={(e) => setRecord(e.target.value)} /></div>
      <section className="card"><DataTable rows={list.data} cols={[['Quando', (r) => dateTime(String(r.occurred_at))], ['Origem', (r) => String(r.source)], ['Ação', (r) => String(r.action)],
        ['Tabela / registro', (r) => `${r.table_name || '—'} · ${String(r.record_id || '').slice(0, 8)}`], ['Ator', (r) => String(r.actor_username || 'sistema')],
        ['Campos', (r) => ((r.changed_fields as string[]) || []).join(', ')], ['Motivo', (r) => String(r.reason || '')],
        ['Detalhes', (r) => <button className="btn sm" onClick={() => { setCopied(false); setDetail({ title: `${r.action} · ${r.table_name || '—'} · ${dateTime(String(r.occurred_at))}`,
          json: JSON.stringify({ antes: r.old_data, depois: r.new_data, ...((r.details as object) || {}) }, null, 2) }); }}>Ver detalhes</button>]]} /></section>
      {detail && (
        <Modal title="Detalhes do registro de auditoria" onClose={() => setDetail(null)}>
          <div className="stack">
            <p className="small muted" style={{ margin: 0 }}>{detail.title}</p>
            <pre className="audit-json" tabIndex={0} aria-label="Conteúdo do registro">{detail.json}</pre>
            <div className="row">
              <button className="btn primary" onClick={async () => {
                try { await navigator.clipboard.writeText(detail.json); setCopied(true); toast('ok', 'Detalhes copiados.'); }
                catch { toast('error', 'Não foi possível copiar. Selecione o texto e use Ctrl+C.'); }
              }}><Copy size={16} aria-hidden />{copied ? 'Copiado!' : 'Copiar detalhes'}</button>
              <button className="btn" onClick={() => setDetail(null)}>Fechar</button>
            </div>
          </div>
        </Modal>)}
    </div>
  );
}

// Chaves editadas na tela Parâmetros (com rótulos e validação próprios).
const IN_PARAMS = new Set(['sales_paused', 'sales_paused_reason', 'disabled_platforms', 'signup_enabled', 'google_login_enabled', 'queue_mode_enabled',
  'scheduled_mode_enabled', 'coupons_enabled', 'keyboard_mouse_enabled', 'public_streams_enabled', 'support_tickets_enabled', 'share_button_enabled', 'hold_minutes', 'setup_minutes',
  'scheduled_lead_minutes', 'queue_lead_minutes', 'booking_horizon_days', 'max_pending_holds_per_user', 'max_future_reservations_per_user',
  'cancel_full_refund_min_minutes_before', 'no_show_tolerance_minutes', 'featured_window_days', 'agent_heartbeat_timeout_seconds']);

/** Explicação curta de cada chave (exibida na tabela de Configurações operacionais). */
const SETTING_HELP: Record<string, string> = {
  reminder_minutes: 'Minutos antes do início em que o cliente recebe lembretes da reserva. Lista separada por vírgula (ex.: 15,10,5,1).',
  session_end_warnings_seconds: 'Segundos antes do fim da sessão em que o jogador vê avisos de "tempo acabando". Lista separada por vírgula (ex.: 600,300,60,30).',
  featured_metric: 'Critério do destaque "mais jogado" na home: minutes_played (minutos jogados), sessions_sold (sessões vendidas) ou revenue (receita).',
  support_hours_text: 'Texto exibido na página de Suporte com o horário de atendimento.',
  hold_minutes: 'Tempo que a reserva fica guardada aguardando o pagamento.',
  setup_minutes: 'Intervalo de preparação/limpeza do console entre dois jogadores.',
  queue_lead_minutes: 'Antecedência mínima para começar no modo fila (0 = assim que o console ficar livre).',
  scheduled_lead_minutes: 'Antecedência mínima para comprar um horário marcado.',
  booking_horizon_days: 'Até quantos dias à frente o cliente pode reservar.',
  max_pending_holds_per_user: 'Quantas reservas aguardando pagamento um cliente pode ter ao mesmo tempo.',
  max_future_reservations_per_user: 'Quantas reservas futuras um cliente pode ter ao mesmo tempo.',
  cancel_full_refund_min_minutes_before: 'Cancelando com pelo menos esta antecedência (minutos), o cliente recebe reembolso integral.',
  no_show_tolerance_minutes: 'Tolerância de atraso antes de considerar ausência (0 = o horário fica reservado até o fim).',
  featured_window_days: 'Período (dias) usado para calcular os jogos em destaque.',
  agent_heartbeat_timeout_seconds: 'Tempo sem sinal do agente local até o console ser marcado como offline.',
  sales_paused: 'Pausa a venda de tempo novo (reservas pagas continuam valendo).',
  sales_paused_reason: 'Mensagem mostrada aos clientes enquanto as vendas estiverem pausadas.',
  disabled_platforms: 'Plataformas desligadas: consoles e jogos delas saem da venda.',
};

export function Settings() {
  const s = useApi<{ values: Record<string, unknown>; defaults: Record<string, unknown>; critical: string[] }>('/admin/settings');
  const pol = useApi<R[]>('/admin/policies');
  const [vals, setVals] = useState<Record<string, string>>({});
  const [p, setP] = useState({ kind: 'cancellation', version: '', title: '', body: '' });
  const { run, msg } = useAction();
  const parse = (k: string, raw: string) => { const d = s.data!.defaults[k]; return typeof d === 'boolean' ? raw === 'true' : typeof d === 'number' ? Number(raw) : Array.isArray(d) ? raw.split(',').map((x) => Number(x.trim())) : raw; };
  return (
    <div className="stack">
      <PageHeader title="Configurações operacionais" subtitle="Alterações auditadas. Itens críticos exigem superadministrador." />
      {msg}
      <Alert kind="info"><span>Liga/desliga de funções, plataformas e regras de agenda ficam em <a className="link-purple" href="/admin/parametros">Parâmetros</a>. Aqui ficam os ajustes avançados.</span></Alert>
      <section className="card"><DataTable rows={s.data ? Object.entries(s.data.values).filter(([k]) => !IN_PARAMS.has(k)).map(([k, v]) => ({ id: k, k, v })) : null} cols={[['Chave', (r) => <span>{String(r.k)}{s.data!.critical.includes(String(r.k)) && <span className="pill amber" style={{ marginLeft: 6 }}>crítica</span>}</span>],
        ['O que é', (r) => <span className="small muted" style={{ display: 'block', maxWidth: 380 }}>{SETTING_HELP[String(r.k)] || 'Ajuste avançado do sistema.'}</span>],
        ['Valor', (r) => <input className="btn sm" style={{ width: 260, maxWidth: '100%' }} value={vals[String(r.k)] ?? (Array.isArray(r.v) ? (r.v as number[]).join(',') : String(r.v))} onChange={(e) => setVals({ ...vals, [String(r.k)]: e.target.value })} />],
        ['', (r) => <button className="btn sm" disabled={vals[String(r.k)] === undefined} onClick={() => { const reason = prompt('Motivo da alteração:') || ''; run(async () => { await put(`/admin/settings/${r.k}`, { value: parse(String(r.k), vals[String(r.k)]), reason }); s.reload(); }, 'Configuração salva.'); }}>Salvar</button>]]} /></section>
      <section className="card stack"><h2>Políticas (termos, privacidade, cancelamento)</h2>
        <div className="grid3"><Field label="Tipo"><select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })}><option value="terms">Termos</option><option value="privacy">Privacidade</option><option value="cancellation">Cancelamento</option></select></Field>
          <Field label="Versão"><input maxLength={20} value={p.version} onChange={(e) => setP({ ...p, version: e.target.value })} /></Field><Field label="Título"><input maxLength={200} value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} /></Field></div>
        <Field label="Texto"><textarea maxLength={50000} style={{ minHeight: 160 }} value={p.body} onChange={(e) => setP({ ...p, body: e.target.value })} /></Field>
        <button className="btn primary" onClick={() => run(async () => { await post('/admin/policies', p); pol.reload(); }, 'Nova versão publicada.')}>Publicar nova versão</button>
        <DataTable rows={pol.data} cols={[['Tipo', (r) => String(r.kind)], ['Versão', (r) => String(r.version)], ['Atual', (r) => (r.is_current ? 'sim' : 'não')], ['Publicada', (r) => dateTime(r.published_at as string)]]} /></section>
    </div>
  );
}
