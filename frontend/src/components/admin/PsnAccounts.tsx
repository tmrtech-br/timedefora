'use client';
import { useState } from 'react';
import { Alert, Field, PageHeader, StatusPill } from '@/components/ui';
import { del, patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { DataTable, useAction, useConfirm } from './common';
import { dateTime } from '@/lib/format';

type Account = Record<string, unknown> & { id: string; agent_id: string; agent_name: string; label: string; status: string; online_id: string | null;
  account_id: string | null; last_check_at: string | null; last_error: string };
type Agent = { id: string; name: string; is_simulated: boolean };

type LoginLink = { id: string; label: string; url: string };
type PsnDevice = { platform: string; duid: string; name: string; remoteplay_enabled: boolean };
type LanPs4 = { address: string; state: string; host_name: string | null };
type Ps4Diagnostic = { duid: string; message: string };

export default function PsnAccounts() {
  const accounts = useApi<Account[]>('/admin/psn-accounts');
  const options = useApi<{ chiaki_import_enabled: boolean }>('/admin/psn-accounts/options');
  const agents = useApi<Agent[]>('/admin/agents');
  const [newLabel, setNewLabel] = useState('');
  const [agentId, setAgentId] = useState('');
  const [redirect, setRedirect] = useState('');
  const [login, setLogin] = useState<LoginLink | null>(null);
  const [diagnostic, setDiagnostic] = useState<(Ps4Diagnostic & { label: string }) | null>(null);
  const [devices, setDevices] = useState<
    { source: 'psn'; label: string; items: PsnDevice[] } |
    { source: 'lan'; label: string; items: LanPs4[] } | null
  >(null);
  const { run, msg, busy } = useAction();
  const [confirm, confirmation] = useConfirm();
  const refresh = () => { accounts.reload(); setLogin(null); setRedirect(''); setDevices(null); setDiagnostic(null); };

  return (
    <div className="stack">
      <PageHeader title="Contas PSN" subtitle="Vincule várias contas ao mesmo PC agente. Os tokens são protegidos por DPAPI e não são armazenados no servidor." />
      {msg}{confirmation}
      <Alert kind="warn"><span>A conexão Remote Play nativa pela internet ainda depende do protocolo PSN Session Manager/holepunch.
        Vincular uma conta NÃO significa que vídeo, áudio, controle ou conexão ao console foram validados.</span></Alert>
      <section className="card stack">
        <h2>Cadastrar conta</h2>
        <div className="grid3">
          <Field label="Rótulo interno"><input maxLength={80} placeholder="teste01" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} /></Field>
          <Field label="Agente Windows"><select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Selecione um agente</option>
            {agents.data?.filter((a) => !a.is_simulated).map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
          </select></Field>
        </div>
        <div className="row"><button className="btn primary" disabled={busy || !agentId || newLabel.trim().length < 2} onClick={() => run(async () => {
          await post('/admin/psn-accounts', { label: newLabel.trim(), agent_id: agentId });
          setNewLabel(''); accounts.reload();
        }, 'Conta cadastrada. Clique em Vincular para autenticar na Sony.')}>Cadastrar conta</button></div>
      </section>
      <section className="card stack">
        <h2>Contas vinculadas ao agente</h2>
        <DataTable<Account> rows={accounts.data} cols={[
          ['Rótulo', (a) => <b>{a.label}</b>],
          ['Agente', (a) => a.agent_name],
          ['PSN ID', (a) => a.online_id || '—'],
          ['Estado', (a) => <StatusPill status={a.status} map={{ pending: 'pendente', linked: 'vinculada', expired: 'expirada', error: 'erro', disabled: 'desativada' }} />],
          ['Última verificação', (a) => dateTime(a.last_check_at)],
          ['Ações', (a) => <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <button className="btn sm" disabled={busy || a.status === 'disabled'} onClick={() => run(async () => {
              const result = await post<{ login_url: string }>(`/admin/psn-accounts/${a.id}/login/start`);
              setLogin({ id: a.id, label: a.label, url: result.login_url }); setRedirect('');
            })}>Vincular</button>
            <button className="btn sm" disabled={busy || a.status === 'disabled'} onClick={() => run(async () => {
              const result = await post<{ok: boolean; message?: string}>(`/admin/psn-accounts/${a.id}/test`);
              accounts.reload(); if (!result.ok) throw new Error(result.message || 'A conta PSN não foi validada.');
            }, 'Token PSN validado na Sony.')}>Testar</button>
            <button className="btn sm" disabled={busy || a.status !== 'linked'} onClick={() => run(async () => {
              const response = await post<{ok: boolean; devices: PsnDevice[]}>(`/admin/psn-accounts/${a.id}/devices`);
              setDevices({ source: 'psn', label: a.label, items: response.devices });
            }, 'Consulta de dispositivos PS5 concluída na Sony.')}>Consultar PS5</button>
            <button className="btn sm" disabled={busy} onClick={() => run(async () => {
              const response = await post<{ devices: LanPs4[] }>(`/admin/psn-accounts/${a.id}/devices/ps4-lan`);
              setDevices({ source: 'lan', label: a.agent_name, items: response.devices });
            })}>Buscar PS4 na rede local</button>
            <button className="btn sm" disabled={busy || a.status !== 'linked'} onClick={() => run(async () => {
              setDiagnostic(null);
              const result = await post<Ps4Diagnostic>(`/admin/psn-accounts/${a.id}/diagnose/ps4-psn`);
              setDiagnostic({ ...result, label: a.label });
            })}>Diagnosticar PS4 via PSN</button>
            {options.data?.chiaki_import_enabled === true && (
              <button className="btn sm" disabled={busy || a.status === 'disabled'} onClick={() => run(async () => {
                await post(`/admin/psn-accounts/${a.id}/import/chiaki`); accounts.reload();
              }, 'Credencial Chiaki importada. Execute Testar para validar.')}>Importar Chiaki</button>
            )}
            <button className="btn sm" disabled={busy} onClick={() => run(async () => {
              const yes = await confirm({ title: 'Desativar conta PSN', message: `Desativar ${a.label}? A conta ficará indisponível para novas conexões.`, confirm: 'Desativar', danger: true });
              if (!yes) return;
              await patch(`/admin/psn-accounts/${a.id}`, { status: 'disabled' }); refresh();
            }, 'Conta desativada no agente e no painel.')}>Desativar</button>
            {a.status === 'disabled' && <button className="btn sm" disabled={busy} onClick={() => run(async () => {
              await patch(`/admin/psn-accounts/${a.id}`, { status: 'pending' }); accounts.reload();
            }, 'Conta reativada. Vincule e valide o login Sony novamente.')}>Reativar</button>}
            <button className="btn sm danger" disabled={busy} onClick={() => run(async () => {
              const yes = await confirm({ title: 'Excluir conta PSN', message: `Excluir a conta ${a.label} e eliminar os tokens armazenados no agente?`, confirm: 'Excluir', danger: true });
              if (!yes) return;
              await del(`/admin/psn-accounts/${a.id}`); refresh();
            }, 'Conta excluída do agente e do banco.')}>Excluir</button>
          </div>],
        ]} />
        {accounts.data?.some((a) => a.last_error) && <div className="small muted">
          {accounts.data.filter((a) => a.last_error).map((a) => <div key={a.id}>{a.label}: {a.last_error}</div>)}
        </div>}
      </section>
      {diagnostic && <section className="card stack">
        <h2>Diagnóstico PSN de {diagnostic.label}</h2>
        <p>{diagnostic.message}</p>
        <p>DUID <code>{diagnostic.duid}</code></p>
        <button className="btn sm" onClick={() => setDiagnostic(null)}>Fechar</button>
      </section>}
      {devices?.source === 'psn' && <section className="card stack">
        <h2>PS5 da conta {devices.label}</h2>
        <p className="small muted">Dispositivos retornados pela PSN. Para localizar um PS4, use a busca na rede local do agente.</p>
        {devices.items.length ? devices.items.map((device) => <div key={device.duid} className="row" style={{ flexWrap: 'wrap' }}>
          <b>{device.name}</b> — {device.platform} — {device.remoteplay_enabled ? 'Remote Play habilitado' : 'Remote Play indisponível'}
          <code>{device.duid}</code>
        </div>) : <p>Nenhum PS5 retornado pela Sony.</p>}
        <button className="btn sm" onClick={() => setDevices(null)}>Fechar</button>
      </section>}
      {devices?.source === 'lan' && <section className="card stack">
        <h2>PS4 na rede de {devices.label}</h2>
        <p className="small muted">A descoberta mostra os consoles detectados pelo agente na rede local. O vínculo com a conta é verificado no pareamento.</p>
        {devices.items.length ? devices.items.map((device) => <div key={device.address} className="row">
          <b>{device.host_name || 'PS4'}</b><code>{device.address}</code><span>{device.state}</span>
        </div>) : <p>Nenhum PS4 respondeu. Confira se o console está ligado, na rede do agente e com Uso remoto habilitado.</p>}
        <button className="btn sm" onClick={() => setDevices(null)}>Fechar</button>
      </section>}
      {login && <section className="card stack">
        <h2>Vincular conta {login.label}</h2>
        <p>1. Abra o login oficial Sony. 2. Faça a autenticação. 3. Copie a URL completa da página de retorno e cole abaixo.</p>
        <div><a className="btn primary" href={login.url} target="_blank" rel="noopener noreferrer">Abrir login Sony</a></div>
        <Field label="URL completa de retorno da Sony"><textarea rows={3} value={redirect} onChange={(e) => setRedirect(e.target.value)}
          placeholder="https://remoteplay.dl.playstation.net/remoteplay/redirect?code=..." /></Field>
        <div className="row">
          <button className="btn primary" disabled={busy || !redirect.trim()} onClick={() => run(async () => {
            await post(`/admin/psn-accounts/${login.id}/login/finish`, { redirect_url: redirect.trim() }); refresh();
          }, 'Conta vinculada à PSN com tokens cifrados no agente.')}>Concluir vínculo</button>
          <button className="btn" onClick={() => { setLogin(null); setRedirect(''); }}>Cancelar</button>
        </div>
        <div className="small muted">Prazo de 10 minutos entre iniciar e concluir. A URL de retorno não é salva no banco.</div>
      </section>}
    </div>
  );
}
