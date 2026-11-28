'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { BarChart3, CircleHelp, Gamepad2, Headphones, Landmark, LifeBuoy, MonitorSmartphone, UserRoundCheck, CalendarClock } from 'lucide-react';
import { Alert, Field } from '@/components/ui';
import { put } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { DataTable, useAction } from '@/components/admin/common';
import OwnerDashboard from '@/components/owner/OwnerDashboard';
import OwnerConsoles from '@/components/owner/OwnerConsoles';
import OwnerPsn from '@/components/owner/OwnerPsn';
import OwnerGames from '@/components/owner/OwnerGames';
import OwnerHours from '@/components/owner/OwnerHours';
import OwnerHelp from '@/components/owner/OwnerHelp';
import type { OwnerConsole, PsnAccount } from '@/components/owner/shared';

type Destination = { kind: 'pix' | 'bank'; masked: string; updated_at: string };
type Payout = { id: string; amount_cents: number; status: string; destination_masked: string | null; paid_at: string | null; proof_url: string | null; game: string };
const PAYOUT_LABEL: Record<string, string> = { scheduled: 'Agendado', waiting_destination: 'Cadastre seu Pix/conta', awaiting_manual: 'Em pagamento',
  processing: 'Enviando', paid: 'Pago', failed: 'Em análise pela equipe' };

const MENU = [
  { id: 'dashboard', label: 'Dashboard', icon: BarChart3 },
  { id: 'cadastro', label: 'Cadastro de console', icon: MonitorSmartphone },
  { id: 'psn', label: 'Contas PSN', icon: UserRoundCheck },
  { id: 'jogos', label: 'Jogos e preços', icon: Gamepad2 },
  { id: 'disponibilidade', label: 'Disponibilidade', icon: CalendarClock },
  { id: 'recebimento', label: 'Configurações bancárias', icon: Landmark },
  { id: 'suporte', label: 'Suporte', icon: Headphones },
  { id: 'ajuda', label: 'Ajuda', icon: CircleHelp },
] as const;
type Tab = typeof MENU[number]['id'];

/** Portal do proprietário: um menu por assunto (o console escolhido é compartilhado entre os menus). */
export default function OwnerInventory() {
  const consoles = useApi<OwnerConsole[]>('/owner/consoles');
  const accounts = useApi<PsnAccount[]>('/owner/psn-accounts');
  const [tab, setTab] = useState<Tab>('dashboard');
  const [selected, setSelected] = useState('');
  useEffect(() => {
    const fromHash = () => { const h = window.location.hash.slice(1) as Tab; if (MENU.some((m) => m.id === h)) setTab(h); };
    fromHash();
    window.addEventListener('hashchange', fromHash);
    return () => window.removeEventListener('hashchange', fromHash);
  }, []);
  useEffect(() => { if (!selected && consoles.data?.length === 1) setSelected(consoles.data[0].id); }, [consoles.data, selected]);
  const go = (id: Tab) => { setTab(id); try { window.history.replaceState(null, '', `#${id}`); } catch { /* */ } };
  const title = MENU.find((m) => m.id === tab)?.label;

  return <div className="admin-grid owner-portal">
    <nav className="admin-nav" aria-label="Menu do proprietário">
      {MENU.map((m) => <a key={m.id} href={`#${m.id}`} className={tab === m.id ? 'on' : ''} aria-current={tab === m.id ? 'page' : undefined}
        onClick={(e) => { e.preventDefault(); go(m.id); }}><m.icon size={16} aria-hidden />{m.label}</a>)}
    </nav>
    <div className="stack">
      <h2 className="owner-title">{title}</h2>
      {consoles.error && <Alert kind="error">{consoles.error.message}</Alert>}
      {tab === 'dashboard' && <OwnerDashboard />}
      {tab === 'cadastro' && <OwnerConsoles consoles={consoles.data} reload={consoles.reload} selected={selected} setSelected={setSelected} />}
      {tab === 'psn' && <OwnerPsn consoles={consoles.data} accounts={accounts.data} reloadAccounts={accounts.reload} reloadConsoles={consoles.reload}
        selected={selected} setSelected={setSelected} />}
      {tab === 'jogos' && <OwnerGames key={selected} consoles={consoles.data} selected={selected} setSelected={setSelected} onReviewChange={consoles.reload} />}
      {tab === 'disponibilidade' && <OwnerHours key={selected} consoles={consoles.data} selected={selected} setSelected={setSelected} onReviewChange={consoles.reload} />}
      {tab === 'recebimento' && <Payments />}
      {tab === 'suporte' && <Support />}
      {tab === 'ajuda' && <OwnerHelp />}
    </div>
  </div>;
}

