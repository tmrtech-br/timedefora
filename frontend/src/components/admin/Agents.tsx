'use client';
import { useState } from 'react';
import { Alert, Field, PageHeader } from '@/components/ui';
import { del, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, useAction } from './common';

export default function Agents() {
  const agents = useApi<Record<string, unknown>[]>('/admin/agents', 15000);
  const caps = useApi<Record<string, unknown>[]>('/admin/capture-devices');
  const ctls = useApi<Record<string, unknown>[]>('/admin/control-adapters');
  const [a, setA] = useState({ name: '', host_name: '', endpoint_url: '', location: '', is_simulated: false });
  const [c, setC] = useState({ agent_id: '', manufacturer: '', model: '', device_identifier: '', input_port: 'HDMI-1', supports_simultaneous_inputs: false });
  const [k, setK] = useState({ agent_id: '', adapter_type: 'usb_controller_interface', identifier: '', manufacturer: '', model: '', authorized: false });
  const [secret, setSecret] = useState<Record<string, string> | null>(null);
  const { run, msg } = useAction();
  const agentOpts = agents.data?.filter((x) => !x.is_simulated).map((x) => <option key={String(x.id)} value={String(x.id)}>{String(x.name)}</option>);
  return (
    <div className="stack">
      <PageHeader title="Agentes locais e dispositivos" subtitle="PC ao lado dos consoles: captura, encode, stream e interfaces de controle." />
      {msg}
      {secret && <Alert kind="warn"><span>Tokens gerados (exibidos uma única vez): agente→API <code>{secret.agent_token}</code> · API→agente <code>{secret.api_to_agent_token}</code></span></Alert>}
      <section className="card stack"><h2>Novo agente</h2><div className="grid3">
        <Field label="Nome"><input value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></Field>
        <Field label="Host"><input value={a.host_name} onChange={(e) => setA({ ...a, host_name: e.target.value })} /></Field>
        <Field label="Endpoint HTTPS do agente"><input value={a.endpoint_url} onChange={(e) => setA({ ...a, endpoint_url: e.target.value })} placeholder="https://agente-01.vpn.local" /></Field>
        <Field label="Localização"><input value={a.location} onChange={(e) => setA({ ...a, location: e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={a.is_simulated} onChange={(e) => setA({ ...a, is_simulated: e.target.checked })} />Agente SIMULADO (desenvolvimento)</label></div>
        <button className="btn primary" onClick={() => run(async () => { setSecret(await post('/admin/agents', { ...a, endpoint_url: a.endpoint_url || null })); agents.reload(); }, 'Agente cadastrado.')}>Cadastrar</button>
        <DataTable rows={agents.data} cols={[['Nome', (r) => String(r.name)], ['Host', (r) => String(r.host_name)], ['Status', (r) => String(r.status)], ['Simulado', (r) => (r.is_simulated ? 'sim' : 'não')],
          ['Último heartbeat', (r) => dateTime(r.last_heartbeat_at as string)], ['', (r) => <button className="btn sm" onClick={() => run(async () => setSecret(await post(`/admin/agents/${r.id}/rotate-credentials`)), 'Credenciais rotacionadas.')}>Rotacionar tokens</button>]]} />
      </section>
      <section className="card stack"><h2>Capturadoras HDMI</h2>
        <p className="small muted">Cada console precisa de uma entrada de captura independente. Saída HDMI de notebook não é capturadora. Respeite HDCP/DRM.</p>
        <div className="grid3"><Field label="Agente"><select value={c.agent_id} onChange={(e) => setC({ ...c, agent_id: e.target.value })}><option value="">Selecione</option>{agentOpts}</select></Field>
          <Field label="Fabricante"><input value={c.manufacturer} onChange={(e) => setC({ ...c, manufacturer: e.target.value })} /></Field>
          <Field label="Modelo"><input value={c.model} onChange={(e) => setC({ ...c, model: e.target.value })} /></Field>
          <Field label="Device ID"><input value={c.device_identifier} onChange={(e) => setC({ ...c, device_identifier: e.target.value })} /></Field>
          <Field label="Entrada"><input value={c.input_port} onChange={(e) => setC({ ...c, input_port: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={c.supports_simultaneous_inputs} onChange={(e) => setC({ ...c, supports_simultaneous_inputs: e.target.checked })} />Captura entradas simultaneamente</label></div>
        <button className="btn" onClick={() => run(async () => { await post('/admin/capture-devices', c); caps.reload(); }, 'Capturadora cadastrada.')}>Cadastrar</button>
        <DataTable rows={caps.data} cols={[['Agente', (r) => String(r.agent_name)], ['Dispositivo', (r) => `${r.manufacturer} ${r.model}`], ['ID / entrada', (r) => `${r.device_identifier} · ${r.input_port}`],
          ['Em uso', (r) => (r.used_by_console ? 'sim' : 'não')], ['', (r) => <button className="btn sm danger" onClick={() => run(async () => { await del(`/admin/capture-devices/${r.id}`); caps.reload(); }, 'Removida.')}>Remover</button>]]} />
      </section>
      <section className="card stack"><h2>Adaptadores de controle</h2>
        <div className="grid3"><Field label="Agente"><select value={k.agent_id} onChange={(e) => setK({ ...k, agent_id: e.target.value })}><option value="">Selecione</option>{agentOpts}</select></Field>
          <Field label="Tipo"><select value={k.adapter_type} onChange={(e) => setK({ ...k, adapter_type: e.target.value })}><option value="usb_controller_interface">Interface USB</option><option value="bluetooth_controller_interface">Interface Bluetooth</option><option value="remote_play_input">Entrada via Remote Play</option><option value="other">Outro</option></select></Field>
          <Field label="Identificador"><input value={k.identifier} onChange={(e) => setK({ ...k, identifier: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={k.authorized} onChange={(e) => setK({ ...k, authorized: e.target.checked })} />Compatível e autorizado (verificado)</label></div>
        <button className="btn" onClick={() => run(async () => { await post('/admin/control-adapters', k); ctls.reload(); }, 'Adaptador cadastrado.')}>Cadastrar</button>
        <DataTable rows={ctls.data} cols={[['Agente', (r) => String(r.agent_name)], ['Tipo', (r) => String(r.adapter_type)], ['Identificador', (r) => String(r.identifier)],
          ['Autorizado', (r) => (r.authorized ? 'sim' : 'não')], ['Em uso', (r) => (r.used_by_console ? 'sim' : 'não')],
          ['', (r) => <button className="btn sm danger" onClick={() => run(async () => { await del(`/admin/control-adapters/${r.id}`); ctls.reload(); }, 'Removido.')}>Remover</button>]]} />
      </section>
    </div>
  );
}
