'use client';

import { useState } from 'react';
import { Alert, Field } from '@/components/ui';
import { post, put } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { fromLocalInput, useAction } from '@/components/admin/common';

type Console = { id: string; code: string; name: string; agent_id: string | null; is_published: boolean;
  owner_requested_psn_account_id?: string | null; psn_account_id?: string | null };
type Account = { id: string; label: string; online_id: string | null; status: string; agent_id: string };
type Games = { games: { id: string; title: string }[]; assignments: { id: string; title: string; starts_at: string; ends_at: string }[] };
type Rate = { min_minutes: number; max_minutes: number; rate_unit: 'minute' | 'hour'; rate_cents: number };
type Dashboard = { totals: { sessions: number; seconds_used: number; rented_minutes: number; paid_cents: number; pending_cents: number }; history: { id: string; name: string; ended_at: string; seconds_used: number }[] };
type Settlement = { id: string; owner_cents: number; status: string; updated_at: string };
type Destination = { kind: 'pix' | 'bank'; masked: string; updated_at: string };
const SETTLEMENT_STATUS: Record<string, string> = { held: 'Retido', eligible: 'Aguardando repasse', cancelled: 'Cancelado', paid: 'Pago' };
const DEFAULT_RATE: Rate = { min_minutes: 10, max_minutes: 120, rate_unit: 'minute', rate_cents: 100 };

function Rates({ consoleId, value, locked }: { consoleId: string; value: Rate | null; locked: boolean }) {
  const [rate, setRate] = useState<Rate>(value ?? DEFAULT_RATE);
  const { busy, msg, run } = useAction();
  return <form className="stack" onSubmit={(event) => {
    event.preventDefault();
    void run(() => put(`/owner/consoles/${consoleId}/availability`, rate), 'Disponibilidade salva.');
  }}>
    {msg}
    <div className="grid3">
      <Field label="Mínimo de minutos"><input required type="number" min={1} max={480} value={rate.min_minutes} onChange={(event) => setRate({ ...rate, min_minutes: Number(event.target.value) })} /></Field>
      <Field label="Máximo de minutos"><input required type="number" min={rate.min_minutes} max={480} value={rate.max_minutes} onChange={(event) => setRate({ ...rate, max_minutes: Number(event.target.value) })} /></Field>
      <Field label="Tarifa em centavos"><input required type="number" min={1} max={1000000} value={rate.rate_cents} onChange={(event) => setRate({ ...rate, rate_cents: Number(event.target.value) })} /></Field>
      <Field label="Unidade"><select value={rate.rate_unit} onChange={(event) => setRate({ ...rate, rate_unit: event.target.value === 'hour' ? 'hour' : 'minute' })}>
        <option value="minute">Por minuto</option><option value="hour">Por hora</option></select></Field>
    </div>
    <div><button className="btn primary" disabled={busy || locked}>Salvar tarifa e duração</button></div>
  </form>;
}

