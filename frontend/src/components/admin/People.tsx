'use client';
import DateFilter from '@/components/DateFilter';
import { exportExcel, printReports } from './exportReport';
import { useState } from 'react';
import { Copy } from 'lucide-react';
import { Alert, Field, Modal, PageHeader } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { del, get, patch, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime, DATA_REQUEST_STATUS, TICKET_CATEGORY, TICKET_STATUS } from '@/lib/format';
import { permissionLabel } from '@/lib/permissionsLabels';
import { DataTable, useAction, useAsk } from './common';
const DR_STATUS_PT = { in_progress: 'Em andamento', completed: 'Concluir', rejected: 'Recusar' } as const;

type R = Record<string, unknown>;

type PermissionDocument = {
  version: number;
  overrides: Record<string, boolean>;
  catalog: { key: string; label: string; kind: 'menu' | 'level' | 'action'; minimum: string }[];
};

const ROLE_NAMES: Record<string, string> = {
  client: 'Cliente', operator: 'Operador', admin: 'Administrador', superadmin: 'Superadministrador', owner: 'Proprietário',
};
const USER_STATUS: Record<string, string> = {
  active: 'Ativo', pending_verification: 'Aguardando verificação', suspended: 'Suspenso', deleted: 'Excluído',
};
const TICKET_PRIORITY: Record<string, string> = { low: 'Baixa', normal: 'Normal', high: 'Alta', urgent: 'Urgente' };
const DATA_REQUEST_TYPE: Record<string, string> = {
  access: 'Acesso aos dados', rectification: 'Correção de dados', deletion: 'Exclusão da conta',
  portability: 'Portabilidade', consent_revocation: 'Revogação de consentimento',
};

