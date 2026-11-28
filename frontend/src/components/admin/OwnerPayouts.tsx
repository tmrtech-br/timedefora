'use client';
import { useState } from 'react';
import { Alert, Field, Modal } from '@/components/ui';
import { post } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { DataTable, useAction } from './common';

type Payout = {
  id: string; amount_cents: number; status: string; destination_kind: string | null; destination_masked: string | null;
  destination?: Record<string, string> | null; scheduled_for: string; owner_username: string; owner_email: string;
  game: string; session_ended_at: string; reservation_code: string; last_error: string | null;
};
export const PAYOUT_STATUS: Record<string, string> = {
  scheduled: 'Agendado', waiting_destination: 'Sem Pix/conta cadastrados', awaiting_manual: 'Aguardando pagamento',
  processing: 'Enviando', paid: 'Pago', failed: 'Falhou',
};
const ACCOUNT_TYPE: Record<string, string> = { checking: 'Corrente', savings: 'Poupança' };

function DestinationText({ d, kind }: { d: Record<string, string> | null | undefined; kind: string | null }) {
  if (!d) return <span className="muted">—</span>;
  if (kind === 'pix') return <span>Pix: <b>{d.pix_key}</b></span>;
  return <span>Banco {d.bank_code} · Ag. {d.branch} · Conta {d.account_number} ({ACCOUNT_TYPE[d.account_type] ?? d.account_type}) · Titular {d.holder_document}</span>;
}

/** Repasses aos proprietários: com o provedor "manual", a equipe paga pelo banco e marca como pago aqui. */
export default function OwnerPayouts() {
  const list = useApi<Payout[]>('/admin/owner-payouts', 30000);
  const [paying, setPaying] = useState<Payout | null>(null);
  const [proof, setProof] = useState('');
  const [notes, setNotes] = useState('');
  const { run, msg, busy } = useAction();
  const total = (list.data ?? []).filter((p) => p.status === 'awaiting_manual').reduce((s, p) => s + p.amount_cents, 0);
  return (
    <section className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Repasses a pagar</h2>{total > 0 && <span className="pill amber">Total: {money(total)}</span>}</div>
      <p className="small muted" style={{ margin: 0 }}>Gerados 10 min após uma sessão concluída sem problemas. Pague pelo banco (Pix ou transferência) e marque como pago:
        o proprietário é avisado e vê o comprovante.</p>
      {msg}
      <DataTable limit={10} rows={list.data} error={list.error?.message} empty="Nenhum repasse pendente."
        cols={[['Proprietário', (p) => <span>{p.owner_username}<br /><small className="muted">{p.owner_email}</small></span>],
          ['Valor', (p) => <b>{money(p.amount_cents)}</b>], ['Sessão', (p) => `${p.game} · ${p.reservation_code} · ${dateTime(p.session_ended_at)}`],
          ['Destino', (p) => <DestinationText d={p.destination} kind={p.destination_kind} />],
          ['Situação', (p) => PAYOUT_STATUS[p.status] ?? p.status],
          ['', (p) => p.status === 'awaiting_manual' || p.status === 'failed'
            ? <button className="btn sm primary" onClick={() => { setPaying(p); setProof(''); setNotes(''); }}>Marcar como pago</button> : null]]} />
      {paying && <Modal title={`Repasse de ${money(paying.amount_cents)} para ${paying.owner_username}`} onClose={() => setPaying(null)}>
        <div className="stack">
          <Alert kind="info"><DestinationText d={paying.destination} kind={paying.destination_kind} /></Alert>
          <Field label="Link do comprovante (opcional)" hint="https://…"><input maxLength={500} value={proof} onChange={(e) => setProof(e.target.value)} /></Field>
          <Field label="Observação (opcional)"><input maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          <div className="row">
            <button className="btn primary" disabled={busy} onClick={() => run(async () => {
              await post(`/admin/owner-payouts/${paying.id}/mark-paid`, { proof_url: proof.trim() || null, notes });
              setPaying(null); list.reload();
            }, 'Repasse marcado como pago. O proprietário foi avisado.')}>Confirmar pagamento</button>
            <button className="btn" onClick={() => setPaying(null)}>Cancelar</button>
          </div>
        </div>
      </Modal>}
    </section>
  );
}
