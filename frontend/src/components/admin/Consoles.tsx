'use client';
import { useEffect, useState } from 'react';
import { Eraser } from 'lucide-react';
import { Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { del, get, patch, post, put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, useAction } from './common';
import { toast } from '@/components/Toaster';

type Method = { method: string; label: string; status: string; applicable: boolean; operational: boolean; guide: string; needs: string[] };
type Conn = Record<string, unknown> & { method: string; method_label?: string; connection_status: string; agent_id: string | null; validated_at: string | null;
  video_validated_at: string | null; audio_validated_at: string | null; control_validated_at: string | null; heartbeat_validated_at: string | null };
type C = { id: string; code: string; name: string; platform_code: string; status: string; is_published: boolean; model: string; serial_number: string | null;
  location: string; description: string; connection: Conn; tests: { test_type: string; result: string; simulated: boolean; message: string; run_at: string }[];
  last_health: Record<string, unknown> | null; current_assignment: { title: string; ends_at: string } | null; active_session: { id: string } | null;
  pairing: { status: string } | null; method_history?: { id: string; from_method: string; to_method: string; reason: string; created_at: string }[];
  hours?: { weekday: number; opens_at: string; closes_at: string }[] };
type Agent = { id: string; name: string; is_simulated: boolean };
type Dev = { id: string; agent_id: string; manufacturer: string; model: string; device_identifier?: string; identifier?: string; input_port?: string; used_by_console: string | null; authorized?: boolean };

const ROUTE_HINT: Record<string, string> = {
  lan: 'O PC do agente fica na mesma rede (de preferência no cabo) que o console. Menor atraso; liga o console pela rede.',
  internet_psn: 'O agente conecta ao console pela PSN, sem abrir portas. O agente precisa estar logado na conta PSN do console.',
  internet_port_forward: 'O agente conecta pelo IP público do roteador do console. Exige redirecionar as portas do Remote Play no roteador.',
};

const TESTS: [string, string][] = [['discover', 'Descobrir console'], ['pair', 'Parear'], ['connection', 'Testar conexão'], ['video_audio', 'Testar imagem e áudio'],
  ['controls', 'Testar controles'], ['heartbeat', 'Verificar heartbeat'], ['latency', 'Medir latência']];
const RESULT_PT: Record<string, string> = { passed: 'aprovado', failed: 'falhou', not_available: 'não disponível' };
const DAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

function Editor({ c, onChange, onDelete }: { c: C; onChange: () => void; onDelete: () => void }) {
  const methods = useApi<Method[]>(`/admin/connection-methods?platform=${c.platform_code}`).data;
  const agents = useApi<Agent[]>('/admin/agents').data;
  const caps = useApi<Dev[]>('/admin/capture-devices').data;
  const ctls = useApi<Dev[]>('/admin/control-adapters').data;
  const [cfg, setCfg] = useState<Record<string, unknown>>({});
  const [basic, setBasic] = useState({ name: c.name, model: c.model, serial_number: c.serial_number || '', location: c.location, description: c.description });
  const [pairCode, setPairCode] = useState('');
  const [statusReason, setStatusReason] = useState('');
  const [hours, setHours] = useState(c.hours || []);
  const { run, msg, busy } = useAction();
  useEffect(() => {
    const x = c.connection;
    setCfg({ method: x.method, agent_id: x.agent_id || '', internal_host: x.internal_host || '', console_identifier: x.console_identifier || '', discovery_mode: x.discovery_mode,
      network_route: x.network_route || 'lan', public_host: x.public_host || '', public_port: x.public_port || '',
      resolution: x.resolution, fps: x.fps, codec: x.codec, bitrate_kbps: x.bitrate_kbps, low_latency: x.low_latency, audio_enabled: x.audio_enabled,
      capture_device_id: x.capture_device_id || '', control_adapter_id: x.control_adapter_id || '', video_encoder: x.video_encoder || '', capture_color_space: x.capture_color_space || '', reason: '' });
  }, [c]);
  const m = String(cfg.method || 'unconfigured');
  const info = methods?.find((x) => x.method === m);
  const set = (k: string, v: unknown) => setCfg({ ...cfg, [k]: v });
  const save = () => run(async () => {
    const body: Record<string, unknown> = { ...cfg, fps: Number(cfg.fps), bitrate_kbps: Number(cfg.bitrate_kbps), public_port: cfg.public_port ? Number(cfg.public_port) : null };
    if (body.method !== 'remote_play_chiaki') body.network_route = 'lan';
    for (const k of ['agent_id', 'capture_device_id', 'control_adapter_id', 'internal_host', 'console_identifier', 'video_encoder', 'capture_color_space', 'public_host']) if (!body[k]) body[k] = null;
    await put(`/admin/consoles/${c.id}/connection`, body); onChange();
  }, 'Configuração salva. Execute os testes para validar novamente.');
  const flag = (v: unknown) => (v ? <span className="pill green">validado</span> : <span className="pill red">não validado</span>);
  return (
    <div className="stack">
      {msg}
      <section className="card">
        <div className="spread"><h2 style={{ margin: 0 }}>{c.name} <span className="small muted">{c.code} · {c.platform_code}</span></h2>
          <div className="row"><StatusPill status={c.status} />{c.is_published ? <span className="pill green">publicado</span> : <span className="pill amber">não publicado</span>}</div></div>
        <div className="grid3" style={{ marginTop: 12 }}>
          <Field label="Nome"><input value={basic.name} onChange={(e) => setBasic({ ...basic, name: e.target.value })} /></Field>
          <Field label="Modelo"><input value={basic.model} onChange={(e) => setBasic({ ...basic, model: e.target.value })} /></Field>
          <Field label="Série / identificador"><input value={basic.serial_number} onChange={(e) => setBasic({ ...basic, serial_number: e.target.value })} /></Field>
          <Field label="Localização operacional"><input maxLength={120} value={basic.location} onChange={(e) => setBasic({ ...basic, location: e.target.value })} /></Field>
          <Field label="Descrição / observações"><input maxLength={500} value={basic.description} onChange={(e) => setBasic({ ...basic, description: e.target.value })} /></Field>
        </div>
        <button className="btn" style={{ marginTop: 10 }} disabled={busy} onClick={() => run(async () => { await patch(`/admin/consoles/${c.id}`, { ...basic, serial_number: basic.serial_number || null }); onChange(); }, 'Dados salvos.')}>Salvar dados</button>
      </section>

      <section className="card stack">
        <h2>Método de conexão e transmissão</h2>
        <Field label="Método (obrigatório)"><select value={m} onChange={(e) => set('method', e.target.value)}>
          {methods?.map((x) => <option key={x.method} value={x.method} disabled={!x.applicable}>{x.label}{!x.applicable ? ' — não aplicável a esta plataforma' : ''}</option>)}</select></Field>
        {m === 'remote_play_chiaki' && cfg.network_route !== 'lan' && <div className="alert warn"><span><b>Console em outra rede (pela internet):</b> mais atraso e menos estabilidade que na rede local;
          ligar o console do modo de repouso pode não funcionar; o PS4 deve ficar em modo de repouso com "Permanecer conectado à Internet" ativo. Indicado para testes — para clientes, prefira um agente na mesma rede do console.</span></div>}
        {info && <div className={`alert ${info.status === 'simulated' ? 'warn' : 'info'}`}><span><b>{info.label}</b> · {info.operational ? 'operacional' : 'NÃO validado com hardware'}<br />{info.guide}</span></div>}
        {m !== 'unconfigured' && <div className="grid3">
          <Field label="Agente local / PC host"><select value={String(cfg.agent_id)} onChange={(e) => set('agent_id', e.target.value)}><option value="">Selecione</option>
            {agents?.filter((a) => (m === 'simulated') === a.is_simulated).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          {m === 'remote_play_chiaki' && <>
            <Field label="Rota de rede (onde o console está)" hint={ROUTE_HINT[String(cfg.network_route)]}>
              <select value={String(cfg.network_route)} onChange={(e) => setCfg({ ...cfg, network_route: e.target.value, ...(e.target.value !== 'lan' ? { discovery_mode: 'manual' } : {}) })}>
                <option value="lan">Mesma rede do agente (recomendado)</option>
                <option value="internet_psn">Outra rede — pela internet via PSN</option>
                <option value="internet_port_forward">Outra rede — pela internet com portas abertas</option></select></Field>
            {cfg.network_route === 'lan' && <>
              <Field label="Descoberta"><select value={String(cfg.discovery_mode)} onChange={(e) => set('discovery_mode', e.target.value)}><option value="manual">IP/hostname manual</option><option value="lan_discovery">Descoberta na LAN</option></select></Field>
              <Field label="IP / hostname interno"><input maxLength={253} value={String(cfg.internal_host)} onChange={(e) => set('internal_host', e.target.value)} placeholder="192.168.0.20" /></Field>
            </>}
            {cfg.network_route === 'internet_port_forward' && <>
              <Field label="IP público ou DDNS do roteador do console" required><input maxLength={253} value={String(cfg.public_host)} onChange={(e) => set('public_host', e.target.value)} placeholder="meuconsole.ddns.net" /></Field>
              <Field label="Porta base do Remote Play" hint="Padrão 9295 (portas 9295–9304 redirecionadas para o console)"><input type="number" min={1} max={65535} value={String(cfg.public_port)} onChange={(e) => set('public_port', e.target.value)} placeholder="9295" /></Field>
            </>}
            <Field label="Identificação do console" required={cfg.network_route === 'internet_psn'} hint={cfg.network_route === 'internet_psn' ? 'Nome/ID do console registrado na conta PSN do agente' : undefined}>
              <input maxLength={120} value={String(cfg.console_identifier)} onChange={(e) => set('console_identifier', e.target.value)} /></Field>
          </>}
          {m === 'remote_play_direct' && <>
            <Field label="IP do console na rede local" required hint="Fixe esse IP no roteador (reserva DHCP) para não mudar."><input maxLength={253} value={String(cfg.internal_host)} onChange={(e) => set('internal_host', e.target.value)} placeholder="192.168.0.20" /></Field>
            <Field label="Identificação do console" required hint='Mesmo nome usado em "consoles" no config.json do agente (ex.: PS4-118).'>
              <input maxLength={120} value={String(cfg.console_identifier)} onChange={(e) => set('console_identifier', e.target.value)} /></Field>
          </>}
          {m === 'hdmi_capture' && <>
            <Field label="Capturadora / entrada HDMI"><select value={String(cfg.capture_device_id)} onChange={(e) => set('capture_device_id', e.target.value)}><option value="">Selecione</option>
              {caps?.filter((d) => d.agent_id === cfg.agent_id).map((d) => <option key={d.id} value={d.id} disabled={!!d.used_by_console && d.used_by_console !== c.id}>{d.manufacturer} {d.model} · {d.device_identifier} · {d.input_port}{d.used_by_console && d.used_by_console !== c.id ? ' (em uso)' : ''}</option>)}</select></Field>
            <Field label="Canal de controle SEPARADO"><select value={String(cfg.control_adapter_id)} onChange={(e) => set('control_adapter_id', e.target.value)}><option value="">Selecione</option>
              {ctls?.filter((d) => d.agent_id === cfg.agent_id).map((d) => <option key={d.id} value={d.id} disabled={!d.authorized || (!!d.used_by_console && d.used_by_console !== c.id)}>{d.identifier}{!d.authorized ? ' (não autorizado)' : ''}</option>)}</select></Field>
            <Field label="Encoder de vídeo"><input value={String(cfg.video_encoder)} onChange={(e) => set('video_encoder', e.target.value)} placeholder="ex.: NVENC / x264" /></Field>
          </>}
          <Field label="Resolução"><select value={String(cfg.resolution)} onChange={(e) => set('resolution', e.target.value)}><option>720p</option><option>1080p</option></select></Field>
          <Field label="FPS"><select value={String(cfg.fps)} onChange={(e) => set('fps', e.target.value)}><option>30</option><option>60</option></select></Field>
          <Field label="Codec"><select value={String(cfg.codec)} onChange={(e) => set('codec', e.target.value)}><option value="h264">H.264</option><option value="h265">H.265</option></select></Field>
          <Field label="Bitrate (kbps)"><input type="number" value={String(cfg.bitrate_kbps)} onChange={(e) => set('bitrate_kbps', e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={!!cfg.low_latency} onChange={(e) => set('low_latency', e.target.checked)} />Perfil de baixa latência</label>
          <label className="check"><input type="checkbox" checked={!!cfg.audio_enabled} onChange={(e) => set('audio_enabled', e.target.checked)} />Áudio</label>
        </div>}
        <Field label="Motivo da alteração (registrado na auditoria)"><input maxLength={500} value={String(cfg.reason || '')} onChange={(e) => set('reason', e.target.value)} /></Field>
        <div className="row"><button className="btn primary" disabled={busy} onClick={save}>Salvar configuração</button>
          <button className="btn" disabled={busy || m === 'unconfigured'} onClick={() => run(async () => { await put(`/admin/consoles/${c.id}/connection`, { method: 'unconfigured', reason: 'Desativado no painel' }); onChange(); }, 'Conexão desativada.')}>Desativar</button></div>
      </section>

      <section className="card stack">
        <h2>Testes e diagnóstico</h2>
        <div className="row">Vídeo {flag(c.connection.video_validated_at)} Áudio {flag(c.connection.audio_validated_at)} Controle {flag(c.connection.control_validated_at)} Heartbeat {flag(c.connection.heartbeat_validated_at)}
          Conexão <StatusPill status={c.connection.connection_status} /></div>
        {m === 'remote_play_chiaki' && <Field label="Código de pareamento exibido no console (assistente do admin)"><input value={pairCode} onChange={(e) => setPairCode(e.target.value)} maxLength={12} /></Field>}
        {m === 'remote_play_direct' && <Field label="PIN de registro (8 dígitos)" hint="No console: Configurações → Configurações da Conexão de Uso Remoto → Adicionar Dispositivo. Digite aqui e clique em Pareamento (vale por ~5 min).">
          <input inputMode="numeric" value={pairCode} onChange={(e) => setPairCode(e.target.value.replace(/\D/g, '').slice(0, 8))} maxLength={8} placeholder="12345678" /></Field>}
        <div className="row">{TESTS.map(([t, l]) => <button key={t} className="btn sm" disabled={busy} onClick={() => run(async () => {
          const r = await post<{ result: string; message: string; simulated: boolean }>(`/admin/consoles/${c.id}/tests/${t}`, t === 'pair' ? { code: pairCode || null } : {});
          onChange(); return r;
        }).then((r) => r && toast(r.result === 'passed' ? 'ok' : 'error', `${l}: ${RESULT_PT[r.result] || r.result}${r.simulated ? ' (SIMULADO)' : ''} — ${r.message}`))}>{l}</button>)}</div>
        <div className="row">
          <button className="btn primary" disabled={busy || c.is_published} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/publish`); onChange(); }, 'Console publicado para vendas.')}>Publicar</button>
          <button className="btn" disabled={busy || !c.is_published} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/unpublish`); onChange(); }, 'Console despublicado.')}>Despublicar</button>
        </div>
        <div className="spread"><h3 style={{ margin: 0 }}>Histórico de testes</h3>
          <button className="btn sm" disabled={busy || !c.tests?.length} title="Apaga só o histórico exibido; as validações continuam valendo"
            onClick={() => { if (confirm('Limpar o histórico de testes deste console? As validações (vídeo, áudio, controle, heartbeat) continuam valendo.'))
              run(async () => { await del(`/admin/consoles/${c.id}/tests`); onChange(); }, 'Histórico de testes limpo.'); }}>
            <Eraser size={14} aria-hidden />Limpar testes</button></div>
        <DataTable rows={c.tests as unknown as Record<string, unknown>[]} empty="Nenhum teste executado." cols={[['Teste', (r) => String(r.test_type)], ['Resultado', (r) => <StatusPill status={String(r.result)} />],
          ['Simulado', (r) => (r.simulated ? 'sim' : 'não')], ['Mensagem', (r) => String(r.message)], ['Quando', (r) => dateTime(String(r.run_at))]]} />
        <p className="small muted">Telemetria: {c.last_health ? `${c.last_health.status} · FPS ${c.last_health.fps ?? 'não disponível'} · RTT ${c.last_health.rtt_ms ?? 'não disponível'} · bitrate ${c.last_health.bitrate_kbps ?? 'não disponível'} · ${dateTime(String(c.last_health.checked_at))}${c.last_health.simulated ? ' (simulado)' : ''}` : 'sem amostras'}</p>
        <p className="small muted">Jogo vinculado agora: {c.current_assignment ? `${c.current_assignment.title} até ${dateTime(c.current_assignment.ends_at)}` : 'nenhum'} · Sessão ativa: {c.active_session ? 'sim' : 'não'} · Pareamento: {c.pairing?.status || '—'}</p>
      </section>

      <div className="grid2">
        <section className="card stack">
          <h2>Manutenção / status</h2>
          <Field label="Justificativa"><input maxLength={500} value={statusReason} onChange={(e) => setStatusReason(e.target.value)} /></Field>
          <div className="row">
            <button className="btn" disabled={busy || statusReason.length < 3} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'maintenance', reason: statusReason }); onChange(); }, 'Em manutenção.')}>Manutenção</button>
            <button className="btn danger" disabled={busy || statusReason.length < 3} onClick={() => confirm('Cancelar e reembolsar as reservas afetadas?') && run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'maintenance', reason: statusReason, resolution: 'cancel_and_refund' }); onChange(); }, 'Em manutenção; reservas afetadas canceladas e reembolsadas.')}>Manutenção + reembolsar afetados</button>
            <button className="btn" disabled={busy || statusReason.length < 3} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'online', reason: statusReason }); onChange(); }, 'Retornou à operação.')}>Retornar à operação</button>
          </div>
        </section>
        <section className="card stack">
          <h2>Horário de funcionamento</h2>
          {hours.map((h, i) => <div key={i} className="row">
            <select className="btn sm" value={h.weekday} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, weekday: Number(e.target.value) } : x))}>{DAYS.map((d, k) => <option key={k} value={k}>{d}</option>)}</select>
            <input className="btn sm" type="time" value={h.opens_at.slice(0, 5)} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, opens_at: e.target.value } : x))} />
            <input className="btn sm" type="time" value={h.closes_at.slice(0, 5)} onChange={(e) => setHours(hours.map((x, j) => j === i ? { ...x, closes_at: e.target.value } : x))} />
            <button className="btn sm danger" onClick={() => setHours(hours.filter((_, j) => j !== i))}>Remover</button></div>)}
          <div className="row"><button className="btn sm" onClick={() => setHours([...hours, { weekday: 1, opens_at: '08:00', closes_at: '22:00' }])}>Adicionar faixa</button>
            <button className="btn sm primary" onClick={() => run(async () => { await put(`/admin/consoles/${c.id}/hours`, { hours }); onChange(); }, 'Horários salvos.')}>Salvar horários</button></div>
          <p className="small dim">Sem faixas = funcionamento limitado apenas pelos vínculos.</p>
        </section>
      </div>
      {c.method_history && c.method_history.length > 0 && <section className="card"><h2>Histórico de métodos (rollback)</h2>
        <DataTable rows={c.method_history as unknown as Record<string, unknown>[]} cols={[['De', (r) => String(r.from_method)], ['Para', (r) => String(r.to_method)], ['Motivo', (r) => String(r.reason)],
          ['Quando', (r) => dateTime(String(r.created_at))], ['', (r) => <button className="btn sm" onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/connection/rollback/${r.id}`); onChange(); }, 'Configuração anterior restaurada (requer nova validação).')}>Restaurar</button>]]} /></section>}
      <section className="card stack" style={{ borderColor: 'rgba(255, 75, 92, .45)' }}>
        <h2 style={{ margin: 0 }}>Excluir console</h2>
        <p className="small muted" style={{ margin: 0 }}>Remove o console da operação: despublica, arquiva os vínculos futuros e libera capturadora/controle. O histórico (reservas, sessões, auditoria) é mantido.
          Bloqueado se houver sessão ativa ou reservas futuras.</p>
        <div><button className="btn danger" onClick={onDelete}>Excluir este console</button></div>
      </section>
    </div>
  );
}

export default function Consoles() {
  const list = useApi<C[]>('/admin/consoles', 20000);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<C | null>(null);
  const [nc, setNc] = useState({ code: '', name: '', platform_code: 'PS5' });
  const { run, msg } = useAction();
  const load = async (id: string) => setDetail(await get<C>(`/admin/consoles/${id}`));
  const [delC, setDelC] = useState<{ id: string; code: string; name: string } | null>(null);
  const [delTyped, setDelTyped] = useState('');
  const del_ = useAction();
  async function confirmDelete() {
    if (!delC) return;
    const ok = await del_.run(async () => { await del(`/admin/consoles/${delC.id}`); return true; }, `Console ${delC.name} excluído.`);
    if (ok) { if (sel === delC.id) { setSel(null); setDetail(null); } setDelC(null); list.reload(); }
  }
  const askDelete = (x: { id: string; code: string; name: string }) => { setDelTyped(''); setDelC(x); };
  useEffect(() => { if (sel) load(sel); }, [sel]);
  return (
    <div className="stack">
      <PageHeader title="Consoles e conexão" subtitle="Cadastro independente de jogos; método de conexão individual por console." />
      {msg}
      {!delC && del_.msg}
      <section className="card"><h2>Novo console</h2><div className="row">
        <input className="btn" placeholder="Código (PS5-05)" value={nc.code} onChange={(e) => setNc({ ...nc, code: e.target.value.toUpperCase() })} />
        <input className="btn" placeholder="Nome (PS5 nº 05)" value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })} />
        <select className="btn" value={nc.platform_code} onChange={(e) => setNc({ ...nc, platform_code: e.target.value })}>{['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((p) => <option key={p}>{p}</option>)}</select>
        <button className="btn primary" onClick={() => run(async () => { const c = await post<C>('/admin/consoles', nc); list.reload(); setSel(c.id); setNc({ code: '', name: '', platform_code: 'PS5' }); }, 'Console criado como "não configurado".')}>Cadastrar</button></div></section>
      <section className="card"><DataTable rows={list.data as unknown as Record<string, unknown>[] | null} cols={[
        ['Console', (r) => <button className="btn sm" onClick={() => setSel(String(r.id))}>{String(r.name)}</button>], ['Plataforma', (r) => String(r.platform_code)],
        ['Método', (r) => String((r.connection as Conn)?.method_label || '—')], ['Status', (r) => <StatusPill status={String(r.status)} />],
        ['Publicado', (r) => (r.is_published ? 'sim' : 'não')], ['Jogo agora', (r) => String((r.current_assignment as { title?: string })?.title || '—')],
        ['', (r) => <button className="btn sm danger" onClick={() => askDelete({ id: String(r.id), code: String(r.code), name: String(r.name) })}>Excluir</button>]]} /></section>
      {detail && <Editor key={detail.id + JSON.stringify(detail.connection.version)} c={detail} onChange={() => { load(detail.id); list.reload(); }} onDelete={() => askDelete(detail)} />}
      {delC && (
        <Modal title="Excluir console" onClose={() => setDelC(null)}>
          <div className="stack">
            <p style={{ margin: 0 }}>Excluir <b>{delC.name}</b>? Ele sai da operação e do painel; o histórico é mantido.</p>
            <Field label={`Digite o código do console para confirmar: ${delC.code}`}><input value={delTyped} onChange={(e) => setDelTyped(e.target.value.toUpperCase())} /></Field>
            <div className="row"><button className="btn danger" disabled={del_.busy || delTyped !== delC.code} onClick={confirmDelete}>Excluir definitivamente</button>
              <button className="btn" onClick={() => setDelC(null)}>Cancelar</button></div>
            {del_.msg}
          </div>
        </Modal>)}
    </div>
  );
}
