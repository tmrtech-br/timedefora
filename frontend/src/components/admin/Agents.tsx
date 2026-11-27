'use client';
import { useState } from 'react';
import { Alert, Field, FieldHelp, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, need, NewRecord, useAction, useDelete } from './common';

const AGENT_STATUS: Record<string, string> = { online: 'online', offline: 'offline', degraded: 'instável', unknown: 'aguardando primeiro sinal' };

const EMPTY_AGENT = { name: '', host_name: '', endpoint_url: '', location: '', is_simulated: false };
const EMPTY_CAPTURE = { agent_id: '', manufacturer: '', model: '', device_identifier: '', input_port: 'HDMI-1', supports_simultaneous_inputs: false };
const EMPTY_CONTROL = { agent_id: '', adapter_type: 'usb_controller_interface', identifier: '', manufacturer: '', model: '', authorized: false };

type AgentTokens = { agent_token: string; api_to_agent_token: string };
type ConfigHandle = FileSystemFileHandle & {
  requestPermission(options: { mode: 'readwrite' }): Promise<PermissionState>;
};
type ConfigPickerWindow = Window & {
  showOpenFilePicker?: (options: {
    types: { description: string; accept: Record<string, string[]> }[];
  }) => Promise<ConfigHandle[]>;
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

async function readConfig(file: ConfigHandle) {
  const data: unknown = JSON.parse((await (await file.getFile()).text()).replace(/^\uFEFF/, ''));
  need(data !== null && typeof data === 'object' && !Array.isArray(data), 'O config.json precisa conter um objeto JSON.');
  return data as Record<string, unknown>;
}

async function writeConfig(file: ConfigHandle, config: Record<string, unknown>) {
  const writable = await file.createWritable();
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

export default function Agents() {
  const agents = useApi<Record<string, unknown>[]>('/admin/agents', 15000);
  const caps = useApi<Record<string, unknown>[]>('/admin/capture-devices');
  const ctls = useApi<Record<string, unknown>[]>('/admin/control-adapters');
  const [a, setA] = useState(EMPTY_AGENT);
  const [c, setC] = useState(EMPTY_CAPTURE);
  const [k, setK] = useState(EMPTY_CONTROL);
  const [aId, setAId] = useState('');
  const [cId, setCId] = useState('');
  const [kId, setKId] = useState('');
  const [secret, setSecret] = useState<{ tokens: AgentTokens; endpoint: string; config?: Record<string, unknown> } | null>(null);
  const [configFile, setConfigFile] = useState<ConfigHandle | null>(null);
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const agentOpts = agents.data?.filter((x) => !x.is_simulated).map((x) => <option key={String(x.id)} value={String(x.id)}>{String(x.name)}</option>);
  const canSelectConfig = typeof window !== 'undefined' && Boolean((window as ConfigPickerWindow).showOpenFilePicker);

  async function chooseConfig() {
    const picker = (window as ConfigPickerWindow).showOpenFilePicker;
    if (!picker) return;
    try {
      const [handle] = await picker.call(window, {
        types: [{ description: 'Configuração do ConsoleAgent', accept: { 'application/json': ['.json'] } }],
      });
      if (handle.name !== 'config.json') throw new Error('Selecione o arquivo config.json do ConsoleAgent.');
      if (await handle.requestPermission({ mode: 'readwrite' }) !== 'granted') {
        throw new Error('Permita a gravação para atualizar o arquivo selecionado.');
      }
      return handle;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      throw error;
    }
  }

  return (
    <div className="stack">
      <PageHeader title="Agentes locais e dispositivos" subtitle="PC ao lado dos consoles: captura, encode, stream e interfaces de controle." />
      {msg}
      {deletion.dialog}
      {secret && <Alert kind="warn" dismissible={false}>
        <span>O config.json contém credenciais. Mantenha-o no computador do agente.{' '}
          <button type="button" className="btn sm" onClick={() => downloadConfig(secret.config ?? agentConfig(secret.tokens, secret.endpoint))}>Baixar config.json</button>{' '}
          {canSelectConfig && <button type="button" className="btn sm" disabled={busy} onClick={() => run(async () => {
            const file = await chooseConfig();
            if (!file) return;
            await writeConfig(file, agentConfig(secret.tokens, secret.endpoint, await readConfig(file)));
            setSecret(null);
          }, '')}>Atualizar config.json existente</button>}{' '}
          <button type="button" className="btn sm" onClick={() => setSecret(null)}>Fechar</button>
        </span>
      </Alert>}
      <section className="card stack"><h2>Agentes</h2><NewRecord title="Novo agente" editingTitle={aId ? "Editar agente" : undefined} onClose={() => { setAId(''); setA(EMPTY_AGENT); setConfigFile(null); }}>{(close) => <><div className="grid3">
        <Field label="Nome" help="Nome exibido no painel."><input value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></Field>
        <Field label="Host" help="Nome de rede ou IP do computador do agente."><input maxLength={253} value={a.host_name} onChange={(e) => setA({ ...a, host_name: e.target.value })} /></Field>
        <Field label="Endpoint do agente" help="Endereço que o FastAPI consegue alcançar. Para outro PC, use HTTPS acessível pela rede ou VPN." hint="Em homologação, com o agente no mesmo PC do FastAPI: http://127.0.0.1:8765"><input maxLength={500} value={a.endpoint_url} onChange={(e) => setA({ ...a, endpoint_url: e.target.value })} placeholder="https://agente-01.vpn.local" /></Field>
        <Field label="Localização" help="Local físico do agente."><input maxLength={120} value={a.location} onChange={(e) => setA({ ...a, location: e.target.value })} /></Field>
        {!aId && <div className="row"><label className="check"><input type="checkbox" checked={a.is_simulated} onChange={(e) => setA({ ...a, is_simulated: e.target.checked })} />Agente SIMULADO (desenvolvimento)</label><FieldHelp text="Agente de desenvolvimento que opera sem console físico." /></div>}</div>
        {!aId && !a.is_simulated && canSelectConfig && <div className="row">
          <button type="button" className="btn" disabled={busy} onClick={() => run(async () => {
            const file = await chooseConfig();
            if (file) setConfigFile(file);
          }, '')}>
            {configFile ? 'Trocar config.json selecionado' : 'Selecionar config.json existente'}
          </button>
          {configFile && <button type="button" className="btn sm" onClick={() => setConfigFile(null)}>Usar download</button>}
        </div>}
        <button className="btn primary" disabled={busy} onClick={() => run(async () => {
          need(a.name.trim().length >= 2, 'Informe o nome do agente (mínimo 2 caracteres).');
          need(a.host_name.trim(), 'Informe o host do agente.');
          need(!a.endpoint_url || /^https?:\/\//.test(a.endpoint_url), 'O endpoint deve começar com https:// (ou http:// em desenvolvimento).');
          const { is_simulated, ...agent } = a;
          const payload = { ...agent, endpoint_url: a.endpoint_url || null };
          const file = is_simulated ? null : configFile;
          const existing = file ? await readConfig(file) : undefined;
          if (aId) {
            await patch(`/admin/agents/${aId}`, payload);
          } else {
            const tokens = await post<AgentTokens>('/admin/agents', { ...payload, is_simulated });
            if (!is_simulated) {
              const config = agentConfig(tokens, a.endpoint_url, existing);
              if (file) {
                try {
                  await writeConfig(file, config);
                } catch {
                  setSecret({ tokens, endpoint: a.endpoint_url, config });
                  downloadConfig(config);
                }
              } else {
                setSecret({ tokens, endpoint: a.endpoint_url });
                downloadConfig(config);
              }
            }
          }
          agents.reload();
          close();
        }, aId ? 'Agente atualizado.' : 'Agente cadastrado.')}>{aId ? 'Salvar' : 'Cadastrar'}</button></>}</NewRecord>
        <DataTable rows={agents.data} error={agents.error?.message} cols={[['Nome', (r) => String(r.name)], ['Host', (r) => String(r.host_name)], ['Status', (r) => <StatusPill status={String(r.status)} map={AGENT_STATUS} tone={({ online: 'green', offline: 'red', degraded: 'amber', unknown: '' } as Record<string, string>)[String(r.status)]} />], ['Simulado', (r) => (r.is_simulated ? 'sim' : 'não')],
          ['Último heartbeat', (r) => dateTime(r.last_heartbeat_at as string)], ['Ações', (r) => <div className="row"><button className="btn sm" disabled={busy} onClick={() => run(async () => {
            const tokens = await post<AgentTokens>(`/admin/agents/${r.id}/rotate-credentials`);
            setSecret({ tokens, endpoint: String(r.endpoint_url ?? '') });
          }, 'Credenciais rotacionadas.')}>Rotacionar tokens</button><button className="btn sm" onClick={() => { setA(formValues(EMPTY_AGENT, r)); setAId(String(r.id)); }}>Editar</button><button className="btn sm danger" onClick={() => deletion.remove(`/admin/agents/${r.id}`, 'Excluir agente?', (request) => run(async () => { await request(); agents.reload(); }, 'Exclusão concluída.'))}>Excluir</button></div>]]} />
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
