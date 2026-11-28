'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Alert, Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { useAuth } from '@/lib/auth';
import { useAction } from './common';
import { GameSummary, type Game } from './Games';
import LimitedScroll from '@/components/LimitedScroll';

type Window = { id: string; game_id: string; status: string; starts_at: string; ends_at: string; title: string; game_status: string; slug: string;
  cover_url: string | null; banner_url: string | null; short_description: string; age_rating: string | null; min_minutes: number; max_minutes: number };
type Conn = { method?: string; network_route?: string; console_identifier?: string | null; resolution?: string; fps?: number; bitrate_kbps?: number;
  standby_after_session?: boolean; keep_awake_minutes?: number };
type Hour = { weekday: number; opens_at: string; closes_at: string };
const DAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const PSN_STATUS: Record<string, string> = { pending: 'login Sony pendente — o proprietário ainda não conectou', linked: 'conectada', expired: 'expirada', error: 'com erro', disabled: 'desativada' };
type Review = {
  id: string; code: string; name: string; model: string; location: string; description: string; is_published: boolean; platform_code: string;
  status: 'submitted' | 'changes_pending'; notes: string; submitted_at: string | null; approved_at: string | null;
  pending: { rate?: { min_minutes: number; max_minutes: number; rate_unit: string; rate_cents: number }; connection?: Conn; hours?: Hour[] };
  owner_name: string | null; psn_status: string | null; current_method: string | null; current_route: string | null; current_resolution: string | null;
  current_fps: number | null; current_bitrate: number | null; validated_at: string | null; hours: Hour[];
  agent_id: string | null; agent_name: string | null; owner_username: string; owner_email: string;
  psn_label: string | null; psn_online_id: string | null;
  min_minutes: number | null; max_minutes: number | null; rate_unit: string | null; rate_cents: number | null; windows: Window[];
};
const REVIEW_STATUS: Record<string, string> = { submitted: 'Em análise', changes_pending: 'Proprietário editando' };
const rateText = (r: { min_minutes: number | null; max_minutes: number | null; rate_unit: string | null; rate_cents: number | null }) =>
  r.rate_cents == null ? '—' : `${money(r.rate_cents)} por ${r.rate_unit === 'hour' ? 'hora' : 'minuto'} · ${r.min_minutes} a ${r.max_minutes} min`;

function GameReview({ id, title, onClose, onPublished }: { id: string; title: string; onClose: () => void; onPublished: () => void }) {
  const game = useApi<Game>(`/admin/games/${id}`);
  const { run, msg, busy } = useAction();
  return <Modal title={`Cadastro de ${title}`} onClose={onClose} allowEscape>
    <div className="stack">
      {msg}
      {game.error && <p className="small err" role="alert">{game.error.message}</p>}
      {game.data && <><GameSummary game={game.data} />
        {game.data.status !== 'published' && <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run(async () => {
            await patch(`/admin/games/${id}`, { status: 'published' });
            await game.reload(); onPublished();
          }, 'Jogo publicado.')}>Publicar jogo</button>
          <Link className="btn" href={`/admin/jogos?jogo=${id}`}>Editar cadastro e licença</Link>
        </div>}</>}
    </div>
  </Modal>;
}

