'use client';

import { useEffect, useState } from 'react';
import { Alert, Field, Modal } from '@/components/ui';
import { patch, post, put } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { DataTable, fromLocalInput, NewRecord, useAction, useDelete } from '@/components/admin/common';
import { EMPTY_GAME, GameRegistrationFields, gameRegistrationBody } from '@/components/admin/Games';

type Console = { id: string; code: string; name: string; platform_code: string; agent_id: string | null; is_published: boolean;
  owner_requested_psn_account_id?: string | null; psn_account_id?: string | null };
type Account = { id: string; label: string; online_id: string | null; status: string; agent_id: string | null };
const EMPTY_CONSOLE = { code: '', name: '', platform_code: 'PS5', model: '', serial_number: '', location: '', description: '' };
type Games = { games: { id: string; title: string }[]; assignments: { id: string; title: string; starts_at: string; ends_at: string }[]; drafts: { id: string; title: string }[] };
type Rate = { min_minutes: number; max_minutes: number; rate_unit: 'minute' | 'hour'; rate_cents: number; paused?: boolean };
type Dashboard = { totals: { sessions: number; seconds_used: number; rented_minutes: number; paid_cents: number; pending_cents: number }; history: { id: string; name: string; ended_at: string; seconds_used: number }[] };
type Settlement = { id: string; owner_cents: number; status: string; updated_at: string };
type Destination = { kind: 'pix' | 'bank'; masked: string; updated_at: string };
const SETTLEMENT_STATUS: Record<string, string> = { held: 'Retido', eligible: 'Aguardando repasse', cancelled: 'Cancelado', paid: 'Pago' };
const DEFAULT_RATE: Rate = { min_minutes: 10, max_minutes: 120, rate_unit: 'minute', rate_cents: 100 };

function Rates({ consoleId, value, locked, onSaved }: { consoleId: string; value: Rate | null; locked: boolean; onSaved: () => void }) {
  const [rate, setRate] = useState<Rate>(value ?? DEFAULT_RATE);
  const { busy, msg, run } = useAction();
  const [editing, setEditing] = useState(!value);
  const deletion = useDelete();
  return <>{msg}{deletion.dialog}
    {value && <div className="stack">
      <p><strong>{value.paused ? 'Pausada' : 'Disponibilidade salva'}</strong> · {value.min_minutes} a {value.max_minutes} min · {money(value.rate_cents)} por {value.rate_unit === 'hour' ? 'hora' : 'minuto'}</p>
      <div className="row">
        <button className="btn sm" disabled={busy || locked} onClick={() => { setRate(value); setEditing(true); }}>Alterar</button>
        <button className="btn sm" disabled={busy} onClick={() => run(async () => {
          await patch(`/owner/consoles/${consoleId}/availability`, { paused: !value.paused });
          onSaved();
        }, value.paused ? 'Disponibilidade retomada.' : 'Disponibilidade pausada.')}>{value.paused ? 'Retomar' : 'Pausar'}</button>
        <button className="btn sm danger" disabled={busy || locked} onClick={() => deletion.remove(
          `/owner/consoles/${consoleId}/availability`, 'Excluir disponibilidade?',
          (request) => run(async () => { await request(); setRate(DEFAULT_RATE); setEditing(true); onSaved(); }, 'Disponibilidade excluída.'),
        )}>Excluir</button>
      </div>
      {locked && <p className="small muted">Despublique o console para alterar ou excluir a tarifa e a duração.</p>}
    </div>}
    {editing && <form className="stack" onSubmit={(event) => {
    event.preventDefault();
    void run(async () => { await put(`/owner/consoles/${consoleId}/availability`, rate); setEditing(false); onSaved(); }, 'Disponibilidade salva.');
  }}>
    <div className="grid3">
      <Field label="Mínimo de minutos"><input required type="number" min={1} max={480} value={rate.min_minutes} onChange={(event) => setRate({ ...rate, min_minutes: Number(event.target.value) })} /></Field>
      <Field label="Máximo de minutos"><input required type="number" min={rate.min_minutes} max={480} value={rate.max_minutes} onChange={(event) => setRate({ ...rate, max_minutes: Number(event.target.value) })} /></Field>
      <Field label="Tarifa em centavos"><input required type="number" min={1} max={1000000} value={rate.rate_cents} onChange={(event) => setRate({ ...rate, rate_cents: Number(event.target.value) })} /></Field>
      <Field label="Unidade"><select value={rate.rate_unit} onChange={(event) => setRate({ ...rate, rate_unit: event.target.value === 'hour' ? 'hour' : 'minute' })}>
        <option value="minute">Por minuto</option><option value="hour">Por hora</option></select></Field>
    </div>
    <div><button className="btn primary" disabled={busy || locked}>Salvar tarifa e duração</button></div>
  </form>}</>;
}

