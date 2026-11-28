'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Alert, Field, PageHeader, StatusPill } from '@/components/ui';
import { post } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { useAuth } from '@/lib/auth';
import { useAction } from './common';
import OwnerPayouts from './OwnerPayouts';

type Window = { id: string; status: string; starts_at: string; ends_at: string; title: string; game_status: string; slug: string };
type Review = {
  id: string; code: string; name: string; model: string; location: string; description: string; is_published: boolean; platform_code: string;
  status: 'submitted' | 'changes_pending'; notes: string; submitted_at: string | null; approved_at: string | null;
  pending: { rate?: { min_minutes: number; max_minutes: number; rate_unit: string; rate_cents: number } };
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
        <dt>Proprietário</dt><dd>{r.owner_username} · {r.owner_email}</dd>
        <dt>Tipo</dt><dd>{r.approved_at ? `Alterações de console aprovado (no ar: ${r.is_published ? 'sim' : 'não'})` : 'Console novo'}</dd>
        <dt>Enviado em</dt><dd>{r.submitted_at ? dateTime(r.submitted_at) : '—'}</dd>
        <dt>Modelo / local</dt><dd>{[r.model, r.location].filter(Boolean).join(' · ') || '—'}</dd>
        <dt>Conta PSN</dt><dd>{r.psn_label ? `${r.psn_label}${r.psn_online_id ? ` (${r.psn_online_id})` : ''}` : '—'}</dd>
        <dt>Tarifa atual</dt><dd>{rateText(r)}</dd>
        {r.pending.rate && <><dt>Tarifa pedida</dt><dd><b>{rateText(r.pending.rate)}</b></dd></>}
      </dl>
      <h3 style={{ margin: 0 }}>Jogos e períodos</h3>
      {r.windows.length ? <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.windows.map((w) =>
        <li key={w.id}>{w.title}: {dateTime(w.starts_at)} – {dateTime(w.ends_at)} {w.status === 'pending_review' && <span className="pill amber">novo</span>}
          {w.game_status !== 'published' && <span className="pill red">jogo em rascunho</span>}</li>)}</ul> : <p className="small muted">Nenhum período.</p>}
      {draftGames.length > 0 && <Alert kind="warn">Há jogo proposto pelo proprietário ainda em rascunho: revise as artes, a licença comercial e publique em{' '}
        <Link className="link-purple" href="/admin/jogos">Jogos</Link>. Só vende depois de publicado.</Alert>}
      <div className="grid2">
        <Field label="Agente que vai controlar o console"><select value={agent} onChange={(e) => setAgent(e.target.value)} disabled={!superadmin}>
          <option value="">Selecione</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        <Field label="Observações ao proprietário" hint="Obrigatório para pedir ajustes."><textarea maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      {r.status === 'changes_pending' && <p className="small muted">O proprietário ainda está editando; aprove depois que ele reenviar.</p>}
      <div className="row">
        <button className="btn primary" disabled={busy || !superadmin || r.status !== 'submitted' || !agent}
          onClick={() => run(async () => { await post(`/admin/owner-reviews/${r.id}/approve`, { agent_id: agent || null, notes }); onDone(); }, 'Console aprovado e agente vinculado.')}>
          Aprovar e vincular agente</button>
        <button className="btn danger" disabled={busy || notes.trim().length < 5}
          onClick={() => run(async () => { await post(`/admin/owner-reviews/${r.id}/reject`, { notes }); onDone(); }, 'Ajustes solicitados ao proprietário.')}>
          Pedir ajustes</button>
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
      <PageHeader title="Proprietários: análise de consoles" subtitle="Valide o cadastro feito pelo proprietário, vincule o agente e libere a publicação. Edições de consoles aprovados também passam por aqui." />
      {list.error && <Alert kind="error">{list.error.message}</Alert>}
      {list.data?.length === 0 && <section className="card"><p className="muted" style={{ margin: 0 }}>Nenhum console aguardando análise.</p></section>}
      {list.data?.map((r) => <ReviewCard key={r.id} r={r} agents={agents} superadmin={superadmin} onDone={list.reload} />)}
      <OwnerPayouts />
    </div>
  );
}
