'use client';
import { useState } from 'react';
import { Alert, Field, FieldHelp, Modal, PageHeader, StatusPill } from '@/components/ui';
import { del, patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, need, NewRecord, useAction, useDelete } from './common';

const AGENT_STATUS: Record<string, string> = { online: 'online', offline: 'offline', degraded: 'instável', unknown: 'aguardando primeiro sinal' };

const EMPTY_AGENT = { name: '', host_name: '', endpoint_url: '', location: '', is_simulated: false };
const EMPTY_CAPTURE = { agent_id: '', manufacturer: '', model: '', device_identifier: '', input_port: 'HDMI-1', supports_simultaneous_inputs: false };
const EMPTY_CONTROL = { agent_id: '', adapter_type: 'usb_controller_interface', identifier: '', manufacturer: '', model: '', authorized: false };

type AgentTokens = { agent_token: string; api_to_agent_token: string };
type AgentCredentials = { tokens: AgentTokens; config?: Record<string, unknown> };
type AgentRow = Record<string, unknown>;
type ConfigTargetFile = { handle: FileSystemFileHandle; directory: string; empty: boolean };
type ConfigPickerWindow = Window & {
  showDirectoryPicker?: (options: { mode: 'readwrite'; id: string }) => Promise<FileSystemDirectoryHandle>;
};

function isLocalAgent(endpoint: string) {
  return /^http:\/\/127\.0\.0\.1(?=[:/]|$)/.test(endpoint);
}

function agentConfig(tokens: AgentTokens, endpoint: string, existing: Record<string, unknown> = {}) {
  return {
    api_url: isLocalAgent(endpoint) ? 'http://127.0.0.1:8000' : `${window.location.origin}/api`,
    listen_host: '127.0.0.1',
    listen_port: 8765,
    ...existing,
    agent_token: tokens.agent_token,
    api_to_agent_token: tokens.api_to_agent_token,
  };
}

