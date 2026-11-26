'use client';
import { useEffect, useState } from 'react';
import { Alert, Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { DataTable, DropdownActions, NewRecord, useAction, useConfirm, useDelete } from './common';
import { dateTime } from '@/lib/format';

type Account = Record<string, unknown> & { id: string; agent_id: string | null; agent_name: string | null; label: string; status: string; online_id: string | null;
  account_id: string | null; last_check_at: string | null; last_error: string };
type Agent = { id: string; name: string; is_simulated: boolean };

type LoginLink = { id: string; label: string; url: string };
type PsnDevice = { platform: string; duid: string; name: string; remoteplay_enabled: boolean };
type LanPs4 = { address: string; state: string; host_name: string | null };
type Ps4Diagnostic = { duid: string; message: string };

export default function PsnAccounts({ onAccountsChanged, initialPlatform = 'all' }: {
  onAccountsChanged?: () => void; initialPlatform?: string;
} = {}) {
  const accounts = useApi<Account[]>('/admin/psn-accounts');
  const options = useApi<{ chiaki_import_enabled: boolean }>('/admin/psn-accounts/options');
  const agents = useApi<Agent[]>('/admin/agents');
  const [newLabel, setNewLabel] = useState('');
  const [agentId, setAgentId] = useState('');
  const [platform, setPlatform] = useState(initialPlatform);
  const [redirect, setRedirect] = useState('');
  const [login, setLogin] = useState<LoginLink | null>(null);
  const [diagnostic, setDiagnostic] = useState<(Ps4Diagnostic & { label: string }) | null>(null);
  const [devices, setDevices] = useState<
    { source: 'psn'; label: string; items: PsnDevice[] } |
    { source: 'lan'; label: string; items: LanPs4[] } | null
  >(null);
  const { run, msg, busy } = useAction();
  const [confirm, confirmation] = useConfirm();
  const deletion = useDelete();
  const refresh = () => { accounts.reload(); onAccountsChanged?.(); setLogin(null); setRedirect(''); setDevices(null); setDiagnostic(null); };
  useEffect(() => {
    if (accounts.error) console.error('Falha ao carregar contas PSN administrativas', { status: accounts.error.status, code: accounts.error.code });
  }, [accounts.error]);

  return (
    <div className="stack">
      <PageHeader title="Contas PSN" subtitle="Vincule várias contas ao mesmo PC agente. Os tokens são protegidos por DPAPI e não são armazenados no servidor." />
      {msg}{confirmation}{deletion.dialog}
      <Alert kind="warn"><span>A conexão Remote Play nativa pela internet ainda depende do protocolo PSN Session Manager/holepunch.
        Vincular uma conta NÃO significa que vídeo, áudio, controle ou conexão ao console foram validados.</span></Alert>
      <NewRecord title="Nova conta PSN">{(close) => <>
        <div className="grid3">
          <Field label="Tipo de console"><select value={platform} onChange={(event) => setPlatform(event.target.value)}>
            <option value="all">Todos os PlayStation</option><option value="PS4">PS4</option><option value="PS5">PS5</option>
          </select></Field>
          <Field label="Rótulo interno"><input maxLength={80} placeholder="teste01" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} /></Field>
          <Field label="Agente Windows"><select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Selecione um agente</option>
            {agents.data?.filter((a) => !a.is_simulated).map((a) => <option value={a.id} key={a.id}>{a.name}</option>)}
          </select></Field>
        </div>
        <div className="row"><button className="btn primary" disabled={busy || !agentId || newLabel.trim().length < 2} onClick={() => run(async () => {
          await post('/admin/psn-accounts', { label: newLabel.trim(), agent_id: agentId });
          setNewLabel(''); accounts.reload(); onAccountsChanged?.(); close();
        }, 'Conta cadastrada. Clique em Vincular para autenticar na Sony.')}>Cadastrar conta</button></div>
      </>}</NewRecord>
      <section className="card stack">
        <h2>Contas vinculadas ao agente</h2>
        <Field label="Filtrar ações por console"><select value={platform} onChange={(event) => setPlatform(event.target.value)}>
          <option value="all">Todos os PlayStation</option><option value="PS4">PS4</option><option value="PS5">PS5</option>
        </select></Field>
        <DataTable<Account> rows={accounts.data} error={accounts.error?.message} cols={[
          ['Rótulo', (a) => <b>{a.label}</b>],
          ['Agente', (a) => a.agent_name ?? 'Aguardando agente'],
          ['PSN ID', (a) => a.online_id || '—'],
          ['Estado', (a) => <StatusPill status={a.status} map={{ pending: 'pendente', linked: 'vinculada', expired: 'expirada', error: 'erro', disabled: 'desativada' }} />],
          ['Última verificação', (a) => dateTime(a.last_check_at)],
          ['Ações', (a) => <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <DropdownActions key={platform} disabled={busy} actions={[
              { id: 'link', label: 'Vincular', disabled: !a.agent_id || a.status === 'disabled', execute: () => run(async () => {
                const result = await post<{ login_url: string }>('/admin/psn-accounts/' + a.id + '/login/start');
                setLogin({ id: a.id, label: a.label, url: result.login_url }); setRedirect('');
              }) },
              { id: 'test', label: 'Testar autenticação', disabled: !a.agent_id || a.status === 'disabled', execute: () => run(async () => {
                const result = await post<{ ok: boolean; message?: string }>('/admin/psn-accounts/' + a.id + '/test');
                accounts.reload(); if (!result.ok) throw new Error(result.message || 'A conta PSN n?o foi validada.');
              }, 'Autenticação PSN validada.') },
              ...(platform !== 'PS4' ? [{ id: 'ps5', label: 'Consultar PS5', disabled: a.status !== 'linked', execute: () => run(async () => {
                const response = await post<{ devices: PsnDevice[] }>('/admin/psn-accounts/' + a.id + '/devices');
                setDevices({ source: 'psn', label: a.label, items: response.devices });
              }) }] : []),
              ...(platform !== 'PS5' ? [
                { id: 'ps4-lan', label: 'Buscar PS4 na rede local', disabled: !a.agent_id, execute: () => run(async () => {
                  const response = await post<{ devices: LanPs4[] }>('/admin/psn-accounts/' + a.id + '/devices/ps4-lan');
                  setDevices({ source: 'lan', label: a.agent_name ?? a.label, items: response.devices });
                }) },
                { id: 'ps4-wan', label: 'Diagnosticar PS4 via PSN', disabled: a.status !== 'linked', execute: () => run(async () => {
                  const result = await post<Ps4Diagnostic>('/admin/psn-accounts/' + a.id + '/diagnose/ps4-psn');
                  setDiagnostic({ ...result, label: a.label });
                }) },
              ] : []),
              ...(options.data?.chiaki_import_enabled ? [{ id: 'chiaki', label: 'Importar Chiaki', disabled: !a.agent_id || a.status === 'disabled', execute: () => run(async () => {
                await post('/admin/psn-accounts/' + a.id + '/import/chiaki'); accounts.reload();
              }, 'Credencial importada. Execute o teste de autenticação.') }] : []),
              ...(a.status === 'disabled' ? [{ id: 'enable', label: 'Reativar', execute: () => run(async () => {
                await patch('/admin/psn-accounts/' + a.id, { status: 'pending' }); refresh();
              }, 'Conta reativada.') }] : []),
            ]} />
            <button className="btn sm" disabled={busy} onClick={() => run(async () => {
              const yes = await confirm({ title: 'Desativar conta PSN', message: `Desativar ${a.label}? A conta ficará indisponível para novas conexões.`, confirm: 'Desativar', danger: true });
              if (!yes) return;
              await patch(`/admin/psn-accounts/${a.id}`, { status: 'disabled' }); refresh();
            }, 'Conta desativada no agente e no painel.')}>Desativar</button>
            <button className="btn sm danger" disabled={busy} onClick={() => deletion.remove(
              `/admin/psn-accounts/${a.id}`, 'Excluir conta PSN?',
              (request) => run(async () => { await request(); refresh(); }, 'Conta excluída do agente e do banco.'),
              `Os tokens da conta ${a.label} serão eliminados do agente.`,
            )}>Excluir</button>
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
        <DataTable rows={devices.items} empty="Nenhum PS5 retornado pela Sony." cols={[
          ['Nome', (device) => device.name], ['Plataforma', (device) => device.platform],
          ['Remote Play', (device) => device.remoteplay_enabled ? 'Habilitado' : 'Indisponível'],
          ['DUID', (device) => <code>{device.duid}</code>],
        ]} />
        <button className="btn sm" onClick={() => setDevices(null)}>Fechar</button>
      </section>}
      {devices?.source === 'lan' && <section className="card stack">
        <h2>PS4 na rede de {devices.label}</h2>
        <p className="small muted">A descoberta mostra os consoles detectados pelo agente na rede local. O vínculo com a conta é verificado no pareamento.</p>
        <DataTable rows={devices.items} empty="Nenhum PS4 respondeu. Confira a rede e o Uso remoto." cols={[
          ['Console', (device) => device.host_name || 'PS4'], ['Endereço', (device) => <code>{device.address}</code>],
          ['Estado', (device) => device.state],
        ]} />
        <button className="btn sm" onClick={() => setDevices(null)}>Fechar</button>
      </section>}
      {login && <Modal title={`Vincular conta ${login.label}`} onClose={() => { setLogin(null); setRedirect(''); }}>
        <div className="stack">
        <p>1. Abra o login oficial Sony. 2. Faça a autenticação. 3. Copie a URL completa da página de retorno e cole abaixo.</p>
        <div><a className="btn primary" href={login.url} target="_blank" rel="noopener noreferrer">Abrir login Sony</a></div>
        <Field label="URL completa de retorno da Sony"><textarea rows={3} value={redirect} onChange={(e) => setRedirect(e.target.value)}
          placeholder="https://remoteplay.dl.playstation.net/remoteplay/redirect?code=..." /></Field>
        <div className="row">
          <button className="btn primary" disabled={busy || !redirect.trim()} onClick={() => run(async () => {
            await post(`/admin/psn-accounts/${login.id}/login/finish`, { redirect_url: redirect.trim() }); refresh();
          }, 'Conta vinculada à PSN com tokens cifrados no agente.')}>Concluir vínculo</button>
        </div>
        <div className="small muted">Prazo de 10 minutos entre iniciar e concluir. A URL de retorno não é salva no banco.</div>
        </div>
      </Modal>}
    </div>
  );
}
