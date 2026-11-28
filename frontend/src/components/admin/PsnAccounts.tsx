'use client';
import SonyLoginForm from '@/components/SonyLoginForm';
import { useState, type ReactNode } from 'react';
import { Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { DataTable, NewRecord, useAction, useDelete } from './common';
import { dateTime } from '@/lib/format';

type Platform = 'PS4' | 'PS5';
type Account = Record<string, unknown> & {
  id: string; agent_id: string | null; agent_name: string | null; label: string; status: string;
  online_id: string | null; last_check_at: string | null; last_error: string; platforms?: Platform[];
};
type Agent = { id: string; name: string; is_simulated: boolean };
type PsnDevice = { platform: string; duid: string; name: string; remoteplay_enabled: boolean };
type LanPs4 = { address: string; state: string; host_name: string | null };
type Ps4Diagnostic = { duid: string; message: string };

const STATUS = { pending: 'Pendente', linked: 'Vinculada', expired: 'Expirada', error: 'Erro', disabled: 'Desvinculada' };
const FILTERS = { search: '', agent: '', status: '', platform: '' };

function AccountActions({ account, initialPlatform, canImport, onChange, onClose }: {
  account: Account; initialPlatform: string; canImport: boolean; onChange: () => void; onClose: () => void;
}) {
  const availablePlatforms = account.platforms?.length ? account.platforms : ['PS4', 'PS5'];
  const [platform, setPlatform] = useState(availablePlatforms.length === 1 ? availablePlatforms[0]
    : availablePlatforms.includes(initialPlatform as Platform) ? initialPlatform : '');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ label: string; content: ReactNode; error?: boolean }>();
  const [loginUrl, setLoginUrl] = useState('');
  const [redirect, setRedirect] = useState('');
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const path = `/admin/psn-accounts/${account.id}`;
  const canTest = Boolean(account.agent_id && account.status !== 'disabled');

  async function execute(label: string, action: () => Promise<ReactNode>) {
    setBusy(true);
    setResult(undefined);
    setConfirmUnlink(false);
    try {
      setResult({ label, content: await action() });
    } catch (error) {
      setResult({ label, content: error instanceof Error ? error.message : 'Não foi possível concluir a ação.', error: true });
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Ações da conta ${account.label}`} onClose={onClose} allowEscape>
    <div className="stack">
      <Field label="Console"><select value={platform} disabled={busy || availablePlatforms.length === 1} onChange={(e) => setPlatform(e.target.value)}>
        <option value="">Selecione o console</option>
        {availablePlatforms.map((item) => <option key={item}>{item}</option>)}
      </select></Field>
      {platform && <div className="psn-action-grid">
        <button className="btn" disabled={busy || !account.agent_id} onClick={() => execute('Vincular', async () => {
          setLoginUrl(''); setRedirect('');
          if (account.status === 'disabled') {
            await patch(path, { status: 'pending' });
            onChange();
          }
          const response = await post<{ login_url: string }>(path + '/login/start');
          setLoginUrl(response.login_url);
          return 'Abra o login Sony e cole a URL completa de retorno para concluir o vínculo.';
        })}>Vincular</button>
        <button className="btn" disabled={busy || !canTest} onClick={() => execute('Testar autenticação', async () => {
          const response = await post<{ ok: boolean; message?: string }>(path + '/test');
          onChange();
          if (!response.ok) throw new Error(response.message || 'A conta PSN não foi validada.');
          return response.message || 'Autenticação PSN validada.';
        })}>Testar autenticação</button>
        {platform === 'PS4' && <>
          <button className="btn" disabled={busy || !account.agent_id} onClick={() => execute('Buscar PS4 na rede local', async () => {
            const response = await post<{ devices: LanPs4[] }>(path + '/devices/ps4-lan');
            return <DataTable rows={response.devices} empty="Nenhum PS4 respondeu à busca." cols={[
              ['Console', (item) => item.host_name || 'PS4'], ['Endereço', (item) => <code>{item.address}</code>], ['Estado', (item) => item.state],
            ]} />;
          })}>Buscar PS4 na rede local</button>
          <button className="btn" disabled={busy || account.status !== 'linked'} onClick={() => execute('Diagnosticar PS4 via PSN', async () => {
            const response = await post<Ps4Diagnostic>(path + '/diagnose/ps4-psn');
            return <div className="stack"><span>{response.message}</span>{response.duid && <span>DUID <code>{response.duid}</code></span>}</div>;
          })}>Diagnosticar PS4 via PSN</button>
        </>}
        {platform === 'PS5' && <button className="btn" disabled={busy || account.status !== 'linked'} onClick={() => execute('Consultar PS5', async () => {
          const response = await post<{ devices: PsnDevice[] }>(path + '/devices');
          return <DataTable rows={response.devices} empty="Nenhum PS5 retornado pela Sony." cols={[
            ['Nome', (item) => item.name], ['Remote Play', (item) => item.remoteplay_enabled ? 'Habilitado' : 'Indisponível'],
            ['DUID', (item) => <code>{item.duid}</code>],
          ]} />;
        })}>Consultar PS5</button>}
        {canImport && <button className="btn" disabled={busy || !canTest} onClick={() => execute('Importar Chiaki', async () => {
          await post(path + '/import/chiaki'); onChange();
          return 'Credencial importada. Execute o teste de autenticação.';
        })}>Importar Chiaki</button>}
        <button className="btn danger psn-unlink" disabled={busy || account.status === 'disabled'} onClick={() => setConfirmUnlink(true)}>Desvincular</button>
      </div>}
      {confirmUnlink && <div className="card stack">
        <p>A conta {account.label} ficará indisponível para novas conexões.</p>
        <div className="row">
          <button className="btn danger psn-unlink" onClick={() => execute('Desvincular', async () => {
            await patch(path, { status: 'disabled' }); setLoginUrl(''); setRedirect(''); onChange();
            return 'Conta PSN desvinculada.';
          })}>Confirmar desvinculação</button>
          <button className="btn" onClick={() => setConfirmUnlink(false)}>Cancelar</button>
        </div>
      </div>}
      {loginUrl && <SonyLoginForm url={loginUrl} value={redirect} onChange={setRedirect} busy={busy}
        onSubmit={() => execute('Concluir vínculo', async () => {
          await post(path + '/login/finish', { redirect_url: redirect.trim() });
          setLoginUrl(''); setRedirect(''); onChange();
          return 'Conta vinculada à PSN.';
        })} />}
      {busy && <p role="status">Executando ação…</p>}
      {result && <section className="card stack psn-action-result" role={result.error ? 'alert' : 'status'}>
        <h3>{result.label}</h3><div className={result.error ? 'err' : undefined}>{result.content}</div>
      </section>}
    </div>
  </Modal>;
}

export default function PsnAccounts({ onAccountsChanged, initialPlatform = 'all' }: {
  onAccountsChanged?: () => void; initialPlatform?: string;
} = {}) {
  const accounts = useApi<Account[]>('/admin/psn-accounts', 5000);
  const options = useApi<{ chiaki_import_enabled: boolean }>('/admin/psn-accounts/options');
  const agents = useApi<Agent[]>('/admin/agents');
  const [newLabel, setNewLabel] = useState('');
  const [agentId, setAgentId] = useState('');
  const [draft, setDraft] = useState(FILTERS);
  const [filters, setFilters] = useState(FILTERS);
  const [actionAccountId, setActionAccountId] = useState<string | null>(null);
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const refresh = () => { void accounts.reload(); onAccountsChanged?.(); };
  const account = accounts.data?.find((item) => item.id === actionAccountId);
  const query = filters.search.trim().toLocaleLowerCase('pt-BR');
  const agentOptions = agents.data?.filter((a) => !a.is_simulated).map((a) => <option value={a.id} key={a.id}>{a.name}</option>);
  const rows = accounts.data?.filter((a) =>
    (!query || [a.label, a.online_id, a.agent_name].some((field) => field?.toLocaleLowerCase('pt-BR').includes(query)))
    && (!filters.agent || a.agent_id === filters.agent)
    && (!filters.status || a.status === filters.status)
    && (!filters.platform || (filters.platform === 'unlinked' ? !a.platforms?.length : a.platforms?.includes(filters.platform as Platform)))) ?? null;

  return (
    <div className="stack">
      <PageHeader title="Contas PSN" subtitle="Vincule contas PlayStation aos agentes e consulte a autenticação de cada conta." />
      {msg}{deletion.dialog}
      <NewRecord title="Nova conta PSN">{(close) => <>
        <div className="grid2">
          <Field label="Rótulo interno"><input maxLength={80} value={newLabel} onChange={(e) => setNewLabel(e.target.value)} /></Field>
          <Field label="Agente Windows"><select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Selecione um agente</option>{agentOptions}
          </select></Field>
        </div>
        <div><button className="btn primary" disabled={busy || !agentId || newLabel.trim().length < 2} onClick={() => run(async () => {
          await post('/admin/psn-accounts', { label: newLabel.trim(), agent_id: agentId });
          setNewLabel(''); refresh(); close();
        }, 'Conta cadastrada. Use Ações para vincular à Sony.')}>Cadastrar conta</button></div>
      </>}</NewRecord>
      <section className="card stack">
        <h2>Contas vinculadas ao agente</h2>
        <form className="stack psn-filters" onSubmit={(e) => { e.preventDefault(); setFilters(draft); }}>
          <div className="psn-filter-grid">
            <Field label="Buscar conta"><input type="search" placeholder="Rótulo, PSN ID ou agente" value={draft.search} onChange={(e) => setDraft({ ...draft, search: e.target.value })} /></Field>
            <Field label="Agente"><select value={draft.agent} onChange={(e) => setDraft({ ...draft, agent: e.target.value })}>
              <option value="">Todos</option>{agentOptions}
            </select></Field>
            <Field label="Estado"><select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
              <option value="">Todos</option>{Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select></Field>
            <Field label="Plataforma"><select value={draft.platform} onChange={(e) => setDraft({ ...draft, platform: e.target.value })}>
              <option value="">Todas</option><option>PS4</option><option>PS5</option><option value="unlinked">Sem console vinculado</option>
            </select></Field>
          </div>
          <div className="row">
            <button className="btn primary" type="submit">Filtrar</button>
            <button className="btn" type="button" onClick={() => { setDraft(FILTERS); setFilters(FILTERS); }}>Limpar filtros</button>
          </div>
        </form>
        <DataTable<Account> rows={rows} error={accounts.error?.message} cols={[
          ['Rótulo', (a) => <b>{a.label}</b>], ['Agente', (a) => a.agent_name ?? 'Aguardando agente'],
          ['PSN ID', (a) => a.online_id || '—'], ['Plataforma', (a) => a.platforms?.join(', ') || '—'],
          ['Estado', (a) => <StatusPill status={a.status} map={STATUS} />],
          ['Última verificação', (a) => dateTime(a.last_check_at)],
          ['Ações', (a) => <div className="row">
            <button className="btn sm" onClick={() => setActionAccountId(a.id)}>Ações</button>
            <button className="btn sm danger" disabled={busy} onClick={() => deletion.remove(
              `/admin/psn-accounts/${a.id}`, 'Excluir conta PSN?',
              (request) => run(async () => { await request(); refresh(); }, 'Conta excluída do agente e do banco.'),
              `Os tokens da conta ${a.label} serão eliminados do agente.`,
            )}>Excluir</button>
          </div>],
        ]} />
        {rows?.filter((a) => a.last_error).map((a) => <div className="small muted" key={a.id}>{a.label}: {a.last_error}</div>)}
      </section>
      {account && <AccountActions key={account.id} account={account} initialPlatform={filters.platform || initialPlatform}
        canImport={Boolean(options.data?.chiaki_import_enabled)} onChange={refresh} onClose={() => setActionAccountId(null)} />}
    </div>
  );
}