function Payments() {
  const destination = useApi<Destination>('/owner/payout-destination');
  const payouts = useApi<Payout[]>('/owner/payouts', 60000);
  return <section className="stack" id="recebimento">
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Onde receber</h2>
      <p className="small muted" style={{ margin: 0 }}>Sua parte de cada sessão concluída sem problemas é enviada para este destino a partir de 10 minutos após o fim
        da sessão. Pix ou transferência por Pix para a sua conta, sem custo.</p>
      {destination.data && <Alert kind="ok">Atual: {destination.data.kind === 'pix' ? 'Pix' : 'Conta bancária'} · {destination.data.masked} (desde {dateTime(destination.data.updated_at)})</Alert>}
      <PayoutForm onSaved={destination.reload} />
    </div>
    <div className="card stack"><h2 style={{ margin: 0 }}>Meus repasses</h2>
      <DataTable limit={10} rows={payouts.data} error={payouts.error?.message} empty="Nenhum repasse ainda."
        cols={[['Valor', (r) => money(r.amount_cents)], ['Sessão', (r) => r.game], ['Destino', (r) => r.destination_masked ?? '—'],
          ['Situação', (r) => PAYOUT_LABEL[r.status] ?? r.status], ['Pago em', (r) => (r.paid_at ? dateTime(r.paid_at) : '—')],
          ['', (r) => (r.proof_url ? <a className="link-purple" href={r.proof_url} target="_blank" rel="noopener noreferrer">Comprovante</a> : null)]]} /></div>
  </section>;
}

function PayoutForm({ onSaved }: { onSaved: () => void }) {
  const [kind, setKind] = useState<'pix' | 'bank'>('pix');
  const { busy, msg, run } = useAction();
  return <form className="stack" onSubmit={(event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    void run(async () => { await put('/owner/payout-destination', { kind, ...values }); form.reset(); onSaved(); }, 'Dados de recebimento salvos.');
  }}>
    {msg}
    <Field label="Forma de recebimento"><select value={kind} onChange={(e) => setKind(e.target.value === 'bank' ? 'bank' : 'pix')}>
      <option value="pix">Pix</option><option value="bank">Conta bancária</option></select></Field>
    {kind === 'pix' ? <Field label="Chave Pix"><input name="pix_key" required minLength={5} maxLength={140} autoComplete="off" /></Field>
      : <div className="grid3">
        <Field label="Código do banco"><input name="bank_code" required pattern="[0-9]{3}" inputMode="numeric" /></Field>
        <Field label="Agência"><input name="branch" required pattern="[0-9]{1,8}" inputMode="numeric" /></Field>
        <Field label="Conta com dígito"><input name="account_number" required maxLength={18} autoComplete="off" /></Field>
        <Field label="Tipo de conta"><select name="account_type"><option value="checking">Corrente</option><option value="savings">Poupança</option></select></Field>
        <Field label="CPF ou CNPJ do titular"><input name="holder_document" required pattern="[0-9]{11}|[0-9]{14}" inputMode="numeric" autoComplete="off" /></Field>
      </div>}
    <div><button className="btn primary" disabled={busy}>Salvar dados de recebimento</button></div>
  </form>;
}

function Support() {
  return <section className="stack" id="suporte">
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Falar com a equipe</h2>
      <p className="muted" style={{ margin: 0 }}>Abra um chamado e acompanhe as respostas pelo site e por e-mail. Informe o nome do console no assunto para agilizar.</p>
      <div className="row">
        <Link className="btn primary" href="/suporte"><LifeBuoy size={16} aria-hidden />Abrir chamado</Link>
        <Link className="btn" href="/suporte">Meus chamados</Link>
      </div>
    </div>
    <div className="card how-rules"><h2>Antes de abrir um chamado</h2>
      <ul>
        <li><CircleHelp size={18} aria-hidden /><span>Veja o passo a passo em <a className="link-purple" href="#ajuda">Ajuda</a>.</span></li>
        <li><MonitorSmartphone size={18} aria-hidden /><span>Cadastro recusado? Leia as observações da equipe em Cadastro de console, ajuste e envie de novo.</span></li>
        <li><Landmark size={18} aria-hidden /><span>Repasse atrasado? Confira se o Pix ou a conta está cadastrado em Configurações bancárias.</span></li>
      </ul></div>
  </section>;
}