export function Users() {
  const [filters, setFilters] = useState({ q: '', role: '', status: '' });
  const [draft, setDraft] = useState(filters);
  const { me } = useAuth();
  const list = useApi<R[]>(`/admin/users?${new URLSearchParams(filters)}`);
  const { run, msg, busy } = useAction();
  const [ask, askDialog] = useAsk();
  const sup = me?.roles.includes('superadmin');
  const [permissions, setPermissions] = useState<PermissionDocument & { userId: string; username: string }>();
  return (
    <div className="stack">
      <PageHeader title="Usuários e permissões" subtitle="Senhas, tokens e dados sensíveis nunca são exibidos." />
      {msg}
      <form className="card stack audit-filters" onSubmit={(e) => {
        e.preventDefault();
        if (filters.q !== draft.q || filters.role !== draft.role || filters.status !== draft.status) list.setData(null);
        setFilters(draft);
      }}>
        <div className="audit-filter-grid">
          <Field label="Buscar usuário"><input type="search" placeholder="Usuário, e-mail ou nome" value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} /></Field>
          <Field label="Papel"><select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            <option value="">Todos</option>{Object.entries(ROLE_NAMES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></Field>
          <Field label="Status"><select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
            <option value="">Todos</option>{Object.entries(USER_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></Field>
        </div>
        <div className="row"><button className="btn primary">Filtrar</button><button type="button" className="btn" onClick={() => {
          const empty = { q: '', role: '', status: '' };
          if (filters.q || filters.role || filters.status) list.setData(null);
          setDraft(empty); setFilters(empty);
        }}>Limpar filtros</button></div>
      </form>
      <section className="card"><DataTable limit={5} rows={list.data} error={list.error?.message} cols={[['Usuário', (r) => String(r.username)], ['Nome', (r) => String(r.full_name)], ['E-mail', (r) => String(r.email)],
        ['Papéis', (r) => (r.roles as string[]).map((role) => ROLE_NAMES[role] ?? role).join(', ')], ['Status', (r) => USER_STATUS[String(r.status)] ?? 'Indefinido'], ['Último acesso', (r) => dateTime(r.last_login_at as string)],
        ['Ações', (r) => <div className="row">
          <button className="btn sm" onClick={async () => {
            const susp = r.status !== 'suspended';
            const reason = await ask({ title: `${susp ? 'Suspender' : 'Reativar'} ${String(r.username)}?`, label: susp ? 'Motivo da suspensão' : 'Motivo da reativação',
              danger: susp, confirm: susp ? 'Suspender' : 'Reativar', message: susp ? 'A pessoa perde o acesso e as sessões abertas são encerradas.' : undefined });
            if (reason) run(async () => { await post(`/admin/users/${r.id}/suspension`, { suspend: susp, reason }); list.reload(); }, 'Atualizado.');
          }}>{r.status === 'suspended' ? 'Reativar' : 'Suspender'}</button>
          {sup && r.id !== me?.id && <button className="btn sm" disabled={busy} onClick={() => run(async () => {
            const userId = String(r.id);
            const data = await get<PermissionDocument>(`/admin/users/${userId}/permissions`);
            setPermissions({ ...data, userId, username: String(r.username) });
          })}>Permissões</button>}
          {sup && r.id !== me?.id && me?.permission_overrides?.['action:DELETE:/admin/users/{uid}'] !== false &&
            <button className="btn sm danger" disabled={busy} onClick={async () => {
              const reason = await ask({ title: `Excluir ${String(r.username)}?`, label: 'Motivo da exclusão',
                message: 'A conta perde o acesso e o histórico operacional é preservado.', danger: true, confirm: 'Excluir' });
              if (reason) void run(async () => { await del(`/admin/users/${r.id}`, { reason }); await list.reload(); }, 'Usuário excluído.');
            }}>Excluir</button>}
          {sup && <select className="btn sm" value="" onChange={(e) => { const [g, role] = e.target.value.split(':'); if (role) run(async () => { await post(`/admin/users/${r.id}/roles`, { role, grant: g === '+' }); list.reload(); }, 'Papéis atualizados.'); }}>
            <option value="">Papéis…</option>{['operator', 'admin', 'superadmin', 'owner'].map((x) => <option key={x} value={`${(r.roles as string[]).includes(x) ? '-' : '+'}:${x}`}>{(r.roles as string[]).includes(x) ? 'Remover' : 'Conceder'} {x}</option>)}</select>}</div>]]} /></section>
      {askDialog}
      {permissions && <Modal title={`Permissões de ${permissions.username}`} onClose={() => setPermissions(undefined)}>
        <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await put(`/admin/users/${permissions.userId}/permissions`, {
              version: permissions.version, overrides: permissions.overrides,
            });
            setPermissions(undefined);
          }, 'Permissões atualizadas.');
        }}>
          <p className="small muted">As permissões marcadas respeitam o papel da pessoa.</p>
          <div className="stack" style={{ maxHeight: '55vh', overflowY: 'auto' }}>
            {(['menu', 'level', 'action'] as const).map((kind) => <fieldset key={kind} className="stack">
              <legend>{{ menu: 'Menus', level: 'Níveis de acesso', action: 'Ações' }[kind]}</legend>
              {permissions.catalog.filter((item) => item.kind === kind).map((item) => (
                <label key={item.key} className="row">
                  <input type="checkbox" checked={permissions.overrides[item.key] !== false} onChange={(event) => {
                    const enabled = event.target.checked;
                    setPermissions((current) => {
                      if (!current) return current;
                      const overrides = { ...current.overrides };
                      if (enabled) delete overrides[item.key];
                      else overrides[item.key] = false;
                      return { ...current, overrides };
                    });
                  }} />
                  <span>{kind === 'action' ? permissionLabel(item.label) : item.label}</span>
                </label>
              ))}
            </fieldset>)}
          </div>
          <div className="row">
            <button className="btn primary" type="submit" disabled={busy}>Salvar permissões</button>
            <button className="btn" type="button" disabled={busy} onClick={() => setPermissions({ ...permissions, overrides: {} })}>Restaurar padrão do papel</button>
          </div>
        </form>
      </Modal>}
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
      {edit && <Modal title={`Editar ${String(edit.code)} · ${String(edit.channel)}`} onClose={() => setEdit(null)}>
        <div className="stack">
        <Field label="Assunto / título"><input maxLength={200} value={String(edit.subject)} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} /></Field>
        <Field label="Texto"><textarea maxLength={50000} value={String(edit.body_text)} onChange={(e) => setEdit({ ...edit, body_text: e.target.value })} /></Field>
        {edit.channel === 'email' && <Field label="HTML"><textarea maxLength={50000} value={String(edit.body_html)} onChange={(e) => setEdit({ ...edit, body_html: e.target.value })} /></Field>}
        <div className="row"><button className="btn primary" onClick={() => run(async () => { await put(`/admin/notification-templates/${edit.id}`, { subject: edit.subject, body_text: edit.body_text, body_html: edit.body_html, active: edit.active }); setEdit(null); t.reload(); }, 'Template salvo.')}>Salvar</button>
          <button className="btn" onClick={() => setEdit(null)}>Cancelar</button></div></div></Modal>}
      <section className="card"><h2>Templates</h2><DataTable rows={t.data} error={t.error?.message} cols={[['Código', (r) => String(r.code)], ['Canal', (r) => String(r.channel)], ['Assunto', (r) => String(r.subject)], ['Versão', (r) => String(r.version)],
        ['', (r) => <button className="btn sm" onClick={() => setEdit(r)}>Editar</button>]]} /></section>
      <section className="card"><h2>Entregas de e-mail</h2><DataTable rows={d.data} error={d.error?.message} cols={[['Quando', (r) => dateTime(String(r.created_at))], ['Evento', (r) => String(r.event_code)], ['Para', (r) => String(r.to_address)],
        ['Status', (r) => String(r.status)], ['Tentativas', (r) => String(r.attempts)], ['Erro', (r) => String(r.last_error || '')],
        ['', (r) => r.status === 'failed' ? <button className="btn sm" onClick={() => run(async () => { await post(`/admin/notification-deliveries/${r.id}/retry`); d.reload(); }, 'Reenvio solicitado.')}>Reenviar</button> : null]]} /></section>
    </div>
  );
}

