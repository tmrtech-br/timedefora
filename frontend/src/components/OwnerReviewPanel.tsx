'use client';
import { useEffect } from 'react';
import { Alert, StatusPill } from '@/components/ui';
import { post } from '@/lib/api';
import { dateTime, duration, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { DataTable, useAction } from '@/components/admin/common';

type Review = {
  status: 'draft' | 'submitted' | 'approved' | 'changes_pending' | 'rejected'; notes: string; submitted_at: string | null;
  reviewed_at: string | null; approved_at: string | null; is_published: boolean; agent_linked: boolean;
  pending: { rate?: { rate_cents: number; rate_unit: string; min_minutes: number; max_minutes: number } };
  missing: string[]; pending_windows: { id: string; title: string; starts_at: string; ends_at: string }[];
};
type HistoryRow = { code: string; status: string; mode: string; minutes: number; starts_at: string; ends_at: string; total_cents: number;
  game: string; player: string; seconds_used: number | null; end_reason: string | null; first_connected_at: string | null };
const STATUS: Record<string, string> = { draft: 'Rascunho', submitted: 'Em análise pela equipe', approved: 'Aprovado',
  changes_pending: 'Alterações não enviadas', rejected: 'Ajustes solicitados' };
const RES_STATUS: Record<string, string> = { confirmed: 'Na fila', active: 'Jogando', completed: 'Concluída', no_show: 'Ausência',
  cancelled: 'Cancelada', needs_resolution: 'Em resolução', refunded: 'Reembolsada' };

type DiagState = { run: { id: string; status: string; results: { test_type: string; result: string; message: string }[]; error: string | null; finished_at: string | null } | null;
  validation: { validated_at: string | null; video_validated_at: string | null; audio_validated_at: string | null; control_validated_at: string | null;
    heartbeat_validated_at: string | null; connection_status: string; method: string } | null };
const TEST_LABEL: Record<string, string> = { discover: 'Encontrar o console', pair: 'Pareamento', psn_auth: 'Conta PSN', connection: 'Conexão',
  video_audio: 'Imagem e áudio', controls: 'Controles', heartbeat: 'Agente', latency: 'Latência' };
const RESULT_LABEL: Record<string, string> = { passed: '✓ Aprovado', failed: '✗ Falhou', not_available: '— Não se aplica' };

/** Testes e diagnóstico do console (liberados depois da aprovação). A publicação só é liberada com todos aprovados. */
function Diagnostics({ consoleId, onValidated }: { consoleId: string; onValidated: () => void }) {
  const diag = useApi<DiagState>(`/owner/consoles/${consoleId}/diagnostics`, 5000);
  const { run, msg, busy } = useAction();
  const d = diag.data;
  const running = !!d?.run && ['queued', 'running', 'cancelling'].includes(d.run.status);
  const v = d?.validation;
  // Só quando o console passa a ficar validado (não a cada renderização).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (v?.validated_at) onValidated(); }, [v?.validated_at]);
  return <div className="stack owner-diagnostics">
    <h3 style={{ margin: 0 }}>Testes e diagnóstico</h3>
    {msg}
    {v?.validated_at ? <Alert kind="ok">Todos os testes aprovados em {dateTime(v.validated_at)}. O console pode ser publicado.</Alert>
      : <p className="small muted" style={{ margin: 0 }}>Deixe o console ligado (ou em repouso com Remote Play ativado) e a conta PSN conectada.
        O teste aplica a sua configuração de conexão, acorda o console e confere imagem, áudio, controles e o agente (leva 1 a 3 minutos).</p>}
    <div><button className="btn primary" disabled={busy || running} onClick={() => run(async () => {
      await post(`/owner/consoles/${consoleId}/diagnostics`); diag.reload();
    }, 'Testes iniciados. Acompanhe abaixo.')}>{running ? 'Testando…' : v?.validated_at ? 'Testar de novo' : 'Aplicar configuração e testar'}</button></div>
    {d?.run && <ul className="small owner-tests">{d.run.results.map((t) => <li key={t.test_type} className={t.result}>
      <b>{TEST_LABEL[t.test_type] ?? t.test_type}</b>: {RESULT_LABEL[t.result] ?? t.result}{t.result === 'failed' && t.message ? ` — ${t.message}` : ''}</li>)}
      {running && <li>Em andamento…</li>}
      {d.run.error && <li className="failed">{d.run.error}</li>}</ul>}
  </div>;
}

/** Situação da validação do console pela equipe + ações do proprietário + filas/sessões que o console teve. */
export default function OwnerReviewPanel({ consoleId, onChange }: { consoleId: string; onChange: () => void }) {
  const review = useApi<Review>(`/owner/consoles/${consoleId}/review`);
  const history = useApi<HistoryRow[]>(`/owner/consoles/${consoleId}/history`, 30000);
  const { run, msg, busy } = useAction();
  const r = review.data;
  const diag = useApi<DiagState>(r?.approved_at ? `/owner/consoles/${consoleId}/diagnostics` : null, 15000);
  const validated = !!diag.data?.validation?.validated_at;
  const act = (path: string, ok: string) => run(async () => { await post(`/owner/consoles/${consoleId}/${path}`); review.reload(); onChange(); }, ok);
  return <section className="card stack" id="validacao">
    <div className="spread"><h2 style={{ margin: 0 }}>Validação e publicação</h2>{r && <StatusPill status={r.status} map={STATUS} />}</div>
    {msg}{review.error && <Alert kind="error">{review.error.message}</Alert>}
    {r && <>
      <ol className="small owner-steps">
        <li className={r.status !== 'draft' && r.status !== 'rejected' ? 'done' : ''}>Cadastre o console, a conexão e transmissão, a conta PSN, os jogos com artes e períodos, o preço e os horários.</li>
        <li className={r.approved_at ? 'done' : r.status === 'submitted' ? 'now' : ''}>Envie para análise: a equipe confere e vincula o console e a conta PSN ao agente.</li>
        <li className={validated ? 'done' : r.approved_at ? 'now' : ''}>Faça o login Sony da conta PSN, aplique a configuração e rode os testes e o diagnóstico.</li>
        <li className={r.is_published ? 'done' : validated ? 'now' : ''}>Com os testes aprovados, publique o console para aluguel.</li>
      </ol>
      {r.notes && r.status !== 'approved' && <Alert kind="warn">Observações da equipe: {r.notes}</Alert>}
      {r.status === 'changes_pending' && <Alert kind="info">Você alterou um console aprovado. Ele <b>continua no ar com a versão aprovada</b>;
        as mudanças valem depois que a equipe validar. Envie para análise quando terminar.</Alert>}
      {(r.pending.rate || r.pending_windows.length > 0) && <div className="small">
        <b>Aguardando validação:</b>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {r.pending.rate && <li>Nova tarifa: {money(r.pending.rate.rate_cents)} por {r.pending.rate.rate_unit === 'hour' ? 'hora' : 'minuto'}
            ({r.pending.rate.min_minutes} a {r.pending.rate.max_minutes} min)</li>}
          {r.pending_windows.map((w) => <li key={w.id}>{w.title}: {dateTime(w.starts_at)} – {dateTime(w.ends_at)}</li>)}
        </ul></div>}
      {r.missing.length > 0 && ['draft', 'rejected', 'changes_pending'].includes(r.status) && <Alert kind="info">
        Para enviar falta: <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{r.missing.map((m) => <li key={m}>{m}</li>)}</ul></Alert>}
      <div className="row">
        {['draft', 'rejected', 'changes_pending'].includes(r.status) && <button className="btn primary" disabled={busy || r.missing.length > 0}
          onClick={() => act('submit', 'Enviado para análise. A equipe foi avisada.')}>Enviar para análise</button>}
        {r.status === 'submitted' && <button className="btn" disabled={busy} onClick={() => act('withdraw', 'Envio cancelado: você pode editar de novo.')}>Cancelar envio para editar</button>}
        {r.approved_at && !r.is_published && <button className="btn primary" disabled={busy || !validated} title={validated ? undefined : 'Rode os testes e o diagnóstico primeiro'}
          onClick={() => act('publish', 'Console publicado para aluguel.')}>Publicar para aluguel</button>}
        {r.is_published && <button className="btn" disabled={busy} onClick={() => act('unpublish', 'Console fora do ar para novas reservas.')}>Tirar do ar</button>}
      </div>
      {r.approved_at && <Diagnostics consoleId={consoleId} onValidated={() => { review.reload(); onChange(); }} />}
    </>}
    <h3 style={{ margin: '8px 0 0' }}>Filas e sessões deste console</h3>
    <DataTable limit={8} rows={history.data} error={history.error?.message} empty="Este console ainda não teve reservas."
      cols={[['Reserva', (h) => h.code], ['Jogo', (h) => h.game], ['Jogador', (h) => h.player], ['Início', (h) => dateTime(h.starts_at)],
        ['Tempo', (h) => `${h.minutes} min${h.seconds_used ? ` (usou ${duration(h.seconds_used)})` : ''}`],
        ['Situação', (h) => RES_STATUS[h.status] ?? h.status], ['Valor', (h) => money(h.total_cents)]]} />
  </section>;
}