export default function OwnerInventory() {
  const consoles = useApi<Console[]>('/owner/consoles');
  const accounts = useApi<Account[]>('/owner/psn-accounts');
  const dashboard = useApi<Dashboard>('/owner/dashboard');
  const settlements = useApi<Settlement[]>('/owner/settlements');
  const destination = useApi<Destination>('/owner/payout-destination');
  const [consoleId, setConsoleId] = useState('');
  const [newConsole, setNewConsole] = useState({ code: '', name: '', platform_code: 'PS5' });
  const [label, setLabel] = useState('');
  const [window, setWindow] = useState({ game_id: '', starts_at: '', ends_at: '' });
  const [login, setLogin] = useState<{ id: string; url: string }>();
  const [redirectUrl, setRedirectUrl] = useState('');
  const { busy, msg, run } = useAction();
  const current = consoles.data?.find((item) => item.id === consoleId);
  const games = useApi<Games>(current ? `/owner/consoles/${current.id}/games` : null);
  const rate = useApi<Rate | null>(current ? `/owner/consoles/${current.id}/availability` : null);
  const error = consoles.error ?? accounts.error ?? dashboard.error ?? games.error ?? rate.error ?? settlements.error ?? destination.error;

  return <div className="admin-grid">
    <nav className="admin-nav" aria-label="Menu do proprietário">
      <a href="#dashboard">Dashboard</a><a href="#consoles">Consoles</a><a href="#contas-psn">Contas PSN</a>
      <a href="#jogos">Jogos</a><a href="#disponibilidade">Disponibilidade</a><a href="#recebimento">Recebimento</a>
    </nav>
    <div className="stack">
      {msg}{error && <Alert kind="error">{error.message}</Alert>}
      <section className="card" id="dashboard">
        <h2>Dashboard</h2>
        {dashboard.data && <>
          <p>{dashboard.data.totals.sessions} sessões concluídas · {dashboard.data.totals.rented_minutes} minutos alugados · {Math.floor(dashboard.data.totals.seconds_used / 60)} minutos jogados</p>
          <div className="row"><span>Recebidos <strong>{money(dashboard.data.totals.paid_cents)}</strong></span>
            <span>Pendentes <strong>{money(dashboard.data.totals.pending_cents)}</strong></span></div>
          {dashboard.data.history.length > 0 && <ul>{dashboard.data.history.map((entry) => <li key={entry.id}>{entry.name} · {dateTime(entry.ended_at)}</li>)}</ul>}
        </>}
        <h3>Histórico de repasses</h3>
        {settlements.data?.length ? <ul>{settlements.data.map((entry) => <li key={entry.id}>
          {money(entry.owner_cents)} · {SETTLEMENT_STATUS[entry.status] ?? entry.status} · {dateTime(entry.updated_at)}
        </li>)}</ul> : <p>Nenhum repasse registrado.</p>}
      </section>
      <section className="card stack" id="consoles">
        <h2>Consoles</h2>
        <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const created = await post<Console>('/owner/consoles', newConsole);
            await consoles.reload();
            setConsoleId(created.id);
            setNewConsole({ code: '', name: '', platform_code: 'PS5' });
          }, 'Console cadastrado. A equipe configura o agente antes do vínculo PSN.');
        }}>
          <div className="grid3">
            <Field label="Código"><input required maxLength={30} value={newConsole.code} onChange={(e) => setNewConsole({ ...newConsole, code: e.target.value.toUpperCase() })} /></Field>
            <Field label="Nome"><input required maxLength={60} value={newConsole.name} onChange={(e) => setNewConsole({ ...newConsole, name: e.target.value })} /></Field>
            <Field label="Plataforma"><select value={newConsole.platform_code} onChange={(e) => setNewConsole({ ...newConsole, platform_code: e.target.value })}><option>PS5</option><option>PS4</option></select></Field>
          </div>
          <div><button className="btn primary" disabled={busy}>Cadastrar console</button></div>
        </form>
        <Field label="Console em edição"><select value={consoleId} onChange={(e) => {
          setConsoleId(e.target.value);
          setWindow({ game_id: '', starts_at: '', ends_at: '' });
          games.setData(null);
          rate.setData(null);
        }}>
          <option value="">Selecione</option>
          {consoles.data?.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.is_published ? 'Publicado' : 'Aguardando publicação'}</option>)}
        </select></Field>
        {current?.agent_id && !current.is_published && <Field label="Conta PSN para o console">
          <select value={current.owner_requested_psn_account_id ?? current.psn_account_id ?? ''} disabled={busy} onChange={(event) => {
            const psn_account_id = event.target.value;
            if (!psn_account_id) return;
            void run(async () => {
              await put(`/owner/consoles/${current.id}/connection`, { psn_account_id });
              await consoles.reload();
            }, 'Vínculo enviado para configuração pela equipe.');
          }}>
            <option value="">Selecione uma conta vinculada</option>
            {accounts.data?.filter((account) => account.agent_id === current.agent_id && account.status === 'linked')
              .map((account) => <option key={account.id} value={account.id}>{account.label}</option>)}
          </select>
        </Field>}
      </section>
      <section className="card stack" id="contas-psn">
        <h2>Contas PSN</h2>
        {current?.agent_id && !current.is_published && <form className="row" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await post('/owner/psn-accounts', { console_id: current.id, label });
            setLabel('');
            await accounts.reload();
          }, 'Conta cadastrada. Vincule o login Sony.');
        }}>
          <Field label="Rótulo da conta"><input required minLength={2} maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
          <button className="btn" disabled={busy}>Cadastrar conta PSN</button>
        </form>}
        {accounts.data?.map((account) => <div className="row" key={account.id}>
          <span>{account.label}{account.online_id ? ` · ${account.online_id}` : ''}</span>
          <button className="btn sm" disabled={busy || account.status === 'disabled'} onClick={() => run(async () => {
            const response = await post<{ login_url: string }>(`/owner/psn-accounts/${account.id}/login/start`);
            setRedirectUrl('');
            setLogin({ id: account.id, url: response.login_url });
          })}>Vincular login</button>
          <button className="btn sm" disabled={busy || account.status !== 'linked'} onClick={() => run(async () => {
            const response = await post<{ ok: boolean; message: string }>(`/owner/psn-accounts/${account.id}/test`);
            await accounts.reload();
            if (!response.ok) throw new Error(response.message);
          }, 'Autenticação PSN confirmada.')}>Testar autenticação</button>
        </div>)}
        {login && <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await post(`/owner/psn-accounts/${login.id}/login/finish`, { redirect_url: redirectUrl });
            setLogin(undefined);
            setRedirectUrl('');
            await accounts.reload();
          }, 'Login Sony vinculado.');
        }}>
          <a className="link-purple" href={login.url} target="_blank" rel="noreferrer">Abrir login da Sony</a>
          <Field label="URL após autenticar"><input type="url" required autoComplete="off" value={redirectUrl} onChange={(e) => setRedirectUrl(e.target.value)} /></Field>
          <div><button className="btn primary" disabled={busy}>Concluir vínculo</button></div>
        </form>}
      </section>
      <section className="card stack" id="jogos">
        <h2>Jogos e janelas</h2>
        {!current && <p>Selecione um console para vincular jogos.</p>}
        {current && games.data && <>
          {!current.is_published && <form className="stack" onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await post(`/owner/consoles/${current.id}/games`, { game_id: window.game_id,
                starts_at: fromLocalInput(window.starts_at), ends_at: fromLocalInput(window.ends_at) });
              await games.reload();
            }, 'Janela adicionada.');
          }}>
            <div className="grid3">
              <Field label="Jogo"><select required value={window.game_id} onChange={(e) => setWindow({ ...window, game_id: e.target.value })}>
                <option value="">Selecione</option>{games.data.games.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></Field>
              <Field label="Início"><input type="datetime-local" required value={window.starts_at} onChange={(e) => setWindow({ ...window, starts_at: e.target.value })} /></Field>
              <Field label="Fim"><input type="datetime-local" required value={window.ends_at} onChange={(e) => setWindow({ ...window, ends_at: e.target.value })} /></Field>
            </div>
            <div><button className="btn" disabled={busy}>Vincular jogo</button></div>
          </form>}
          <ul>{games.data.assignments.map((item) => <li key={item.id}>{item.title} · {dateTime(item.starts_at)} até {dateTime(item.ends_at)}</li>)}</ul>
        </>}
      </section>
      <section className="card stack" id="disponibilidade">
        <h2>Disponibilidade</h2>
        {current && !rate.loading && !rate.error && <Rates key={current.id} consoleId={current.id} value={rate.data} locked={current.is_published} />}
        {!current && <p>Selecione um console para configurar a duração e a tarifa.</p>}
      </section>
      <section className="card stack" id="recebimento">
        <h2>Recebimento</h2>
        {destination.data && <p>{destination.data.kind === 'pix' ? 'PIX' : 'Conta bancária'} · {destination.data.masked}</p>}
        <PayoutForm onSaved={destination.reload} />
      </section>
    </div>
  </div>;
}

function PayoutForm({ onSaved }: { onSaved: () => void }) {
  const [kind, setKind] = useState<'pix' | 'bank'>('pix');
  const { busy, msg, run } = useAction();
  return <form className="stack" onSubmit={(event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    void run(async () => {
      await put('/owner/payout-destination', { kind, ...values });
      form.reset();
      onSaved();
    }, 'Dados de recebimento salvos.');
  }}>
    {msg}
    <Field label="Forma de recebimento"><select value={kind} onChange={(event) => setKind(event.target.value === 'bank' ? 'bank' : 'pix')}>
      <option value="pix">PIX</option><option value="bank">Conta bancária</option>
    </select></Field>
    {kind === 'pix' ? <Field label="Chave PIX"><input name="pix_key" required minLength={5} maxLength={140} autoComplete="off" /></Field>
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