function ReviewCard({ r, agents, onDone, superadmin }: { r: Review; agents: { id: string; name: string }[]; onDone: () => void; superadmin: boolean }) {
  const [agent, setAgent] = useState(r.agent_id || '');
  const [notes, setNotes] = useState('');
  const [viewing, setViewing] = useState<Window | null>(null);
  const { run, msg, busy } = useAction();
  const draftGames = r.windows.filter((w) => w.game_status !== 'published');
  const psnPending = ['PS4', 'PS5'].includes(r.platform_code) && r.psn_status !== 'linked';
  return (
    <section className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>{r.name} <span className="small muted">({r.code} · {r.platform_code})</span></h2>
        <StatusPill status={r.status} map={REVIEW_STATUS} /></div>
      {msg}
      {viewing && <GameReview id={viewing.game_id} title={viewing.title} onClose={() => setViewing(null)} onPublished={onDone} />}
      <dl className="kv small">
        <dt>Proprietário</dt><dd>{r.owner_name ? `${r.owner_name} · ` : ''}{r.owner_username} · {r.owner_email}</dd>
        <dt>Tipo</dt><dd>{r.approved_at ? `Alterações de console aprovado (no ar: ${r.is_published ? 'sim' : 'não'})` : 'Console novo'}</dd>
        <dt>Enviado em</dt><dd>{r.submitted_at ? dateTime(r.submitted_at) : '—'}</dd>
        <dt>Modelo / local</dt><dd>{[r.model, r.location].filter(Boolean).join(' · ') || '—'}</dd>
        <dt>Conta PSN</dt><dd>{r.psn_label ? <span>{r.psn_label}{r.psn_online_id ? ` (${r.psn_online_id})` : ''} · <b style={{ color: r.psn_status === 'linked' ? 'var(--green, #16a34a)' : 'var(--amber, #d97706)' }}>{r.psn_status === 'linked' ? '✓ ' : ''}{PSN_STATUS[r.psn_status ?? ''] ?? r.psn_status}</b></span> : '—'}</dd>
        <dt>Tarifa atual</dt><dd>{rateText(r)}</dd>
        {r.pending.rate && <><dt>Tarifa pedida</dt><dd><b>{rateText(r.pending.rate)}</b></dd></>}
      </dl>
      <div className="grid2 review-details">
        <div><h3>Conexão e transmissão</h3>{(() => { const cn = r.pending.connection ?? (r.current_method && r.current_method !== 'unconfigured'
          ? { method: r.current_method, network_route: r.current_route ?? undefined, resolution: r.current_resolution ?? undefined, fps: r.current_fps ?? undefined, bitrate_kbps: r.current_bitrate ?? undefined } : null);
          return cn ? <dl className="kv small">
            <dt>Método</dt><dd>Remote Play {cn.network_route === 'internet_psn' ? 'pela internet (PSN)' : `(${cn.network_route})`}</dd>
            <dt>Identificação</dt><dd>{cn.console_identifier || '—'}</dd>
            <dt>Transmissão</dt><dd>{cn.resolution} · {cn.fps} fps · {cn.bitrate_kbps} kbps</dd>
            {cn.keep_awake_minutes != null && <><dt>Energia</dt><dd>{cn.standby_after_session ? 'Repouso quando ocioso' : 'Sempre ligado'} · mantém ligado {cn.keep_awake_minutes} min antes de reserva</dd></>}
            {r.pending.connection && r.approved_at && <><dt /><dd><span className="pill amber">alteração pedida</span></dd></>}
          </dl> : <p className="small muted">Não configurada.</p>; })()}</div>
        <div><h3>Dias e horários</h3>{(() => { const hs = r.pending.hours ?? r.hours;
          return hs.length ? <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{hs.map((h, i) => <li key={i}>{DAYS[h.weekday]}: {h.opens_at} às {h.closes_at}</li>)}
            {r.pending.hours && r.approved_at && <li><span className="pill amber">alteração pedida</span></li>}</ul>
            : <p className="small muted">Sem restrição de dia/horário (vale o período de cada jogo).</p>; })()}</div>
      </div>
      <h3 style={{ margin: 0 }}>Jogos e períodos</h3>
      {r.windows.length ? <div className="review-games">{r.windows.map((w) =>
        <div key={w.id} className="review-game">
          {w.cover_url ? <img src={w.cover_url} alt={`Capa de ${w.title}`} /> : <div className="review-noimg">sem capa</div>}
          <div className="small"><button className="link-purple review-game-link" onClick={() => setViewing(w)}>{w.title}</button> {w.status === 'pending_review' && <span className="pill amber">novo</span>}
            {w.game_status !== 'published' && <span className="pill amber">jogo pendente</span>}
            <br />{dateTime(w.starts_at)} – {dateTime(w.ends_at)}
            <br /><span className="muted">{w.short_description || 'Sem descrição'} · {w.age_rating ? `Classificação ${w.age_rating}` : 'sem classificação'} · {w.min_minutes}–{w.max_minutes} min</span>
            {w.banner_url && <><br /><a className="link-purple" href={w.banner_url} target="_blank" rel="noreferrer">Ver banner</a></>}</div>
        </div>)}</div> : <p className="small muted">Nenhum período.</p>}
      {draftGames.length > 0 && <p className="small muted">Abra o cadastro dos jogos pendentes para conferir as artes e a licença e publicar.</p>}
      {psnPending && <p className="small muted">O proprietário precisa concluir o login Sony para liberar a aprovação.</p>}
      <div className="grid2">
        <Field label="Agente que vai controlar o console" hint="A aprovação vincula o console e a conta PSN a este agente."><select value={agent} onChange={(e) => setAgent(e.target.value)} disabled={!superadmin}>
          <option value="">Selecione</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        <Field label="Motivo da recusa / observações" hint="Obrigatório para recusar: o proprietário vê este texto para corrigir e reenviar."><textarea maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      {r.status === 'changes_pending' && <p className="small muted">O proprietário ainda está editando; aprove depois que ele reenviar.</p>}
      <div className="row">
        <button className="btn primary" disabled={busy || !superadmin || r.status !== 'submitted' || !agent || !!draftGames.length || !r.windows.length || psnPending}
          onClick={() => run(async () => { await post(`/admin/owner-reviews/${r.id}/approve`, { agent_id: agent || null, notes }); onDone(); }, 'Console aprovado e agente vinculado.')}>
          Aprovar vínculo (agente + conta PSN)</button>
        <button className="btn danger" disabled={busy || notes.trim().length < 5}
          onClick={() => run(async () => { await post(`/admin/owner-reviews/${r.id}/reject`, { notes }); onDone(); }, 'Ajustes solicitados ao proprietário.')}>
          Recusar com motivo</button>
      </div>
      {!superadmin && <p className="small muted">Somente superadministradores aprovam e vinculam o agente.</p>}
    </section>
  );
}

