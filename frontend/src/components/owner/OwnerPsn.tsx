'use client';
import { useState } from 'react';
import SonyLoginForm from '@/components/SonyLoginForm';
import { Field, Modal, StatusPill } from '@/components/ui';
import { ApiError, post, put } from '@/lib/api';
import { DataTable, NewRecord, useAction, useDelete } from '@/components/admin/common';
import { ConsolePicker, type OwnerConsole, type PsnAccount } from './shared';
import { useDraftValue } from './registrationDraft';

const PSN_STATUS: Record<string, string> = { pending: 'Login pendente', linked: 'Conectada', expired: 'Expirada', error: 'Com erro', disabled: 'Desativada' };

/** Contas PSN do proprietário: cadastrar, fazer o login Sony e vincular ao console (a equipe só confere o vínculo). */
export default function OwnerPsn({ consoles, accounts, reloadAccounts, reloadConsoles, selected, setSelected, wizard = false, onSaveDraft }: {
  consoles: OwnerConsole[] | null; accounts: PsnAccount[] | null; reloadAccounts: () => void; reloadConsoles: () => void;
  selected: string; setSelected: (id: string) => void; wizard?: boolean; onSaveDraft?: () => void;
}) {
  const [label, setLabel] = useDraftValue('psnLabel', '');
  const [psnConsole, setPsnConsole] = useState('');
  const [login, setLogin] = useState<{ id: string; url: string }>();
  const [redirectUrl, setRedirectUrl] = useState('');
  const [restartLogin, setRestartLogin] = useState(false);
  const { busy, msg, run } = useAction();
  const deletion = useDelete();
  const playStations = (consoles ?? []).filter((c) => ['PS4', 'PS5'].includes(c.platform_code));
  const current = consoles?.find((c) => c.id === selected);
  const startLogin = (a: PsnAccount) => run(async () => {
    const r = await post<{ login_url: string }>(`/owner/psn-accounts/${a.id}/login/start`);
    setRedirectUrl(''); setRestartLogin(false); setLogin({ id: a.id, url: r.login_url });
  });
  const testLogin = (a: PsnAccount) => run(async () => {
    const r = await post<{ ok: boolean; message: string }>(`/owner/psn-accounts/${a.id}/test`);
    reloadAccounts(); if (!r.ok) throw new Error(r.message);
  }, 'Conexão com a PSN confirmada.');
  const consoleAccount = current && accounts?.find((a) => a.id === (current.owner_requested_psn_account_id ?? current.psn_account_id));
  const linkedTo = (accountId: string) => playStations.filter((c) => (c.owner_requested_psn_account_id ?? c.psn_account_id) === accountId).map((c) => c.name).join(', ');

  return <section className="stack" id="psn">
    {msg}{deletion.dialog}
    <div className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Contas PSN</h2>
        <NewRecord title="Nova conta PSN">{(close) => <form className="stack" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const consoleId = wizard ? selected : psnConsole;
            await post('/owner/psn-accounts', { console_id: consoleId || null, label: label.trim() });
            if (!wizard) setSelected(consoleId);
            setLabel(''); setPsnConsole(''); reloadAccounts(); reloadConsoles(); close();
          }, 'Conta cadastrada. Agora clique em "Fazer login Sony".');
        }}>
          <Field label="Nome para identificar a conta"><input required minLength={2} maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          {!wizard && <Field label="Console PlayStation">
            <select required value={psnConsole} onChange={(e) => setPsnConsole(e.target.value)}>
              <option value="">Selecione</option>{playStations.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.platform_code}</option>)}</select></Field>}
          <div className="row"><button className="btn primary" disabled={busy}>Cadastrar conta PSN</button>
            {onSaveDraft && <button type="button" className="btn" onClick={onSaveDraft}>Salvar rascunho</button>}</div>
        </form>}</NewRecord></div>
      <DataTable rows={accounts} empty="Nenhuma conta PSN cadastrada."
        cols={[['Conta', (a) => a.label], ['ID PSN', (a) => a.online_id ?? '—'],
          ['Status', (a) => <StatusPill status={a.status} map={PSN_STATUS} />],
          ['Console', (a) => linkedTo(a.id) || '—'],
          ['', (a) => <div className="row" style={{ gap: 6 }}>
            <button className={`btn sm${a.status === 'linked' ? '' : ' primary'}`} disabled={busy || a.status === 'disabled'} onClick={() => startLogin(a)}>
              {a.status === 'linked' ? 'Refazer login Sony' : 'Fazer login Sony'}</button>
            <button className="btn sm" disabled={busy || a.status !== 'linked'} onClick={() => testLogin(a)}>Testar</button>
            <button className="btn sm danger" disabled={busy} onClick={() => deletion.remove(`/owner/psn-accounts/${a.id}`, `Excluir a conta ${a.label}?`,
              (request) => run(async () => { await request(); reloadAccounts(); reloadConsoles(); }, 'Conta PSN excluída.'),
              'O login Sony guardado no agente também é apagado. Não é possível excluir uma conta em uso por um console aprovado.')}>Excluir</button>
          </div>]]} />
    </div>
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Conta PSN do console</h2>
      {!wizard && <ConsolePicker consoles={playStations} value={playStations.some((c) => c.id === selected) ? selected : ''} onChange={setSelected} />}
      {current && !['PS4', 'PS5'].includes(current.platform_code) && <p className="muted">Este console não usa conta PSN.</p>}
      {current && ['PS4', 'PS5'].includes(current.platform_code) && (
        <Field label="Conta PSN que o console vai usar">
          <select value={current.owner_requested_psn_account_id ?? current.psn_account_id ?? ''} disabled={busy || current.review_status === 'submitted'} onChange={(e) => {
            const psn_account_id = e.target.value;
            if (psn_account_id) void run(async () => { await put(`/owner/consoles/${current.id}/connection`, { psn_account_id }); reloadConsoles(); },
              current.approved_at ? 'Troca de conta enviada para a validação da equipe.' : 'Conta vinculada ao console.');
          }}>
            <option value="">Selecione</option>
            {accounts?.filter((a) => !a.agent_id || !current.agent_id || a.agent_id === current.agent_id).map((a) => <option key={a.id} value={a.id}>{a.label}{a.status === 'linked' ? '' : ' (login pendente)'}</option>)}
          </select></Field>)}
      {consoleAccount && <div className="stack" style={{ gap: 8 }}>
        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span>Login Sony:</span><StatusPill status={consoleAccount.status} map={PSN_STATUS} />
          {consoleAccount.online_id && <span className="small muted">ID PSN: {consoleAccount.online_id}</span>}
        </div>
        {consoleAccount.status !== 'linked'
          ? <p className="small muted" style={{ margin: 0 }}>Entre na conta Sony usada neste console para liberar a conexão.</p>
          : <p className="small muted" style={{ margin: 0 }}>Conta conectada. A equipe confere o vínculo na aprovação.</p>}
        <div className="row" style={{ gap: 8 }}>
          <button className={`btn${consoleAccount.status === 'linked' ? '' : ' primary'}`} disabled={busy || consoleAccount.status === 'disabled'} onClick={() => startLogin(consoleAccount)}>
            {consoleAccount.status === 'linked' ? 'Refazer login Sony' : 'Fazer login Sony'}</button>
          {consoleAccount.status === 'linked' && <button className="btn" disabled={busy} onClick={() => testLogin(consoleAccount)}>Testar conta</button>}
        </div>
      </div>}
      {current && ['PS4', 'PS5'].includes(current.platform_code) && !consoleAccount && (accounts?.length ?? 0) === 0 &&
        <p className="small muted" style={{ margin: 0 }}>Cadastre uma conta em “Nova conta PSN” acima.</p>}
    </div>
    {login && <Modal title="Login na conta Sony" onClose={() => { setLogin(undefined); setRedirectUrl(''); }}>
      {restartLogin ? <div className="card stack">
        <p className="small err" role="alert">O endereço da Sony expirou ou já foi usado. Inicie um novo login e cole o novo endereço de retorno.</p>
        <div><button type="button" className="btn primary" disabled={busy} onClick={() => {
          const account = accounts?.find((item) => item.id === login.id);
          if (account) void startLogin(account);
        }}>Reiniciar login Sony</button></div>
      </div> : <SonyLoginForm url={login.url} value={redirectUrl} onChange={setRedirectUrl} busy={busy} onSubmit={() => {
        void run(async () => {
          try {
            await post(`/owner/psn-accounts/${login.id}/login/finish`, { redirect_url: redirectUrl.trim() });
          } catch (error) {
            if (error instanceof ApiError && (['psn_token_expired', 'login_expired'].includes(error.code) || /\binvalid_grant\b/.test(error.message))) {
              setRedirectUrl('');
              setRestartLogin(true);
              return;
            }
            throw error;
          }
          setLogin(undefined); setRedirectUrl(''); reloadAccounts();
        });
      }} />}
    </Modal>}
  </section>;
}
