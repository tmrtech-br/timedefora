'use client';
import { useState } from 'react';
import { Alert, Field, Modal, StatusPill } from '@/components/ui';
import { post, put } from '@/lib/api';
import { DataTable, NewRecord, useAction } from '@/components/admin/common';
import { ConsolePicker, type OwnerConsole, type PsnAccount } from './shared';

const PSN_STATUS: Record<string, string> = { pending: 'Login pendente', linked: 'Conectada', expired: 'Expirada', error: 'Com erro', disabled: 'Desativada', no_agent: 'Aguardando aprovação' };

/** Contas PSN do proprietário: cadastrar, fazer o login Sony (pelo agente do console) e vincular ao console. */
export default function OwnerPsn({ consoles, accounts, reloadAccounts, reloadConsoles, selected, setSelected }: {
  consoles: OwnerConsole[] | null; accounts: PsnAccount[] | null; reloadAccounts: () => void; reloadConsoles: () => void;
  selected: string; setSelected: (id: string) => void;
}) {
  const [label, setLabel] = useState('');
  const [psnConsole, setPsnConsole] = useState('');
  const [login, setLogin] = useState<{ id: string; url: string }>();
  const [redirectUrl, setRedirectUrl] = useState('');
  const { busy, msg, run } = useAction();
  const playStations = (consoles ?? []).filter((c) => ['PS4', 'PS5'].includes(c.platform_code));
  const current = consoles?.find((c) => c.id === selected);
  const linkedTo = (accountId: string) => playStations.filter((c) => (c.owner_requested_psn_account_id ?? c.psn_account_id) === accountId).map((c) => c.name).join(', ');

  return <section className="stack" id="psn">
    {msg}
    <div className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Contas PSN</h2>
        <NewRecord title="Nova conta PSN">{(close) => <form className="stack" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await post('/owner/psn-accounts', { console_id: psnConsole || null, label: label.trim() });
            setLabel(''); setPsnConsole(''); reloadAccounts(); close();
          }, 'Conta cadastrada e associada ao console. O login Sony é liberado após a aprovação da equipe.');
        }}>
          <Field label="Nome para identificar a conta"><input required minLength={2} maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="Console PlayStation" hint="O login Sony fica liberado depois que a equipe aprovar o console e vincular o agente.">
            <select required value={psnConsole} onChange={(e) => setPsnConsole(e.target.value)}>
              <option value="">Selecione</option>{playStations.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.platform_code}</option>)}</select></Field>
          <button className="btn primary" disabled={busy}>Cadastrar conta PSN</button>
        </form>}</NewRecord></div>
      <DataTable rows={accounts} empty="Nenhuma conta PSN cadastrada."
        cols={[['Conta', (a) => a.label], ['ID PSN', (a) => a.online_id ?? '—'],
          ['Status', (a) => <StatusPill status={a.agent_id ? a.status : 'no_agent'} map={PSN_STATUS} />],
          ['Console', (a) => linkedTo(a.id) || '—'],
          ['', (a) => <div className="row" style={{ gap: 6 }}>
            {!a.agent_id && playStations.some((c) => c.agent_id) && <select className="btn sm" value="" disabled={busy} onChange={(e) => {
              const console_id = e.target.value;
              if (console_id) void run(async () => { await put(`/owner/psn-accounts/${a.id}/agent`, { console_id }); reloadAccounts(); }, 'Agente associado. Faça o login Sony.');
            }}><option value="">Usar agente do console…</option>{playStations.filter((c) => c.agent_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}
            <button className="btn sm" disabled={busy || !a.agent_id || a.status === 'disabled'} title={a.agent_id ? undefined : 'Liberado após a aprovação da equipe'} onClick={() => run(async () => {
              const r = await post<{ login_url: string }>(`/owner/psn-accounts/${a.id}/login/start`);
              setRedirectUrl(''); setLogin({ id: a.id, url: r.login_url });
            })}>{a.status === 'linked' ? 'Refazer login Sony' : 'Fazer login Sony'}</button>
            <button className="btn sm" disabled={busy || a.status !== 'linked'} onClick={() => run(async () => {
              const r = await post<{ ok: boolean; message: string }>(`/owner/psn-accounts/${a.id}/test`);
              reloadAccounts(); if (!r.ok) throw new Error(r.message);
            }, 'Conexão com a PSN confirmada.')}>Testar</button>
          </div>]]} />
    </div>
    <div className="card stack">
      <h2 style={{ margin: 0 }}>Conta PSN do console</h2>
      <ConsolePicker consoles={playStations} value={playStations.some((c) => c.id === selected) ? selected : ''} onChange={setSelected} />
      {current && !['PS4', 'PS5'].includes(current.platform_code) && <p className="muted">Este console não usa conta PSN.</p>}
      {current && ['PS4', 'PS5'].includes(current.platform_code) && (
        <Field label="Conta PSN que o console vai usar" hint={current.agent_id ? undefined : 'A equipe vincula a conta e o console ao agente na aprovação.'}>
          <select value={current.owner_requested_psn_account_id ?? current.psn_account_id ?? ''} disabled={busy || current.review_status === 'submitted'} onChange={(e) => {
            const psn_account_id = e.target.value;
            if (psn_account_id) void run(async () => { await put(`/owner/consoles/${current.id}/connection`, { psn_account_id }); reloadConsoles(); },
              current.approved_at ? 'Troca de conta enviada para a validação da equipe.' : 'Conta vinculada ao console.');
          }}>
            <option value="">Selecione</option>
            {accounts?.filter((a) => !a.agent_id || a.agent_id === current.agent_id).map((a) => <option key={a.id} value={a.id}>{a.label}{a.status === 'linked' ? '' : ' (login pendente)'}</option>)}
          </select></Field>)}
    </div>
    {login && <Modal title="Login na conta Sony" onClose={() => { setLogin(undefined); setRedirectUrl(''); }}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void run(async () => { await post(`/owner/psn-accounts/${login.id}/login/finish`, { redirect_url: redirectUrl }); setLogin(undefined); setRedirectUrl(''); reloadAccounts(); }, 'Conta PSN conectada.');
      }}>
        <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
          <li><a className="link-purple" href={login.url} target="_blank" rel="noreferrer">Abra o login da Sony</a> e entre com a conta PSN do console.</li>
          <li>Depois de entrar, a Sony abre uma página em branco ou de erro: copie o endereço completo dessa página.</li>
          <li>Cole o endereço abaixo e conclua.</li>
        </ol>
        <Field label="Endereço da página após o login"><input type="url" required autoComplete="off" value={redirectUrl} onChange={(e) => setRedirectUrl(e.target.value)} /></Field>
        <div><button className="btn primary" disabled={busy}>Concluir</button></div>
      </form></Modal>}
  </section>;
}
