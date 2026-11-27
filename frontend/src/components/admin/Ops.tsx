'use client';
import LimitedScroll from '@/components/LimitedScroll';
import { useState } from 'react';
import { Empty, ErrorBox, Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { CANCEL_REQUEST_STATUS, dateTime, minutesLabel, money, QUEUE_STATUS, RESERVATION_STATUS, time } from '@/lib/format';
import { DataTable, fromLocalInput, need, NewRecord, useAction, useAsk, useDelete } from './common';

type R = Record<string, unknown>;
const INPUT_LABEL: Record<string, string> = { gamepad: 'Controle', keyboard_mouse: 'Teclado e mouse' };
const INCIDENT_LABEL: Record<string, string> = { console_failure: 'Falha de console', stream_failure: 'Falha de stream', platform_delay: 'Atraso da plataforma', agent_offline: 'Agente offline', other: 'Outro' };
const COMPENSATION: Record<string, { label: string; hint: string }> = {
  none: { label: 'Sem compensação', hint: 'O incidente é encerrado sem crédito ao cliente.' },
  extension: { label: 'Tempo extra', hint: 'Registre nas observações quantos minutos extras foram concedidos.' },
  reschedule: { label: 'Remarcação', hint: 'Registre nas observações a nova data/horário combinado com o cliente.' },
  refund: { label: 'Reembolso', hint: 'Se houver reserva vinculada com pagamento aprovado, o valor integral é reembolsado.' },
};
const PROVIDER_LABEL: Record<string, string> = { twitch: 'Twitch', kick: 'Kick', external: 'Link externo' };

export function Queues() {
  const { data, error, reload } = useApi<{ id: string; name: string; status: string; queue: R[] }[]>('/admin/queues', 5000);
  const [draft, setDraft] = useState({ console: '', player: '', status: '' });
  const [filters, setFilters] = useState(draft);
  const [expanded, setExpanded] = useState<string>();
  const player = filters.player.trim().toLocaleLowerCase('pt-BR');
  const matchesEntries = Boolean(player || filters.status);
  const consoles = data?.filter((c) => !filters.console || c.id === filters.console).map((c) => ({
    ...c,
    entries: c.queue.filter((r) => (!player || [r.username, r.code].some((v) => String(v ?? '').toLocaleLowerCase('pt-BR').includes(player)))
      && (!filters.status || r.status === filters.status)),
  })).filter((c) => !matchesEntries || c.entries.length > 0);
  return (
    <div className="stack">
      <PageHeader title="Filas" subtitle="Atualização automática a cada 5 segundos." />
      <form className="card stack audit-filters" onSubmit={(e) => { e.preventDefault(); setFilters(draft); setExpanded(undefined); }}>
        <div className="audit-filter-grid">
          <Field label="Console"><select value={draft.console} onChange={(e) => setDraft({ ...draft, console: e.target.value })}>
            <option value="">Todos</option>{data?.map((c) => <option key={String(c.id)} value={String(c.id)}>{String(c.name)}</option>)}
          </select></Field>
          <Field label="Jogador ou reserva"><input type="search" value={draft.player} onChange={(e) => setDraft({ ...draft, player: e.target.value })} /></Field>
          <Field label="Situação"><select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
            <option value="">Todas</option>{Object.entries(QUEUE_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
        </div>
        <div className="row"><button className="btn primary">Filtrar</button><button type="button" className="btn" onClick={() => {
          const empty = { console: '', player: '', status: '' };
          setDraft(empty); setFilters(empty); setExpanded(undefined);
        }}>Limpar filtros</button></div>
      </form>
      <ErrorBox error={error} onRetry={reload} />
      {consoles && !consoles.length && <Empty>Nenhuma fila encontrada.</Empty>}
      <LimitedScroll label="Filas por console">
        {(consoles ?? []).map((c) => {
          const id = String(c.id);
          const open = expanded === id;
          return <section key={id} className="card queue-admin-card">
            <button type="button" className="queue-admin-toggle" aria-expanded={open} onClick={() => setExpanded(open ? undefined : id)}>
              <strong>{String(c.name)}</strong><span className="row"><StatusPill status={String(c.status)} />
                <span>{c.entries.length} na fila</span><span aria-hidden>{open ? '▾' : '▸'}</span></span>
            </button>
            {open && <DataTable limit={5} rows={c.entries} empty="Fila vazia." cols={[
              ['#', (r) => String(r.position)], ['Jogador', (r) => String(r.username)], ['Situação', (r) => QUEUE_STATUS[String(r.status)] ?? '—'],
              ['Previsão', (r) => `${time(String(r.estimated_start_at))}–${time(String(r.estimated_end_at))}`],
              ['Reserva', (r) => `${r.code} (${r.mode === 'queue' ? 'fila' : 'fixo'})`],
            ]} />}
          </section>;
        })}
      </LimitedScroll>
    </div>
  );
}

export function Reservations() {
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const list = useApi<R[]>(`/admin/reservations?status=${status}&q=${encodeURIComponent(q)}`, 15000);
  const crs = useApi<R[]>('/admin/cancellation-requests');
  const { run, msg } = useAction();
  const [ask, askDialog] = useAsk();
  const [resched, setResched] = useState<{ id: string; start: string; reason: string } | null>(null);
  return (
    <div className="stack">
      <PageHeader title="Reservas" subtitle="Cancelamentos e remarcações exigem justificativa e ficam auditados." />
      {msg}
      <div className="row"><select className="btn" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Todos os status</option>{Object.entries(RESERVATION_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input className="btn" placeholder="Código ou usuário" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <section className="card"><h2>Reservas</h2><DataTable rows={list.data} error={list.error?.message} cols={[['Código', (r) => String(r.code)], ['Jogador', (r) => String(r.username)], ['Jogo / console', (r) => `${r.game_title} · ${r.console_name}`],
        ['Período', (r) => `${dateTime(String(r.starts_at))}–${time(String(r.ends_at))}`], ['Total', (r) => money(Number(r.total_cents))], ['Status', (r) => <StatusPill status={String(r.status)} map={RESERVATION_STATUS} />],
        ['Ações', (r) => ['pending_payment', 'confirmed', 'active', 'needs_resolution'].includes(String(r.status)) ? <div className="row">
          <button className="btn sm danger" onClick={async () => {
            const reason = await ask({ title: `Cancelar a reserva ${r.code}?`, label: 'Justificativa', danger: true, confirm: 'Cancelar e reembolsar',
              message: <>O pagamento de <b>{String(r.username)}</b> será <b>reembolsado</b> e o horário liberado. A justificativa fica na auditoria.</> });
            if (reason) run(async () => { await post(`/admin/reservations/${r.id}/cancel`, { reason, refund: true }); list.reload(); }, 'Cancelada e reembolsada.');
          }}>Cancelar</button>
          {['confirmed', 'needs_resolution'].includes(String(r.status)) && <button className="btn sm" onClick={() => setResched({ id: String(r.id), start: '', reason: '' })}>Remarcar</button>}</div> : null]]} /></section>
      {resched && <Modal title="Remarcar reserva" onClose={() => setResched(null)}>
        <div className="stack">
          <Field label="Novo horário"><input type="datetime-local" value={resched.start} onChange={(e) => setResched({ ...resched, start: e.target.value })} /></Field>
          <Field label="Justificativa"><input value={resched.reason} onChange={(e) => setResched({ ...resched, reason: e.target.value })} /></Field>
          <div><button className="btn primary" onClick={() => run(async () => {
            await post(`/admin/reservations/${resched.id}/reschedule`, { start_at: fromLocalInput(resched.start), reason: resched.reason });
            setResched(null); list.reload();
          }, 'Remarcada.')}>Remarcar</button></div>
        </div>
      </Modal>}
      <section className="card"><h2>Solicitações de cancelamento</h2>
        <DataTable rows={crs.data} error={crs.error?.message} empty="Nenhuma solicitação." cols={[['Reserva', (r) => String(r.code)], ['Jogador', (r) => String(r.username)], ['Início', (r) => dateTime(String(r.starts_at))],
          ['Motivo', (r) => String(r.reason)], ['Status', (r) => <StatusPill status={String(r.status)} map={CANCEL_REQUEST_STATUS} tone={({ requested: 'amber', approved: 'green', denied: 'red' } as Record<string, string>)[String(r.status)]} />], ['', (r) => r.status === 'requested' ? <div className="row">
            <button className="btn sm primary" onClick={async () => {
              const notes = await ask({ title: `Aprovar o cancelamento de ${r.code}?`, label: 'Observação para o cliente', confirm: 'Aprovar e reembolsar',
                message: 'A reserva é cancelada com reembolso integral e o cliente é avisado.' });
              if (notes) run(async () => { await post(`/admin/cancellation-requests/${r.id}/decide`, { approve: true, notes }); crs.reload(); list.reload(); }, 'Aprovada.');
            }}>Aprovar</button>
            <button className="btn sm danger" onClick={async () => {
              const notes = await ask({ title: `Negar o cancelamento de ${r.code}?`, label: 'Motivo da negativa (o cliente verá)', danger: true, confirm: 'Negar' });
              if (notes) run(async () => { await post(`/admin/cancellation-requests/${r.id}/decide`, { approve: false, notes }); crs.reload(); }, 'Negada.');
            }}>Negar</button></div> : String(r.decision_notes || '')]]} /></section>
      {askDialog}
    </div>
  );
}

export function Sessions() {
  const s = useApi<R[]>('/admin/sessions', 5000);
  const inc = useApi<R[]>('/admin/incidents');
  const all = useApi<R[]>('/admin/incidents?open_only=false');
  const resolved = all.data ? all.data.filter((r) => r.resolved_at) : null;
  const { run, msg, busy } = useAction();
  const [ask, askDialog] = useAsk();
  const [i, setI] = useState({ description: '', kind: 'other', reservationId: '' });
  const [res, setRes] = useState<{ id: string; label: string; compensation: string; notes: string; ownerRental: boolean; fault: string; ownerCents: string } | null>(null);
  return (
    <div className="stack">
      <PageHeader title="Sessões ativas e incidentes" />
      {msg}
      <section className="card"><h2>Sessões ativas</h2><DataTable rows={s.data} error={s.error?.message} empty="Nenhuma sessão ativa." cols={[['Jogador', (r) => String(r.username)], ['Jogo / console', (r) => `${r.title} · ${r.console_name}`],
        ['Término', (r) => time(String(r.contract_ends_at))], ['Entrada', (r) => INPUT_LABEL[String(r.input_device)] || '—'], ['Método', (r) => String(r.adapter_method)],
        ['', (r) => <div className="row">
          <button className="btn sm danger" onClick={async () => {
            const reason = await ask({ title: `Encerrar a sessão de ${String(r.username)}?`, label: 'Justificativa do encerramento', danger: true, confirm: 'Encerrar sessão', minLength: 5,
              message: 'O controle é revogado na hora, sem compensação. Use "Falha → compensar" se o problema foi da plataforma.' });
            if (reason) run(async () => { await post(`/admin/sessions/${r.id}/terminate`, { reason, compensation: 'none' }); s.reload(); }, 'Sessão encerrada.');
          }}>Encerrar</button>
          <button className="btn sm" onClick={async () => {
            const reason = await ask({ title: 'Encerrar por falha operacional?', label: 'Descreva a falha', confirm: 'Encerrar e compensar', minLength: 5,
              message: 'A sessão é encerrada, um incidente é aberto e fica registrada compensação por reembolso ao cliente.' });
            if (reason) run(async () => { await post(`/admin/sessions/${r.id}/terminate`, { reason, compensation: 'refund' }); s.reload(); inc.reload(); }, 'Encerrada por falha; incidente aberto.');
          }}>Falha → compensar</button></div>]]} /></section>
      {askDialog}
      <section className="card stack"><h2>Incidentes</h2>
        <div className="row"><select className="btn" value={i.kind} onChange={(e) => setI({ ...i, kind: e.target.value })}><option value="console_failure">Falha de console</option><option value="stream_failure">Falha de stream</option><option value="agent_offline">Agente offline</option><option value="platform_delay">Atraso da plataforma</option><option value="other">Outro</option></select>
          <select className="btn" aria-label="Reserva afetada" value={i.reservationId} onChange={(e) => setI({ ...i, reservationId: e.target.value })}>
            <option value="">Sem reserva associada</option>
            {s.data?.map((item) => <option key={String(item.id)} value={String(item.reservation_id)}>{String(item.code)} · {String(item.console_name)}</option>)}
          </select>
          <input className="btn" style={{ flex: 1 }} placeholder="Descrição" value={i.description} onChange={(e) => setI({ ...i, description: e.target.value })} />
          <button className="btn" onClick={() => run(async () => {
            await post('/admin/incidents', { description: i.description, kind: i.kind, reservation_id: i.reservationId || null });
            inc.reload();
          }, 'Incidente registrado.')}>Registrar</button></div>
        <DataTable limit={5} rows={inc.data} error={inc.error?.message} empty="Nenhum incidente aberto." cols={[['Tipo', (r) => INCIDENT_LABEL[String(r.kind)] || String(r.kind)], ['Console', (r) => String(r.console_name || '—')], ['Descrição', (r) => String(r.description)],
          ['Desde', (r) => dateTime(String(r.started_at))], ['', (r) => <button className="btn sm" onClick={() => setRes({ id: String(r.id), label: String(r.description), compensation: 'none', notes: '', ownerRental: Boolean(r.owner_rental), fault: '', ownerCents: '' })}>Resolver</button>]]} />
      </section>
      <section className="card stack"><h2>Histórico de incidentes resolvidos</h2>
        <DataTable limit={5} rows={resolved} empty="Nenhum incidente resolvido ainda." cols={[
          ['Tipo', (r) => INCIDENT_LABEL[String(r.kind)] || String(r.kind)], ['Console', (r) => String(r.console_name || '—')],
          ['Descrição', (r) => <span className="small" style={{ display: 'block', maxWidth: 360 }}>{String(r.description)}</span>],
          ['Aberto em', (r) => dateTime(String(r.started_at))], ['Resolvido em', (r) => dateTime(String(r.resolved_at))],
          ['Duração', (r) => minutesLabel(Math.max(1, Math.round((new Date(String(r.resolved_at)).getTime() - new Date(String(r.started_at)).getTime()) / 60000)))],
          ['Compensação', (r) => <span className={`pill ${r.compensation === 'refund' ? 'amber' : r.compensation && r.compensation !== 'none' ? 'purple' : ''}`}>{COMPENSATION[String(r.compensation || 'none')]?.label || String(r.compensation)}</span>],
          ['Observações', (r) => <span className="small muted" style={{ display: 'block', maxWidth: 280 }}>{String(r.compensation_notes || '—')}</span>]]} />
      </section>
      {res && (
        <Modal title="Resolver incidente" onClose={() => setRes(null)}>
          <div className="stack">
            <p className="small muted" style={{ margin: 0 }}>{res.label}</p>
            {res.ownerRental && <Field label="Causa" required>
              <select value={res.fault} onChange={(e) => setRes({ ...res, fault: e.target.value })}>
                <option value="">Selecione</option><option value="renter">Locatário</option><option value="console">Proprietário ou console</option>
              </select>
            </Field>}
            {res.ownerRental && res.fault === 'console' && <Field label="Parcela aprovada em centavos" hint="Em branco, aplica a parcela definida na reserva.">
              <input type="number" min={0} step={1} value={res.ownerCents} onChange={(e) => setRes({ ...res, ownerCents: e.target.value })} />
            </Field>}
            {res.fault === 'renter' ? <p>O cliente recebe o estorno integral e o proprietário fica sem repasse.</p> : <>
            <Field label="Compensação ao cliente" required>
              <select value={res.compensation} onChange={(e) => setRes({ ...res, compensation: e.target.value })}>
                {Object.entries(COMPENSATION).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></Field>
            <p className="small dim" style={{ margin: 0 }}>{COMPENSATION[res.compensation].hint}</p></>}
            <Field label="Justificativa da decisão" required={res.ownerRental || res.compensation !== 'none'}>
              <textarea maxLength={1000} value={res.notes} onChange={(e) => setRes({ ...res, notes: e.target.value })} /></Field>
            <div className="row">
              <button className={`btn ${res.compensation === 'refund' ? 'danger' : 'primary'}`} disabled={busy} onClick={async () => {
                const ok = await run(async () => {
                  need(!res.ownerRental || res.fault, 'Informe a causa do incidente.');
                  need((!res.ownerRental && res.compensation === 'none') || res.notes.trim().length >= 5, 'Justifique a decisão (mínimo 5 caracteres).');
                  const result = await post<{ ok: boolean; message?: string }>(`/admin/incidents/${res.id}/resolve`, {
                    compensation: res.compensation, compensation_notes: res.notes.trim(),
                    owner_fault: res.fault || null,
                    owner_approved_cents: res.fault === 'console' && res.ownerCents ? Number(res.ownerCents) : null,
                  });
                  need(result.ok, result.message || 'O incidente permanece aberto.');
                  inc.reload(); all.reload(); return true;
                }, 'Incidente resolvido.');
                if (ok) setRes(null);
              }}>Resolver incidente</button>
              <button className="btn" onClick={() => setRes(null)}>Voltar</button>
            </div>
          </div>
        </Modal>)}
    </div>
  );
}

export function Channels() {
  const deletion = useDelete();
  const ch = useApi<R[]>('/admin/channels');
  const games = useApi<{ id: string; title: string }[]>('/admin/games').data;
  const consoles = useApi<{ id: string; name: string }[]>('/admin/consoles').data;
  const [f, setF] = useState({ provider: 'twitch', channel_name: '', external_url: '', console_id: '', game_id: '', privacy_mask_enabled: true });
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Transmissões públicas" subtitle="Somente espectadores. Nunca exiba credenciais, telas de compra/configuração ou dados pessoais." />
      {msg}
      {deletion.dialog}
      <NewRecord title="Nova transmissão">{(close) => <><div className="grid3">
        <Field label="Plataforma"><select value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })}><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="external">Link externo</option></select></Field>
        {f.provider === 'external' ? <Field label="URL https"><input maxLength={500} value={f.external_url} onChange={(e) => setF({ ...f, external_url: e.target.value })} /></Field>
          : <Field label="Nome do canal"><input value={f.channel_name} onChange={(e) => setF({ ...f, channel_name: e.target.value })} /></Field>}
        <Field label="Console"><select value={f.console_id} onChange={(e) => setF({ ...f, console_id: e.target.value })}><option value="">—</option>{consoles?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Jogo"><select value={f.game_id} onChange={(e) => setF({ ...f, game_id: e.target.value })}><option value="">—</option>{games?.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select></Field>
        <label className="check"><input type="checkbox" checked={f.privacy_mask_enabled} onChange={(e) => setF({ ...f, privacy_mask_enabled: e.target.checked })} />Máscara/corte de telas sensíveis ativo</label></div>
        <button className="btn primary" onClick={() => run(async () => { await post('/admin/channels', { ...f, console_id: f.console_id || null, game_id: f.game_id || null, channel_name: f.channel_name || null, external_url: f.external_url || null }); ch.reload(); close(); }, 'Canal cadastrado.')}>Cadastrar</button></>}</NewRecord>
      <section className="card"><h2>Transmissões</h2><DataTable limit={5} rows={ch.data} error={ch.error?.message} cols={[['Plataforma', (r) => PROVIDER_LABEL[String(r.provider)] || String(r.provider)], ['Canal', (r) => String(r.channel_name || r.external_url)], ['Console / jogo', (r) => [r.console_name, r.game_title].filter(Boolean).join(' · ')],
        ['Aparece no site?', (r) => { const issues = (r.issues as string[]) || []; const shown = (r.shown_on as string[]) || [];
          return issues.length ? <div className="stack" style={{ gap: 4 }}>{shown.length > 0 && <span className="pill amber">parcial: {shown.join(', ')}</span>}
            {!shown.length && <span className="pill red">não aparece</span>}<ul className="small" style={{ margin: 0, paddingLeft: 16 }}>{issues.map((x) => <li key={x}>{x}</li>)}</ul></div>
            : <span className="pill green">sim — {shown.join(', ')}</span>; }],
        ['Status', (r) => <select className="btn sm" value={String(r.status)} onChange={(e) => run(async () => { await patch(`/admin/channels/${r.id}`, { status: e.target.value }); ch.reload(); })}><option value="offline">offline</option><option value="live">ao vivo</option><option value="disabled">desativado</option></select>],
        ['', (r) => <button className="btn sm danger" onClick={() => deletion.remove(`/admin/channels/${r.id}`, 'Excluir canal?', (request) => run(async () => { await request(); ch.reload(); }, 'Removido.'))}>Excluir</button>]]} /></section>
    </div>
  );
}
