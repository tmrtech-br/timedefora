'use client';
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

/** Situação da validação do console pela equipe + ações do proprietário + filas/sessões que o console teve. */
export default function OwnerReviewPanel({ consoleId, onChange }: { consoleId: string; onChange: () => void }) {
  const review = useApi<Review>(`/owner/consoles/${consoleId}/review`);
  const history = useApi<HistoryRow[]>(`/owner/consoles/${consoleId}/history`, 30000);
  const { run, msg, busy } = useAction();
  const r = review.data;
  const act = (path: string, ok: string) => run(async () => { await post(`/owner/consoles/${consoleId}/${path}`); review.reload(); onChange(); }, ok);
  return <section className="card stack" id="validacao">
    <div className="spread"><h2 style={{ margin: 0 }}>Validação e publicação</h2>{r && <StatusPill status={r.status} map={STATUS} />}</div>
    {msg}{review.error && <Alert kind="error">{review.error.message}</Alert>}
    {r && <>
      <ol className="small owner-steps">
        <li className={r.status !== 'draft' && r.status !== 'rejected' ? 'done' : ''}>Cadastre console, jogos (com artes) e períodos, e a tarifa.</li>
        <li className={r.approved_at ? 'done' : r.status === 'submitted' ? 'now' : ''}>Envie para análise: a equipe valida e vincula o agente.</li>
        <li className={r.agent_linked && r.approved_at ? 'now' : ''}>Depois da aprovação: conecte a conta PSN e aguarde o teste de conexão da equipe.</li>
        <li className={r.is_published ? 'done' : ''}>Publique o console para aluguel.</li>
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
        {r.approved_at && !r.is_published && <button className="btn primary" disabled={busy} onClick={() => act('publish', 'Console publicado para aluguel.')}>Publicar para aluguel</button>}
        {r.is_published && <button className="btn" disabled={busy} onClick={() => act('unpublish', 'Console fora do ar para novas reservas.')}>Tirar do ar</button>}
      </div>
    </>}
    <h3 style={{ margin: '8px 0 0' }}>Filas e sessões deste console</h3>
    <DataTable limit={8} rows={history.data} error={history.error?.message} empty="Este console ainda não teve reservas."
      cols={[['Reserva', (h) => h.code], ['Jogo', (h) => h.game], ['Jogador', (h) => h.player], ['Início', (h) => dateTime(h.starts_at)],
        ['Tempo', (h) => `${h.minutes} min${h.seconds_used ? ` (usou ${duration(h.seconds_used)})` : ''}`],
        ['Situação', (h) => RES_STATUS[h.status] ?? h.status], ['Valor', (h) => money(h.total_cents)]]} />
  </section>;
}