export default function OwnerReviews() {
  const list = useApi<Review[]>('/admin/owner-reviews', 20000);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [opened, setOpened] = useState<string>();
  const agents = useApi<{ id: string; name: string }[]>('/admin/agents').data || [];
  const { me } = useAuth();
  const superadmin = !!me?.roles.includes('superadmin');
  const normalized = query.trim().toLocaleLowerCase('pt-BR');
  const rows = list.data?.filter((r) => (!status || r.status === status) && (!normalized
    || [r.name, r.code, r.owner_name, r.owner_username, r.owner_email].some((value) => value?.toLocaleLowerCase('pt-BR').includes(normalized))));
  const selected = list.data?.find((r) => r.id === opened);
  return (
    <div className="stack">
      <PageHeader title="Aprovação de consoles" subtitle="O proprietário configura tudo. Aqui a equipe apenas confere, vincula o agente e aprova a conta PSN — ou recusa explicando o motivo." />
      <section className="card stack">
        <div className="grid2">
          <Field label="Buscar cadastro"><input type="search" placeholder="Console, código ou proprietário" value={query} onChange={(e) => setQuery(e.target.value)} /></Field>
          <Field label="Situação"><select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todas</option>
            {Object.entries(REVIEW_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
        </div>
        <div className="row"><button className="btn" onClick={() => void list.reload()}>Atualizar status</button>
          {(status || query) && <button className="btn" onClick={() => { setQuery(''); setStatus(''); }}>Limpar filtros</button>}</div>
      </section>
      {list.error && <Alert kind="error">{list.error.message}</Alert>}
      {rows?.length === 0 && <section className="card"><p className="muted" style={{ margin: 0 }}>{status || normalized
        ? 'Nenhum cadastro corresponde aos filtros.' : 'Nenhum console aguardando análise.'}</p></section>}
      {!!rows?.length && <LimitedScroll label="Cadastros para aprovação" limit={5}>
        {rows.map((r) => <div key={r.id} className="card spread"><strong>{r.name}</strong>
          <button className="btn sm" aria-label={`Ver cadastro de ${r.name}`} onClick={() => setOpened(r.id)}>Ver</button></div>)}
      </LimitedScroll>}
      {selected && <Modal title="Análise do cadastro" onClose={() => setOpened(undefined)} allowEscape>
        <ReviewCard key={selected.id} r={selected} agents={agents} superadmin={superadmin} onDone={list.reload} />
      </Modal>}
    </div>
  );
}
