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
  const [secret, setSecret] = useState<Record<string, string> | null>(null);
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const agentOpts = agents.data?.filter((x) => !x.is_simulated).map((x) => <option key={String(x.id)} value={String(x.id)}>{String(x.name)}</option>);
  return (
    <div className="stack">
      <PageHeader title="Agentes locais e dispositivos" subtitle="PC ao lado dos consoles: captura, encode, stream e interfaces de controle." />
      {msg}
      {deletion.dialog}
      {secret && <Alert kind="warn" dismissible={false}><span>Tokens gerados (exibidos uma única vez): agente→API <code>{secret.agent_token}</code> · API→agente <code>{secret.api_to_agent_token}</code></span></Alert>}
      <section className="card stack"><h2>Agentes</h2><NewRecord title="Novo agente" editingTitle={aId ? "Editar agente" : undefined} onClose={() => { setAId(''); setA(EMPTY_AGENT); }}>{(close) => <><div className="grid3">
        <Field label="Nome" help="Nome exibido no painel."><input value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></Field>
        <Field label="Host" help="Nome de rede ou IP do computador do agente."><input maxLength={253} value={a.host_name} onChange={(e) => setA({ ...a, host_name: e.target.value })} /></Field>
        <Field label="Endpoint HTTPS do agente" help="Endereço usado para chamar o agente." hint="Em desenvolvimento, com o agente no mesmo PC: http://127.0.0.1:8765"><input maxLength={500} value={a.endpoint_url} onChange={(e) => setA({ ...a, endpoint_url: e.target.value })} placeholder="https://agente-01.vpn.local" /></Field>
        <Field label="Localização" help="Local físico do agente."><input maxLength={120} value={a.location} onChange={(e) => setA({ ...a, location: e.target.value })} /></Field>
        {!aId && <div className="row"><label className="check"><input type="checkbox" checked={a.is_simulated} onChange={(e) => setA({ ...a, is_simulated: e.target.checked })} />Agente SIMULADO (desenvolvimento)</label><FieldHelp text="Agente de desenvolvimento que opera sem console físico." /></div>}</div>
        <button className="btn primary" disabled={busy} onClick={() => run(async () => {
          need(a.name.trim().length >= 2, 'Informe o nome do agente (mínimo 2 caracteres).');
          need(a.host_name.trim(), 'Informe o host do agente.');
          need(!a.endpoint_url || /^https?:\/\//.test(a.endpoint_url), 'O endpoint deve começar com https:// (ou http:// em desenvolvimento).');
          const { is_simulated, ...agent } = a;
          const payload = { ...agent, endpoint_url: a.endpoint_url || null };
          if (aId) await patch(`/admin/agents/${aId}`, payload);
          else setSecret(await post('/admin/agents', { ...payload, is_simulated })); agents.reload(); close(); }, aId ? 'Agente atualizado.' : 'Agente cadastrado.')}>{aId ? 'Salvar' : 'Cadastrar'}</button></>}</NewRecord>
        <DataTable rows={agents.data} error={agents.error?.message} cols={[['Nome', (r) => String(r.name)], ['Host', (r) => String(r.host_name)], ['Status', (r) => <StatusPill status={String(r.status)} map={AGENT_STATUS} tone={({ online: 'green', offline: 'red', degraded: 'amber', unknown: '' } as Record<string, string>)[String(r.status)]} />], ['Simulado', (r) => (r.is_simulated ? 'sim' : 'não')],
          ['Último heartbeat', (r) => dateTime(r.last_heartbeat_at as string)], ['Ações', (r) => <div className="row"><button className="btn sm" onClick={() => run(async () => setSecret(await post(`/admin/agents/${r.id}/rotate-credentials`)), 'Credenciais rotacionadas.')}>Rotacionar tokens</button><button className="btn sm" onClick={() => { setA(formValues(EMPTY_AGENT, r)); setAId(String(r.id)); }}>Editar</button><button className="btn sm danger" onClick={() => deletion.remove(`/admin/agents/${r.id}`, 'Excluir agente?', (request) => run(async () => { await request(); agents.reload(); }, 'Exclusão concluída.'))}>Excluir</button></div>]]} />
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