export default function OwnerInventory() {
  const consoles = useApi<Console[]>('/owner/consoles');
  const accounts = useApi<Account[]>('/owner/psn-accounts');
  const dashboard = useApi<Dashboard>('/owner/dashboard');
  const settlements = useApi<Settlement[]>('/owner/settlements');
  const destination = useApi<Destination>('/owner/payout-destination');
  const [consoleId, setConsoleId] = useState('');
  const [newConsole, setNewConsole] = useState(EMPTY_CONSOLE);
  const [psnConsole, setPsnConsole] = useState('');
  const [label, setLabel] = useState('');
  const [window, setWindow] = useState({ game_id: '', starts_at: '', ends_at: '' });
  const [gameDraft, setGameDraft] = useState<Record<string, unknown>>(EMPTY_GAME);
  const [login, setLogin] = useState<{ id: string; url: string }>();
  const [redirectUrl, setRedirectUrl] = useState('');
  const { busy, msg, run } = useAction();
  const current = consoles.data?.find((item) => item.id === consoleId);
  const playStations = (consoles.data ?? []).filter((item) => ['PS4', 'PS5'].includes(item.platform_code));
  const games = useApi<Games>(current ? `/owner/consoles/${current.id}/games` : null);
  const rate = useApi<Rate | null>(current ? `/owner/consoles/${current.id}/availability` : null);
  const error = consoles.error ?? accounts.error ?? dashboard.error ?? games.error ?? rate.error ?? settlements.error ?? destination.error;
  useEffect(() => {
    if (accounts.error) console.error('Falha ao carregar contas PSN do proprietário', { status: accounts.error.status, code: accounts.error.code });
  }, [accounts.error]);

  return <div className="admin-grid">
    <nav className="admin-nav" aria-label="Menu do proprietário">
      <a href="#dashboard">Dashboard</a><a href="#consoles">Consoles</a><a href="#contas-psn">Contas PSN</a>
      <a href="#jogos">Jogos</a><a href="#disponibilidade">Disponibilidade</a><a href="#recebimento">Recebimento</a>
    </nav>
    <div className="stack">
      {msg}{error && <Alert kind="error">{error.message}</Alert>}
      {dashboard.data && <div className="kpis">
        <div className="card kpi"><span>Sessões concluídas</span><strong>{dashboard.data.totals.sessions}</strong></div>
        <div className="card kpi"><span>Tempo alugado</span><strong>{dashboard.data.totals.rented_minutes} min</strong></div>
        <div className="card kpi"><span>Recebido</span><strong>{money(dashboard.data.totals.paid_cents)}</strong></div>
        <div className="card kpi"><span>Pendente</span><strong>{money(dashboard.data.totals.pending_cents)}</strong></div>
      </div>}
      <section className="card" id="dashboard"><h2>Dashboard</h2>
        <div className="grid2">
          <div className="stack"><h3>Sessões recentes</h3><DataTable rows={dashboard.data?.history ?? null} error={dashboard.error?.message}
            cols={[[ 'Console', (r) => r.name ], ['Encerrada em', (r) => dateTime(r.ended_at)]]} /></div>
          <div className="stack"><h3>Histórico de repasses</h3><DataTable rows={settlements.data} error={settlements.error?.message}
            cols={[[ 'Valor', (r) => money(r.owner_cents) ], ['Situação', (r) => SETTLEMENT_STATUS[r.status] ?? r.status], ['Desde', (r) => dateTime(r.updated_at)]]} /></div>
        </div>
      </section>
      <section className="card stack" id="consoles"><h2>Consoles</h2>
        
        <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const created = await post<Console>('/owner/consoles', { ...newConsole, serial_number: newConsole.serial_number || null });
            await consoles.reload();
            setConsoleId(created.id);
            setNewConsole(EMPTY_CONSOLE);
          }, 'Console cadastrado. A equipe configura o agente antes do vínculo PSN.');
        }}>
          <div className="grid3">
            <Field label="Código"><input required maxLength={30} value={newConsole.code} onChange={(e) => setNewConsole({ ...newConsole, code: e.target.value.toUpperCase() })} /></Field>
            <Field label="Nome"><input required maxLength={60} value={newConsole.name} onChange={(e) => setNewConsole({ ...newConsole, name: e.target.value })} /></Field>
            <Field label="Plataforma"><select value={newConsole.platform_code} onChange={(e) => setNewConsole({ ...newConsole, platform_code: e.target.value })}>
              {['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((platform) => <option key={platform}>{platform}</option>)}</select></Field>
            <Field label="Modelo"><input maxLength={120} value={newConsole.model} onChange={(e) => setNewConsole({ ...newConsole, model: e.target.value })} /></Field>
            <Field label="Série / identificador"><input maxLength={120} value={newConsole.serial_number} onChange={(e) => setNewConsole({ ...newConsole, serial_number: e.target.value })} /></Field>
            <Field label="Localização operacional"><input maxLength={120} value={newConsole.location} onChange={(e) => setNewConsole({ ...newConsole, location: e.target.value })} /></Field>
          </div>
          <Field label="Descrição / observações"><textarea maxLength={500} value={newConsole.description} onChange={(e) => setNewConsole({ ...newConsole, description: e.target.value })} /></Field>
          <div><button className="btn primary" disabled={busy}>Cadastrar console</button></div>
        </form>
        <Field label="Console em edição"><select value={consoleId} onChange={(e) => {
          setConsoleId(e.target.value);
          setWindow({ game_id: '', starts_at: '', ends_at: '' });
          setGameDraft(EMPTY_GAME);
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
      <section className="card stack" id="contas-psn"><h2>Contas PSN</h2>
        
        <NewRecord title="Nova conta PSN">{(close) => <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await post('/owner/psn-accounts', { console_id: psnConsole || null, label: label.trim() });
            setLabel('');
            setPsnConsole('');
            await accounts.reload();
            close();
          }, 'Conta PSN cadastrada.');
        }}>
          <Field label="Rótulo interno"><input required minLength={2} maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
          <Field label="Console PlayStation" hint="Opcional. Se o console já tem um agente autorizado, você pode vincular o login Sony logo após cadastrar.">
            <select value={psnConsole} onChange={(event) => setPsnConsole(event.target.value)}>
              <option value="">Cadastrar sem console</option>
              {playStations.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.platform_code}</option>)}
            </select>
          </Field>
          <button className="btn" disabled={busy}>Cadastrar conta PSN</button>
        </form>}</NewRecord>
        <DataTable rows={accounts.data} error={accounts.error?.message} empty="Nenhuma conta PSN cadastrada."
          cols={[[ 'Conta', (account) => account.label ], ['ID PSN', (account) => account.online_id ?? '—'],
            ['Estado', (account) => !account.agent_id ? 'Aguardando agente' : account.status === 'linked' ? 'Vinculada' : 'Vínculo pendente'],
            ['Ações', (account) => <div className="row">
          {!account.agent_id && playStations.some((item) => item.agent_id) && <Field label="Associar agente do console">
            <select value="" disabled={busy} onChange={(event) => {
              const console_id = event.target.value;
              if (console_id) void run(async () => {
                await put(`/owner/psn-accounts/${account.id}/agent`, { console_id });
                await accounts.reload();
              }, 'Agente associado. Vincule o login Sony.');
            }}>
              <option value="">Selecione um console</option>
              {playStations.filter((item) => item.agent_id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </Field>}
          <button className="btn sm" disabled={busy || !account.agent_id || account.status === 'disabled'} onClick={() => run(async () => {
            const response = await post<{ login_url: string }>(`/owner/psn-accounts/${account.id}/login/start`);
            setRedirectUrl('');
            setLogin({ id: account.id, url: response.login_url });
          })}>Vincular login</button>
          <button className="btn sm" disabled={busy || account.status !== 'linked'} onClick={() => run(async () => {
            const response = await post<{ ok: boolean; message: string }>(`/owner/psn-accounts/${account.id}/test`);
            await accounts.reload();
            if (!response.ok) throw new Error(response.message);
          }, 'Autenticação PSN confirmada.')}>Testar autenticação</button>
        </div>]]} />
        {login && <Modal title="Vincular conta PSN" onClose={() => { setLogin(undefined); setRedirectUrl(''); }}>
        <form className="stack" onSubmit={(event) => {
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
        </form></Modal>}
      </section>
      <section className="card stack" id="jogos"><h2>Jogos e janelas</h2>
        
        {!current && <p>Selecione um console para vincular jogos.</p>}
        {current && games.data && <>
          {!current.is_published && <NewRecord title="Cadastrar jogo para revisão">{(close) => <form className="stack" onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await post(`/owner/consoles/${current.id}/game-drafts`, gameRegistrationBody(gameDraft));
              setGameDraft(EMPTY_GAME);
              await games.reload();
              close();
            }, 'Rascunho criado para revisão da equipe.');
          }}>
            {msg}
            <p>Plataforma do console: {current.platform_code}</p>
            <GameRegistrationFields f={gameDraft} set={(key, value) => setGameDraft((form) => ({ ...form, [key]: value }))} owner />
            <div><button className="btn primary" disabled={busy || String(gameDraft.title).trim().length < 2}>Cadastrar rascunho</button></div>
          </form>}</NewRecord>}
          {Boolean(games.data.drafts.length) && <DataTable rows={games.data.drafts} cols={[[ 'Rascunho aguardando revisão', (item) => item.title ]]} />}
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
          <DataTable rows={games.data.assignments} cols={[[ 'Jogo', (item) => item.title ], ['Início', (item) => dateTime(item.starts_at)], ['Fim', (item) => dateTime(item.ends_at)]]} />
        </>}
      </section>
      <section className="card stack" id="disponibilidade"><h2>Disponibilidade</h2>
        
        {current && !rate.loading && !rate.error && <Rates key={current.id} consoleId={current.id} value={rate.data} locked={current.is_published} onSaved={rate.reload} />}
        {!current && <p>Selecione um console para configurar a duração e a tarifa.</p>}
      </section>
      <section className="card stack" id="recebimento"><h2>Recebimento</h2>
        
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
