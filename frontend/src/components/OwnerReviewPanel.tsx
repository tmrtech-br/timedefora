'use client';
import { useEffect, useState } from 'react';
import { CONSOLE_TESTS, ProgressModal } from '@/components/admin/ProgressModal';
import { Alert, Modal, StatusPill } from '@/components/ui';
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
  changes_pending: 'Alterações não enviadas', rejected: 'Ajustes solicitados', in_progress: 'Em andamento' };
const RES_STATUS: Record<string, string> = { confirmed: 'Na fila', active: 'Jogando', completed: 'Concluída', no_show: 'Ausência',
  cancelled: 'Cancelada', needs_resolution: 'Em resolução', refunded: 'Reembolsada' };

type DiagState = { run: { id: string; status: string; results: { test_type: string; result: string; message: string; in_progress?: boolean; blocked_by?: string }[]; error: string | null; finished_at: string | null; can_cancel?: boolean } | null;
  validation: { validated_at: string | null; video_validated_at: string | null; audio_validated_at: string | null; control_validated_at: string | null;
    heartbeat_validated_at: string | null; connection_status: string; method: string; network_route?: string } | null };
const TEST_LABEL: Record<string, string> = { discover: 'Encontrar o console', pair: 'Pareamento', psn_auth: 'Conta PSN', connection: 'Conexão',
  video_audio: 'Imagem e áudio', controls: 'Controles', heartbeat: 'Agente', latency: 'Latência' };
const RESULT_LABEL: Record<string, string> = { passed: '✓ Aprovado', failed: '✗ Falhou', not_available: '— Não se aplica' };

/** Testes e diagnóstico do console (liberados depois da aprovação). A publicação só é liberada com todos aprovados. */
function Diagnostics({ consoleId, onValidated }: { consoleId: string; onValidated: () => void }) {
  const path = `/owner/consoles/${consoleId}/diagnostics`;
  const diag = useApi<DiagState>(path, 1500);
  const { run, msg, busy } = useAction();
  const d = diag.data;
  const activeRun = d?.run && ['queued', 'running', 'cancelling'].includes(d.run.status) ? d.run : null;
  const v = d?.validation;
  const tests = CONSOLE_TESTS.filter(([id]) => id !== 'psn_auth' || v?.network_route === 'internet_psn' || activeRun?.results.some((result) => result.test_type === id));
  const currentTest = tests.find(([id]) => !activeRun?.results.some((result) => result.test_type === id))?.[0];
  // Só quando o console passa a ficar validado (não a cada renderização).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (v?.validated_at) onValidated(); }, [v?.validated_at]);
  return <div className="stack owner-diagnostics">
    <h3 style={{ margin: 0 }}>Testes e diagnóstico</h3>
    {msg}
    {v?.validated_at ? <Alert kind="ok">Todos os testes aprovados em {dateTime(v.validated_at)}. O console pode ser publicado.</Alert>
      : <p className="small muted" style={{ margin: 0 }}>Deixe o console ligado (ou em repouso com Remote Play ativado) e a conta PSN conectada.
        O teste aplica a configuração, aguarda a conexão e confere imagem, áudio, controles e o agente. Pela PSN pode levar alguns minutos.</p>}
    <div><button className="btn primary" disabled={busy || !!activeRun} onClick={() => run(async () => {
      await post(path); await diag.reload();
    })}>{activeRun ? 'Testando…' : v?.validated_at ? 'Testar de novo' : 'Aplicar configuração e testar'}</button></div>
    {activeRun && <ProgressModal
      status={activeRun.status === 'cancelling' ? 'Cancelando diagnóstico…' : activeRun.status === 'running'
        ? currentTest === 'connection' && v?.network_route === 'internet_psn' ? 'Aguardando a conexão com o console pela PSN. Isso pode levar alguns minutos.' : 'Executando diagnóstico…'
        : 'Na fila de diagnósticos.'}
      error={diag.error?.message}
      tests={tests.map(([id, label]) => {
        const result = activeRun.results.find((item) => item.test_type === id);
        return { id, label, state: result ? (result.blocked_by ? 'Não executado' : RESULT_LABEL[result.result] ?? result.result) :
          activeRun.status === 'running' && id === currentTest ? 'Em execução' : 'Na fila' };
      })}
      onCancel={activeRun.can_cancel === false ? undefined : () => {
        if (busy || activeRun.status === 'cancelling') return;
        void run(async () => {
          await post(`${path}/${activeRun.id}/cancel`);
          await diag.reload();
        });
      }} />}
    {d?.run && !activeRun && <ul className="small owner-tests">{d.run.results.map((t) => <li key={t.test_type} className={t.result}>
      <b>{TEST_LABEL[t.test_type] ?? t.test_type}</b>: {t.blocked_by ? 'Não executado' : t.in_progress ? 'Conexão ainda em tentativa' : RESULT_LABEL[t.result] ?? t.result}
      {t.result !== 'passed' && t.message ? ` — ${t.message}` : ''}</li>)}
      {d.run.status === 'cancelled' && <li>Diagnóstico cancelado.</li>}
      {d.run.error && <li className="failed">{d.run.error}</li>}</ul>}
  </div>;
}