function downloadConfig(config: Record<string, unknown>) {
  const file = new Blob([JSON.stringify(config, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'config.json';
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function readConfig(file: FileSystemFileHandle) {
  const text = (await (await file.getFile()).text()).replace(/^\uFEFF/, '');
  if (!text.trim()) return null;
  let data: unknown;
  try { data = JSON.parse(text); }
  catch { throw new Error('O config.json selecionado não contém JSON válido. Confira o arquivo antes de continuar.'); }
  need(data !== null && typeof data === 'object' && !Array.isArray(data), 'O config.json precisa conter um objeto JSON.');
  return data as Record<string, unknown>;
}

async function writeConfig(file: FileSystemFileHandle, config: Record<string, unknown>) {
  await commitConfig(await file.createWritable(), config);
}

async function commitConfig(writable: FileSystemWritableFileStream, config: Record<string, unknown>) {
  try {
    await writable.write(JSON.stringify(config, null, 2) + '\n');
    await writable.close();
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
}

function formValues<T extends Record<string, string | boolean>>(initial: T, row: Record<string, unknown>): T {
  return Object.fromEntries(Object.entries(initial).map(([key, value]) => [key,
    typeof value === 'boolean' ? row[key] === true : String(row[key] ?? value),
  ])) as T;
}

const CONFIG_HELP = 'Selecione a pasta que contém o config.json no PC do ConsoleAgent. Na instalação padrão, a pasta é E:\\LocadoraOnline\\locaplay\\agent. Autorize a pasta quando o navegador solicitar. O painel grava somente depois de confirmar a ação.';

function AgentFields({ value, onChange }: { value: typeof EMPTY_AGENT; onChange: (value: typeof EMPTY_AGENT) => void }) {
  return <>
    <Field label="Nome" help="Nome exibido no painel."><input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} /></Field>
    <Field label="Host" help="Nome de rede ou IP do computador do agente."><input maxLength={253} value={value.host_name} onChange={(e) => onChange({ ...value, host_name: e.target.value })} /></Field>
    <Field label="Endpoint do agente" help="Endereço que o FastAPI consegue alcançar. Para outro PC, use HTTPS acessível pela rede ou VPN." hint="No mesmo PC do FastAPI em homologação: http://127.0.0.1:8765"><input maxLength={500} value={value.endpoint_url} onChange={(e) => onChange({ ...value, endpoint_url: e.target.value })} placeholder="https://agente-01.vpn.local" /></Field>
    <Field label="Localização" help="Local físico do agente."><input maxLength={120} value={value.location} onChange={(e) => onChange({ ...value, location: e.target.value })} /></Field>
  </>;
}

function agentPayload(value: typeof EMPTY_AGENT) {
  const { is_simulated, ...agent } = value;
  need(agent.name.trim().length >= 2, 'Informe o nome do agente (mínimo 2 caracteres).');
  need(agent.host_name.trim(), 'Informe o host do agente.');
  const endpoint = agent.endpoint_url.trim();
  need(!endpoint || endpoint.startsWith('https://') || isLocalAgent(endpoint), 'Use HTTPS ou o endereço local do FastAPI em homologação.');
  return { ...agent, endpoint_url: endpoint || null };
}

async function chooseConfig() {
  const browser = window as ConfigPickerWindow;
  if (!browser.showDirectoryPicker) return;
  let directory: FileSystemDirectoryHandle;
  try {
    directory = await browser.showDirectoryPicker({ mode: 'readwrite', id: 'consoleagent-config' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    throw error;
  }
  try {
    const handle = await directory.getFileHandle('config.json');
    const existing = await readConfig(handle);
    return { handle, directory: directory.name, empty: existing === null };
  } catch (error) {
    if (error instanceof DOMException && error.name === 'NotFoundError') {
      throw new Error('A pasta selecionada não contém config.json. Selecione a pasta locaplay\\agent do ConsoleAgent.');
    }
    throw error;
  }
}

function supportsConfigPicker() {
  if (typeof window === 'undefined') return false;
  const browser = window as ConfigPickerWindow;
  return Boolean(browser.showDirectoryPicker);
}

function ConfigTarget({ file, onFile, disabled }: {
  file: ConfigTargetFile | null; onFile: (file: ConfigTargetFile | null) => void; disabled: boolean;
}) {
  const [feedback, setFeedback] = useState('');
  const supported = supportsConfigPicker();
  if (!supported) return <p className="small muted">Use Chrome ou Edge para autorizar a gravação no config.json.</p>;
  return <div className="stack">
    <div className="row">
      <button type="button" className="btn sm" disabled={disabled} onClick={async () => {
        try {
          const selected = await chooseConfig();
          if (!selected) return;
          onFile(selected);
          setFeedback('');
        } catch (error) { setFeedback(error instanceof Error ? error.message : 'Não foi possível selecionar o arquivo.'); }
      }}>{file ? 'Trocar pasta selecionada' : 'Selecionar pasta'}</button>
      <FieldHelp text={CONFIG_HELP} />
    </div>
    {file && <div role="status">
      <strong>Arquivo selecionado</strong> <code>{file.directory}/{file.handle.name}</code>
      {file.empty && <p className="small muted">O arquivo está vazio. Ao confirmar, o painel vai gerar a configuração básica com os tokens do agente.</p>}
    </div>}
    {feedback && <p className="small" role="status">{feedback}</p>}
  </div>;
}

const ACTIONS = [
  ['edit', 'Editar agente'],
  ['rotate', 'Rotacionar tokens'],
  ['download', 'Baixar config.json'],
  ['update', 'Atualizar config.json existente'],
  ['delete', 'Excluir agente'],
] as const;

function AgentActions({ agent, credentials, onCredentials, onChange, onClose, initialSummary }: {
  agent: AgentRow; credentials?: AgentCredentials; onCredentials: (value: AgentCredentials | null) => void;
  onChange: () => void; onClose: () => void; initialSummary?: string;
}) {
  const [action, setAction] = useState('');
  const [record, setRecord] = useState(agent);
  const [draft, setDraft] = useState(() => formValues(EMPTY_AGENT, agent));
  const [file, setFile] = useState<ConfigTargetFile | null>(null);
  const [reason, setReason] = useState('');
  const [summary, setSummary] = useState(initialSummary ?? '');
  const [error, setError] = useState('');
  const [copy, setCopy] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const endpoint = String(record.endpoint_url ?? '');

  async function execute() {
    if (!action || busy || deleted) return;
    setBusy(true);
    setError('');
    setSummary('');
    setCopy('');
    try {
      const base = `/admin/agents/${agent.id}`;
      switch (action) {
        case 'edit': {
          const payload = agentPayload(draft);
          await patch(base, payload);
          setRecord({ ...record, ...payload });
          setSummary('Dados do agente atualizados.');
          break;
        }
        case 'rotate': {
          if (!file) throw new Error('Selecione o config.json e autorize a gravação antes de rotacionar.');
          const existing = (await readConfig(file.handle)) ?? undefined;
          const writable = await file.handle.createWritable();
          let tokens: AgentTokens;
          try {
            tokens = await post<AgentTokens>(`${base}/rotate-credentials`);
          } catch (failure) {
            await writable.abort().catch(() => {});
            throw failure;
          }
          const config = agentConfig(tokens, endpoint, existing);
          onCredentials({ tokens, config });
          try {
            await commitConfig(writable, config);
            setSummary(`Tokens rotacionados e gravados automaticamente em ${file.handle.name}. Reinicie o ConsoleAgent.`);
          } catch {
            setError('Os tokens foram rotacionados, mas o navegador não conseguiu concluir a gravação. Selecione Atualizar config.json existente para tentar novamente com os mesmos tokens.');
          }
          break;
        }
        case 'download':
          if (!credentials) throw new Error('Rotacione os tokens para gerar o arquivo.');
          downloadConfig(credentials.config ?? agentConfig(credentials.tokens, endpoint));
          setSummary('Download do config.json iniciado.');
          break;
        case 'update': {
          if (!credentials) throw new Error('Gere os tokens para atualizar o config.json.');
          if (!file) throw new Error('Selecione o config.json antes de executar.');
          await writeConfig(file.handle, agentConfig(credentials.tokens, endpoint, (await readConfig(file.handle)) ?? undefined));
          setSummary('Tokens gravados no config.json. Reinicie o ConsoleAgent para aplicar a atualização.');
          break;
        }
        case 'delete':
          need(reason.trim(), 'Informe o motivo da exclusão.');
          await del(base, { reason: reason.trim() });
          setDeleted(true);
          onCredentials(null);
          setSummary('Agente excluído.');
          break;
      }
      setAction('');
      onChange();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Não foi possível executar a ação.');
    } finally { setBusy(false); }
  }

  return <Modal title="Ações do agente" onClose={() => { if (!busy) onClose(); }}>
    <div className="stack">
      <dl className="kv">
        <dt>Nome</dt><dd>{String(record.name)}</dd>
        <dt>Host</dt><dd>{String(record.host_name)}</dd>
        <dt>Endpoint</dt><dd style={{ overflowWrap: 'anywhere' }}>{endpoint || '—'}</dd>
        <dt>Localização</dt><dd>{String(record.location || '—')}</dd>
        <dt>Status</dt><dd><StatusPill status={String(record.status)} map={AGENT_STATUS} /></dd>
        <dt>Último heartbeat</dt><dd>{dateTime(record.last_heartbeat_at as string)}</dd>
      </dl>
      {!deleted && <form className="stack" onSubmit={(event) => { event.preventDefault(); void execute(); }}>
        <Field label="Ação"><select value={action} disabled={busy} onChange={(event) => setAction(event.target.value)}>
          <option value="">Selecione uma ação</option>
          {ACTIONS.map(([value, label]) => <option key={value} value={value}
            disabled={((value === 'download' || value === 'update') && !credentials) ||
              (value === 'update' && !supportsConfigPicker())}>{label}</option>)}
        </select></Field>
        {action === 'edit' && <AgentFields value={draft} onChange={setDraft} />}
        {action === 'rotate' && <p className="small muted">Selecione o config.json antes de executar. Depois da autorização de gravação, o sistema substitui os tokens no arquivo e invalida os anteriores.</p>}
        {(action === 'update' || action === 'rotate') && <ConfigTarget file={file} onFile={setFile} disabled={busy} />}
        {action === 'delete' && <Field label="Motivo da exclusão" required>
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} rows={3} />
        </Field>}
        <button className={`btn ${action === 'delete' ? 'danger' : 'primary'}`} type="submit"
          disabled={!action || busy || ((action === 'update' || action === 'rotate') && !file) || (action === 'delete' && !reason.trim())}>{busy ? 'Executando…' : 'Executar'}</button>
      </form>}
      {summary && <p role="status">{summary}</p>}
      {error && <p role="alert" className="field invalid"><span className="err">{error}</span></p>}
      {credentials && !deleted && <section className="stack" aria-label="Credenciais do agente">
        {([['agent_token', 'Token agente → API'], ['api_to_agent_token', 'Token API → agente']] as const).map(([key, label]) => <div key={key} className="row">
          <div style={{ flex: '1 1 240px', minWidth: 0 }}><Field label={label}><input readOnly value={credentials.tokens[key]} spellCheck={false} autoComplete="off" /></Field></div>
          <button className="btn sm" type="button" aria-label={`Copiar ${label.toLowerCase()}`} onClick={async () => {
            try { await navigator.clipboard.writeText(credentials.tokens[key]); setCopy(`${label} copiado.`); }
            catch { setCopy('Selecione e copie o token no campo.'); }
          }}>Copiar</button>
        </div>)}
        {copy && <p className="small" role="status">{copy}</p>}
      </section>}
    </div>
  </Modal>;
}

export default function Agents() {
  const agents = useApi<Record<string, unknown>[]>('/admin/agents', 15000);
  const caps = useApi<Record<string, unknown>[]>('/admin/capture-devices');
  const ctls = useApi<Record<string, unknown>[]>('/admin/control-adapters');
  const [a, setA] = useState(EMPTY_AGENT);
  const [c, setC] = useState(EMPTY_CAPTURE);
  const [k, setK] = useState(EMPTY_CONTROL);
  const [cId, setCId] = useState('');
  const [kId, setKId] = useState('');
  const [credentialsByAgent, setCredentialsByAgent] = useState<Record<string, AgentCredentials>>({});
  const [selectedAgent, setSelectedAgent] = useState<{ row: AgentRow; summary?: string } | null>(null);
  const [configFile, setConfigFile] = useState<ConfigTargetFile | null>(null);
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const agentOpts = agents.data?.filter((x) => !x.is_simulated).map((x) => <option key={String(x.id)} value={String(x.id)}>{String(x.name)}</option>);

  function saveCredentials(id: string, value: AgentCredentials | null) {
    setCredentialsByAgent((current) => {
      const next = { ...current };
      if (value) next[id] = value;
      else delete next[id];
      return next;
    });
  }

  return (
    <div className="stack">
      <PageHeader title="Agentes locais e dispositivos" subtitle="PC ao lado dos consoles: captura, encode, stream e interfaces de controle." />
      {msg}
      {deletion.dialog}
      {selectedAgent && <AgentActions key={String(selectedAgent.row.id)} agent={selectedAgent.row}
        credentials={credentialsByAgent[String(selectedAgent.row.id)]}
        onCredentials={(value) => saveCredentials(String(selectedAgent.row.id), value)}
        initialSummary={selectedAgent.summary} onChange={agents.reload} onClose={() => setSelectedAgent(null)} />}
      <section className="card stack"><h2>Agentes</h2>
        <NewRecord title="Novo agente" onClose={() => { setA(EMPTY_AGENT); setConfigFile(null); }}>{(close) => <>
          <div className="grid3">
            <AgentFields value={a} onChange={setA} />
            <div className="row"><label className="check"><input type="checkbox" checked={a.is_simulated} onChange={(e) => setA({ ...a, is_simulated: e.target.checked })} />Agente SIMULADO (desenvolvimento)</label><FieldHelp text="Agente de desenvolvimento que opera sem console físico." /></div>
          </div>
          {!a.is_simulated && <ConfigTarget file={configFile} onFile={setConfigFile} disabled={busy} />}
          <button className="btn primary" disabled={busy} onClick={() => run(async () => {
            const payload = agentPayload(a);
            const file = a.is_simulated ? null : configFile;
            const existing = file ? (await readConfig(file.handle)) ?? undefined : undefined;
            const result = await post<AgentTokens & { id: string }>('/admin/agents', { ...payload, is_simulated: a.is_simulated });
            let summary = 'Agente cadastrado. Aguardando o primeiro sinal.';
            if (!a.is_simulated) {
              const config = agentConfig(result, payload.endpoint_url ?? '', existing);
              saveCredentials(result.id, { tokens: { agent_token: result.agent_token, api_to_agent_token: result.api_to_agent_token }, config });
              if (file) {
                try {
                  await writeConfig(file.handle, config);
                  summary = 'Agente cadastrado e tokens gravados no config.json. Inicie ou reinicie o ConsoleAgent.';
                } catch {
                  summary = 'Agente cadastrado. Não foi possível gravar no arquivo selecionado. Use Atualizar config.json existente ou Baixar config.json.';
                }
              } else {
                summary = 'Agente cadastrado. Escolha Baixar config.json para transferir as credenciais ao PC do agente.';
              }
            }
            agents.reload();
            close();
            setSelectedAgent({ row: { ...payload, id: result.id, status: 'unknown' }, summary });
          })}>{!a.is_simulated && configFile ? 'Cadastrar e atualizar config.json' : 'Cadastrar'}</button>
        </>}</NewRecord>
        <DataTable rows={agents.data} error={agents.error?.message} cols={[['Nome', (r) => String(r.name)], ['Host', (r) => String(r.host_name)], ['Status', (r) => <StatusPill status={String(r.status)} map={AGENT_STATUS} tone={({ online: 'green', offline: 'red', degraded: 'amber', unknown: '' } as Record<string, string>)[String(r.status)]} />], ['Simulado', (r) => (r.is_simulated ? 'sim' : 'não')],
          ['Último heartbeat', (r) => dateTime(r.last_heartbeat_at as string)], ['Ações', (r) => <button className="btn sm" onClick={() => setSelectedAgent({ row: r })}>Ações</button>]]} />
      </section>
      <section className="card stack"><h2>Capturadoras HDMI</h2>
        <p className="small muted">Cada console precisa de uma entrada de captura independente. Saída HDMI de notebook não é capturadora. Respeite HDCP/DRM.</p>
        <NewRecord title="Nova capturadora" editingTitle={cId ? "Editar capturadora" : undefined} onClose={() => { setCId(''); setC(EMPTY_CAPTURE); }}>{(close) => <><div className="grid3"><Field label="Agente" help="Computador que controla o dispositivo."><select value={c.agent_id} onChange={(e) => setC({ ...c, agent_id: e.target.value })}><option value="">Selecione</option>{agentOpts}</select></Field>
          <Field label="Fabricante" help="Empresa responsável pelo equipamento."><input value={c.manufacturer} onChange={(e) => setC({ ...c, manufacturer: e.target.value })} /></Field>
          <Field label="Modelo" help="Modelo do equipamento."><input value={c.model} onChange={(e) => setC({ ...c, model: e.target.value })} /></Field>
          <Field label="Device ID" help="Identificador da capturadora no sistema operacional."><input value={c.device_identifier} onChange={(e) => setC({ ...c, device_identifier: e.target.value })} /></Field>
          <Field label="Entrada" help="Porta física que recebe o sinal HDMI."><input value={c.input_port} onChange={(e) => setC({ ...c, input_port: e.target.value })} /></Field>
          <div className="row"><label className="check"><input type="checkbox" checked={c.supports_simultaneous_inputs} onChange={(e) => setC({ ...c, supports_simultaneous_inputs: e.target.checked })} />Captura entradas simultaneamente</label><FieldHelp text="O dispositivo consegue transmitir várias entradas ao mesmo tempo." /></div></div>
        <button className="btn primary" disabled={busy} onClick={() => run(async () => {
          need(c.agent_id, 'Selecione o agente da capturadora.');
          need(c.manufacturer.trim() && c.model.trim(), 'Informe fabricante e modelo da capturadora.');
          need(c.device_identifier.trim(), 'Informe o Device ID da capturadora.');
          need(c.input_port.trim(), 'Informe a entrada (ex.: HDMI-1).');
          if (cId) await patch(`/admin/capture-devices/${cId}`, c);
          else await post('/admin/capture-devices', c); caps.reload(); close(); }, cId ? 'Capturadora atualizada.' : 'Capturadora cadastrada.')}>{cId ? 'Salvar' : 'Cadastrar'}</button></>}</NewRecord>
        <DataTable rows={caps.data} error={caps.error?.message} cols={[['Agente', (r) => String(r.agent_name)], ['Dispositivo', (r) => `${r.manufacturer} ${r.model}`], ['ID / entrada', (r) => `${r.device_identifier} · ${r.input_port}`],
          ['Em uso', (r) => (r.used_by_console ? 'sim' : 'não')], ['Ações', (r) => <div className="row"><button className="btn sm" onClick={() => { setC(formValues(EMPTY_CAPTURE, r)); setCId(String(r.id)); }}>Editar</button><button className="btn sm danger" onClick={() => deletion.remove(`/admin/capture-devices/${r.id}`, 'Excluir capturadora?', (request) => run(async () => { await request(); caps.reload(); }, 'Exclusão concluída.'))}>Excluir</button></div>]]} />
      </section>
      <section className="card stack"><h2>Adaptadores de controle</h2>
        <NewRecord title="Novo adaptador" editingTitle={kId ? "Editar adaptador" : undefined} onClose={() => { setKId(''); setK(EMPTY_CONTROL); }}>{(close) => <><div className="grid3"><Field label="Agente" help="Computador que controla o dispositivo."><select value={k.agent_id} onChange={(e) => setK({ ...k, agent_id: e.target.value })}><option value="">Selecione</option>{agentOpts}</select></Field>
          <Field label="Tipo" help="Interface usada para enviar comandos."><select value={k.adapter_type} onChange={(e) => setK({ ...k, adapter_type: e.target.value })}><option value="usb_controller_interface">Interface USB</option><option value="bluetooth_controller_interface">Interface Bluetooth</option><option value="remote_play_input">Entrada via Remote Play</option><option value="other">Outro</option></select></Field>
          <Field label="Identificador" help="Identificador usado pelo agente para localizar o adaptador."><input value={k.identifier} onChange={(e) => setK({ ...k, identifier: e.target.value })} /></Field>
          <div className="row"><label className="check"><input type="checkbox" checked={k.authorized} onChange={(e) => setK({ ...k, authorized: e.target.checked })} />Compatível e autorizado (verificado)</label><FieldHelp text="Autoriza o uso deste adaptador após verificar a compatibilidade." /></div></div>
        <button className="btn primary" disabled={busy} onClick={() => run(async () => {
          need(k.agent_id, 'Selecione o agente do adaptador de controle.');
          need(k.identifier.trim(), 'Informe o identificador do adaptador.');
          if (kId) await patch(`/admin/control-adapters/${kId}`, k);
          else await post('/admin/control-adapters', k); ctls.reload(); close(); }, kId ? 'Adaptador atualizado.' : 'Adaptador cadastrado.')}>{kId ? 'Salvar' : 'Cadastrar'}</button></>}</NewRecord>
        <DataTable rows={ctls.data} error={ctls.error?.message} cols={[['Agente', (r) => String(r.agent_name)], ['Tipo', (r) => String(r.adapter_type)], ['Identificador', (r) => String(r.identifier)],
          ['Autorizado', (r) => (r.authorized ? 'sim' : 'não')], ['Em uso', (r) => (r.used_by_console ? 'sim' : 'não')],
          ['Ações', (r) => <div className="row"><button className="btn sm" onClick={() => { setK(formValues(EMPTY_CONTROL, r)); setKId(String(r.id)); }}>Editar</button><button className="btn sm danger" onClick={() => deletion.remove(`/admin/control-adapters/${r.id}`, 'Excluir adaptador?', (request) => run(async () => { await request(); ctls.reload(); }, 'Exclusão concluída.'))}>Excluir</button></div>]]} />
      </section>
    </div>
  );
}