export function Support() {
  const [status, setStatus] = useState('open');
  const [query, setQuery] = useState('');
  const list = useApi<R[]>(`/admin/support/tickets?status=${status}&q=${encodeURIComponent(query)}`);
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Suporte" />
      {msg}
      <div className="row">
        <select className="btn" aria-label="Status do chamado" value={status} onChange={(e) => setStatus(e.target.value)}><option value="open">Abertos</option><option value="in_progress">Em andamento</option><option value="resolved">Resolvidos</option><option value="closed">Fechados</option><option value="">Todos</option></select>
        <input className="btn" aria-label="Buscar chamados" placeholder="Assunto, usuário ou ID" value={query} onChange={(e) => { setQuery(e.target.value); if (e.target.value.trim()) setStatus(''); }} />
      </div>
      <section className="card"><h2>Chamados de suporte</h2><DataTable limit={5} rows={list.data} error={list.error?.message} cols={[['Assunto', (r) => (
        <div><a className="link-purple" href={`/suporte/${r.id}${r.hidden_by_user_at ? '?auditoria=1' : ''}`}>{String(r.subject)}</a>
          {Boolean(r.hidden_by_user_at) && <div className="small muted">Removido da lista pelo usuário em {dateTime(String(r.hidden_by_user_at))}</div>}</div>
      )], ['Usuário', (r) => String(r.username)], ['Categoria', (r) => TICKET_CATEGORY[String(r.category)] ?? 'Outra'],
        ['Prioridade', (r) => TICKET_PRIORITY[String(r.priority)] ?? '—'], ['Atualizado', (r) => dateTime(String(r.updated_at))],
        ['Status', (r) => <select className="btn sm" value={String(r.status)} onChange={(e) => run(async () => { await patch(`/admin/support/tickets/${r.id}`, { status: e.target.value }); list.reload(); })}>
          {Object.entries(TICKET_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>]]} /></section>
    </div>
  );
}

export function Lgpd() {
  const list = useApi<R[]>('/admin/data-requests');
  const { run, msg } = useAction();
  const [ask, askDialog] = useAsk();
  return (
    <div className="stack">
      <PageHeader title="Solicitações LGPD" subtitle="Exclusão anonimiza dados pessoais e preserva registros financeiros obrigatórios." />
      {msg}
      <section className="card"><h2>Solicitações LGPD</h2><DataTable limit={5} rows={list.data} error={list.error?.message} cols={[['Usuário', (r) => String(r.username)], ['Tipo', (r) => DATA_REQUEST_TYPE[String(r.request_type)] ?? 'Outro'], ['Detalhes', (r) => String(r.details)],
        ['Status', (r) => DATA_REQUEST_STATUS[String(r.status)] ?? 'Indefinido'], ['Criada', (r) => dateTime(String(r.created_at))],
        ['', (r) => ['open', 'in_progress'].includes(String(r.status)) ? <div className="row">{(['in_progress', 'completed', 'rejected'] as const).map((s) => <button key={s} className="btn sm" onClick={async () => {
          const resolution = await ask({ title: `Solicitação LGPD: ${DR_STATUS_PT[s]}`, label: 'Registro da resolução', confirm: DR_STATUS_PT[s], danger: s === 'rejected' });
          if (resolution) run(async () => { await post(`/admin/data-requests/${r.id}/resolve`, { status: s, resolution }); list.reload(); }, 'Atualizado.');
        }}>{DR_STATUS_PT[s]}</button>)}</div> : String(r.resolution || '')]]} /></section>
      {askDialog}
    </div>
  );
}

const AUDIT_FILTERS = { table_name: '', record_id: '', source: '', action: '', from: '', to: '' };
const AUDIT_SOURCE: Record<string, string> = { db_trigger: 'Banco de dados', app: 'Aplicação' };

export function Audit() {
  const [draft, setDraft] = useState(AUDIT_FILTERS);
  const [query, setQuery] = useState('');
  const list = useApi<R[]>(`/admin/audit?limit=300${query}`);
  const report = { title: 'Auditoria', headers: ['Quando', 'Origem', 'Ação', 'Tabela', 'Registro', 'Ator', 'Campos', 'Motivo'],
    excelWidths: [132, 112, 210, 155, 223, 115, 305, 345],
    printWidths: [11, 8, 14, 10, 14, 8, 17, 18],
    rows: (list.data ?? []).map((r) => [dateTime(String(r.occurred_at)), AUDIT_SOURCE[String(r.source)] ?? 'Outra',
      String(r.action), String(r.table_name ?? ''), String(r.record_id ?? ''), String(r.actor_username || 'Sistema'),
      ((r.changed_fields as string[]) || []).join(', '), String(r.reason ?? '')]) };
  const reportHeader = {
    title: 'Relatório de auditoria', landscape: true,
    subtitle: `${report.rows.length.toLocaleString('pt-BR')} registros · Emitido em ${dateTime(new Date().toISOString())}`,
  };
  function applyQuery(next: string) {
    if (next === query) return;
    list.setData(null);
    setQuery(next);
  }
  const [detail, setDetail] = useState<{ title: string; json: string } | null>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="stack">
      <PageHeader title="Auditoria" subtitle="Alterações no banco de dados e ações administrativas.">
        <button className="btn" disabled={list.loading || Boolean(list.error) || !report.rows.length} onClick={() => exportExcel('auditoria', [report], reportHeader)}>Exportar para Excel</button>
        <button className="btn" disabled={list.loading || Boolean(list.error) || !report.rows.length} onClick={() => {
          if (!printReports(reportHeader, [report])) toast('error', 'Permita a abertura da janela para salvar o relatório em PDF.');
        }}>Salvar como PDF</button>
      </PageHeader>
      <form className="card stack audit-filters" onSubmit={(e) => {
        e.preventDefault();
        const { from, to, ...fields } = draft;
        const params = new URLSearchParams();
        Object.entries(fields).forEach(([key, value]) => { if (value.trim()) params.set(key, value.trim()); });
        if (from) params.set('date_from', from + 'T00:00:00-03:00');
        if (to) params.set('date_to', new Date(Date.parse(to + 'T00:00:00-03:00') + 86400000).toISOString());
        applyQuery(params.size ? '&' + params.toString() : '');
      }}>
        <div className="audit-filter-grid">
          <label className="field">Tabela<input maxLength={50} value={draft.table_name} onChange={(e) => setDraft({ ...draft, table_name: e.target.value })} /></label>
          <label className="field">ID do registro<input maxLength={50} value={draft.record_id} onChange={(e) => setDraft({ ...draft, record_id: e.target.value })} /></label>
          <label className="field">Ação<input maxLength={50} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} /></label>
          <label className="field">Origem<select value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
            <option value="">Todas</option>{Object.entries(AUDIT_SOURCE).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <DateFilter label="Data inicial" value={draft.from} max={draft.to} onChange={(from) => setDraft({ ...draft, from })} />
          <DateFilter label="Data final" value={draft.to} min={draft.from} onChange={(to) => setDraft({ ...draft, to })} />
        </div>
        <div className="row"><button className="btn primary">Filtrar</button><button className="btn" type="button" onClick={() => {
          setDraft(AUDIT_FILTERS); applyQuery('');
        }}>Limpar filtros</button></div>
      </form>
      <section className="card audit-events">
        <h2>Eventos de auditoria</h2>
        <DataTable rows={list.data} error={list.error?.message} cols={[
          ['Quando', (r) => <time className="audit-date" dateTime={String(r.occurred_at)}>{dateTime(String(r.occurred_at))}</time>],
          ['Evento', (r) => <div className="audit-cell"><strong>{String(r.action)}</strong>
            <span className="pill">{AUDIT_SOURCE[String(r.source)] ?? 'Outra'}</span></div>],
          ['Registro', (r) => <div className="audit-cell"><strong>{String(r.table_name || '—')}</strong>
            {r.record_id ? <code title={String(r.record_id)}>{String(r.record_id).slice(0, 8)}</code> : null}</div>],
          ['Ator', (r) => String(r.actor_username || 'Sistema')],
          ['Alterações', (r) => <div className="audit-cell">
            <span>{((r.changed_fields as string[]) || []).join(', ') || '—'}</span>
            {r.reason ? <span className="muted">{String(r.reason)}</span> : null}</div>],
          ['Detalhes', (r) => <button type="button" className="btn audit-details-button" onClick={() => {
            setCopied(false);
            setDetail({
              title: `${r.action} · ${r.table_name || '—'} · ${dateTime(String(r.occurred_at))}`,
              json: JSON.stringify({ antes: r.old_data, depois: r.new_data, ...((r.details as object) || {}) }, null, 2),
            });
          }}>Ver detalhes</button>],
        ]} />
      </section>
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
  'scheduled_mode_enabled', 'coupons_enabled', 'keyboard_mouse_enabled', 'controls_menu_enabled', 'public_streams_enabled', 'support_tickets_enabled', 'share_button_enabled', 'hold_minutes', 'setup_minutes',
  'scheduled_lead_minutes', 'queue_lead_minutes', 'booking_horizon_days', 'max_pending_holds_per_user', 'max_future_reservations_per_user',
  'cancel_full_refund_min_minutes_before', 'no_show_tolerance_minutes', 'featured_window_days', 'agent_heartbeat_timeout_seconds',
  'player_video_max_kbps']);

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
  const [ask, askDialog] = useAsk();
  const parse = (k: string, raw: string) => { const d = s.data!.defaults[k]; return typeof d === 'boolean' ? raw === 'true' : typeof d === 'number' ? Number(raw) : Array.isArray(d) ? raw.split(',').map((x) => Number(x.trim())) : raw; };
  return (
    <div className="stack">
      <PageHeader title="Configurações operacionais" subtitle="Alterações auditadas. Itens críticos exigem superadministrador." />
      {msg}
      <Alert kind="info"><span>Liga/desliga de funções, plataformas e regras de agenda ficam em <a className="link-purple" href="/admin/parametros">Parâmetros</a>. Aqui ficam os ajustes avançados.</span></Alert>
      <section className="card operational-settings"><h2>Configurações</h2><DataTable limit={5} error={s.error?.message} rows={s.data ? Object.entries(s.data.values).filter(([k]) => !IN_PARAMS.has(k)).map(([k, v]) => ({ id: k, k, v })) : null} cols={[['Chave', (r) => <span>{String(r.k)}{s.data!.critical.includes(String(r.k)) && <span className="pill amber" style={{ marginLeft: 6 }}>crítica</span>}</span>],
        ['O que é', (r) => <span className="small muted" style={{ display: 'block', maxWidth: 380 }}>{SETTING_HELP[String(r.k)] || 'Ajuste avançado do sistema.'}</span>],
        ['Valor', (r) => <input className="btn sm operational-setting-value" aria-label={String(r.k)} value={vals[String(r.k)] ?? (Array.isArray(r.v) ? (r.v as number[]).join(',') : String(r.v))} onChange={(e) => setVals({ ...vals, [String(r.k)]: e.target.value })} />],
        ['', (r) => <button className="btn sm" disabled={vals[String(r.k)] === undefined} onClick={async () => {
          const reason = await ask({ title: `Alterar "${String(r.k)}"?`, label: 'Motivo da alteração', minLength: 1, confirm: 'Salvar',
            message: <>Novo valor: <code>{vals[String(r.k)]}</code>. A alteração vale na hora e fica na auditoria.</> });
          if (reason !== null) run(async () => { await put(`/admin/settings/${r.k}`, { value: parse(String(r.k), vals[String(r.k)]), reason }); s.reload(); }, 'Configuração salva.');
        }}>Salvar</button>]]} /></section>
      {askDialog}
      <section className="card stack compact-policy-card"><h2>Políticas (termos, privacidade, cancelamento)</h2>
        <div className="grid3"><Field label="Tipo"><select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })}><option value="terms">Termos</option><option value="privacy">Privacidade</option><option value="cancellation">Cancelamento</option></select></Field>
          <Field label="Versão"><input maxLength={20} value={p.version} onChange={(e) => setP({ ...p, version: e.target.value })} /></Field><Field label="Título"><input maxLength={200} value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} /></Field></div>
        <Field label="Texto"><textarea maxLength={50000} style={{ minHeight: 108 }} value={p.body} onChange={(e) => setP({ ...p, body: e.target.value })} /></Field>
        <button className="btn primary" onClick={() => run(async () => { await post('/admin/policies', p); pol.reload(); }, 'Nova versão publicada.')}>Publicar nova versão</button>
        <DataTable limit={5} rows={pol.data} error={pol.error?.message} cols={[['Tipo', (r) => String(r.kind)], ['Versão', (r) => String(r.version)], ['Atual', (r) => (r.is_current ? 'sim' : 'não')], ['Publicada', (r) => dateTime(r.published_at as string)]]} /></section>
    </div>
  );
}