/** Situação da validação do console pela equipe + ações do proprietário + filas/sessões que o console teve. */
export default function OwnerReviewPanel({ consoleId, onChange, phase }: {
  consoleId: string; onChange: () => void; phase: 'review' | 'test';
}) {
  const review = useApi<Review>(`/owner/consoles/${consoleId}/review`, 15000);
  const { run, msg, busy } = useAction();
  const r = review.data;
  const [showNotes, setShowNotes] = useState(false);
  const diag = useApi<DiagState>(phase !== 'review' && r?.approved_at ? `/owner/consoles/${consoleId}/diagnostics` : null, 15000);
  const validated = !!diag.data?.validation?.validated_at;
  const pendingWindows = !!r?.pending_windows.length;
  const cardStatus = r?.status === 'approved' && (!validated || !r.is_published) ? 'in_progress' : r?.status;
  const act = (path: string, ok: string) => run(async () => { await post(`/owner/consoles/${consoleId}/${path}`); review.reload(); onChange(); }, ok);
  return <section className="card stack" id="validacao">
    <div className="spread"><h2 style={{ margin: 0 }}>{phase === 'review' ? 'Envio para aprovação' : 'Validação e publicação'}</h2><div className="row">
      {cardStatus && <StatusPill status={cardStatus} map={STATUS} />}
      <button className="btn sm" disabled={busy} onClick={() => void run(async () => {
        await Promise.all([review.reload(), diag.reload()]); onChange();
      }, 'Status atualizado.')}>Atualizar status</button>
    </div></div>
    {msg}{review.error && <Alert kind="error">{review.error.message}</Alert>}
    {r && <>
      {phase === 'review' && r.status === 'submitted' && <p className="small muted">O cadastro foi enviado. A aba Teste será liberada após a aprovação da equipe.</p>}
      {phase === 'review' && r.status === 'approved' && <p className="small muted">Cadastro aprovado. Abra a aba Teste para validar o console.</p>}
      {r.notes && r.status === 'rejected' && <div className="row">
        <button className="btn" onClick={() => setShowNotes(true)}>Ver motivo da recusa</button>
        {showNotes && <Modal title="Ajustes solicitados pela equipe" onClose={() => setShowNotes(false)} allowEscape>
          <p style={{ whiteSpace: 'pre-wrap' }}>{r.notes}</p>
          <p className="small muted">Depois de corrigir, clique em “Enviar para análise”.</p>
        </Modal>}
      </div>}
      {r.notes && !['rejected', 'approved'].includes(r.status) && <p className="small muted">Observações da equipe: {r.notes}</p>}
      {r.status === 'changes_pending' && <p className="small muted">{pendingWindows
        ? 'O jogo já está vinculado. Clique em “Enviar para análise” para a equipe aprovar o período.'
        : 'Clique em “Enviar para análise” para a equipe validar as alterações.'}</p>}
      {r.status === 'submitted' && pendingWindows && <p className="small muted">O jogo já está vinculado. Aguarde a aprovação do período pela equipe.</p>}
      {(r.pending.rate || r.pending_windows.length > 0) && <div className="small">
        <b>Aguardando validação:</b>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {r.pending.rate && <li>Nova tarifa: {money(r.pending.rate.rate_cents)} por {r.pending.rate.rate_unit === 'hour' ? 'hora' : 'minuto'}
            ({r.pending.rate.min_minutes} a {r.pending.rate.max_minutes} min)</li>}
          {r.pending_windows.map((w) => <li key={w.id}>{w.title}: {dateTime(w.starts_at)} – {dateTime(w.ends_at)}</li>)}
        </ul></div>}
      {r.missing.length > 0 && ['draft', 'rejected', 'changes_pending'].includes(r.status) && <div className="small muted">
        Pendências para enviar <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{r.missing.map((m) => <li key={m}>{m}</li>)}</ul></div>}
      <div className="row">
        {phase !== 'test' && ['draft', 'rejected', 'changes_pending'].includes(r.status) && <button className="btn primary" disabled={busy || r.missing.length > 0}
          onClick={() => act('submit', 'Enviado para análise. A equipe foi avisada.')}>Enviar para análise</button>}
        {phase !== 'test' && r.status === 'submitted' && <button className="btn" disabled={busy} onClick={() => act('withdraw', 'Envio cancelado: você pode editar de novo.')}>Cancelar envio para editar</button>}
        {phase !== 'review' && r.approved_at && !r.is_published && <button className="btn primary" disabled={busy || !validated || pendingWindows} title={pendingWindows ? 'O período do jogo aguarda aprovação' : validated ? undefined : 'Rode os testes e o diagnóstico primeiro'}
          onClick={() => act('publish', 'Console publicado para aluguel.')}>Publicar para aluguel</button>}
        {phase !== 'review' && r.is_published && <button className="btn" disabled={busy} onClick={() => act('unpublish', 'Console fora do ar para novas reservas.')}>Tirar do ar</button>}
      </div>
      {phase !== 'review' && r.approved_at && <Diagnostics key={consoleId} consoleId={consoleId} onValidated={() => { review.reload(); diag.reload(); onChange(); }} />}
    </>}
  </section>;
}

export function OwnerConsoleHistory({ consoleId }: { consoleId: string }) {
  const history = useApi<HistoryRow[]>(`/owner/consoles/${consoleId}/history`);
  return <details className="card"><summary>Filas e sessões deste console</summary>
    <DataTable limit={8} rows={history.data} error={history.error?.message} empty="Este console ainda não teve reservas."
      cols={[['Reserva', (h) => h.code], ['Jogo', (h) => h.game], ['Jogador', (h) => h.player], ['Início', (h) => dateTime(h.starts_at)],
        ['Tempo', (h) => `${h.minutes} min${h.seconds_used ? ` (usou ${duration(h.seconds_used)})` : ''}`],
        ['Situação', (h) => RES_STATUS[h.status] ?? h.status], ['Valor', (h) => money(h.total_cents)]]} />
  </details>;
}
