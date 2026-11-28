'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Alert, Field, PageHeader, StatusPill } from '@/components/ui';
import { post } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { useAuth } from '@/lib/auth';
import { useAction } from './common';

type Window = { id: string; status: string; starts_at: string; ends_at: string; title: string; game_status: string; slug: string;
  cover_url: string | null; banner_url: string | null; short_description: string; age_rating: string | null; min_minutes: number; max_minutes: number };
type Conn = { method?: string; network_route?: string; console_identifier?: string | null; resolution?: string; fps?: number; bitrate_kbps?: number;
  standby_after_session?: boolean; keep_awake_minutes?: number };
type Hour = { weekday: number; opens_at: string; closes_at: string };
const DAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const PSN_STATUS: Record<string, string> = { pending: 'login Sony pendente (feito após a aprovação)', linked: 'conectada', expired: 'expirada', error: 'com erro', disabled: 'desativada' };
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

function ReviewCard({ r, agents, onDone, superadmin }: { r: Review; agents: { id: string; name: string }[]; onDone: () => void; superadmin: boolean }) {
  const [agent, setAgent] = useState(r.agent_id || '');
  const [notes, setNotes] = useState('');
  const { run, msg, busy } = useAction();
  const draftGames = r.windows.filter((w) => w.game_status !== 'published');
  return (
    <section className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>{r.name} <span className="small muted">({r.code} · {r.platform_code})</span></h2>
        <StatusPill status={r.status} map={REVIEW_STATUS} /></div>
      {msg}
      <dl className="kv small">
        <dt>Proprietário</dt><dd>{r.owner_name ? `${r.owner_name} · ` : ''}{r.owner_username} · {r.owner_email}</dd>
        <dt>Tipo</dt><dd>{r.approved_at ? `Alterações de console aprovado (no ar: ${r.is_published ? 'sim' : 'não'})` : 'Console novo'}</dd>
        <dt>Enviado em</dt><dd>{r.submitted_at ? dateTime(r.submitted_at) : '—'}</dd>
        <dt>Modelo / local</dt><dd>{[r.model, r.location].filter(Boolean).join(' · ') || '—'}</dd>
        <dt>Conta PSN</dt><dd>{r.psn_label ? `${r.psn_label}${r.psn_online_id ? ` (${r.psn_online_id})` : ''} · ${PSN_STATUS[r.psn_status ?? ''] ?? r.psn_status}` : '—'}</dd>
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
          <div className="small"><b>{w.title}</b> {w.status === 'pending_review' && <span className="pill amber">novo</span>}
            {w.game_status !== 'published' && <span className="pill red">jogo em rascunho</span>}
            <br />{dateTime(w.starts_at)} – {dateTime(w.ends_at)}
            <br /><span className="muted">{w.short_description || 'Sem descrição'} · {w.age_rating ? `Classificação ${w.age_rating}` : 'sem classificação'} · {w.min_minutes}–{w.max_minutes} min</span>
            {w.banner_url && <><br /><a className="link-purple" href={w.banner_url} target="_blank" rel="noreferrer">Ver banner</a></>}</div>
        </div>)}</div> : <p className="small muted">Nenhum período.</p>}
      {draftGames.length > 0 && <Alert kind="warn">Há jogo proposto pelo proprietário ainda em rascunho: revise as artes, a licença comercial e publique em{' '}
        <Link className="link-purple" href="/admin/jogos">Jogos</Link>. Só vende depois de publicado.</Alert>}
      <div className="grid2">
        <Field label="Agente que vai controlar o console" hint="A aprovação vincula o console e a conta PSN a este agente."><select value={agent} onChange={(e) => setAgent(e.target.value)} disabled={!superadmin}>
          <option value="">Selecione</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        <Field label="Motivo da recusa / observações" hint="Obrigatório para recusar: o proprietário vê este texto para corrigir e reenviar."><textarea maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      {r.status === 'changes_pending' && <p className="small muted">O proprietário ainda está editando; aprove depois que ele reenviar.</p>}
      <div className="row">
        <button className="btn primary" disabled={busy || !superadmin || r.status !== 'submitted' || !agent}
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
  const agents = useApi<{ id: string; name: string }[]>('/admin/agents').data || [];
  const { me } = useAuth();
  const superadmin = !!me?.roles.includes('superadmin');
  return (
    <div className="stack">
      <PageHeader title="Aprovação de consoles" subtitle="O proprietário configura tudo. Aqui a equipe apenas confere, vincula o agente e aprova a conta PSN — ou recusa explicando o motivo." />
      {list.error && <Alert kind="error">{list.error.message}</Alert>}
      {list.data?.length === 0 && <section className="card"><p className="muted" style={{ margin: 0 }}>Nenhum console aguardando análise.</p></section>}
      {list.data?.map((r) => <ReviewCard key={r.id} r={r} agents={agents} superadmin={superadmin} onDone={list.reload} />)}
    </div>
  );
}
