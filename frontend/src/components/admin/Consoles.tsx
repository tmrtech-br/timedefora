'use client';
import { ProgressModal } from '@/components/admin/ProgressModal';
import { useEffect, useState } from 'react';
import { Eraser } from 'lucide-react';
import { Field, Modal, PageHeader, StatusPill } from '@/components/ui';
import { del, get, patch, post, put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';
import { DataTable, NewRecord, useAction, useConfirm, useDelete } from './common';

type Method = { method: string; label: string; status: string; applicable: boolean; operational: boolean; guide: string; needs: string[] };
type Conn = Record<string, unknown> & { method: string; method_label?: string; connection_status: string; agent_id: string | null; psn_account_id?: string | null; validated_at: string | null;
  video_validated_at: string | null; audio_validated_at: string | null; control_validated_at: string | null; heartbeat_validated_at: string | null };
export type AdminConsole = { id: string; code: string; name: string; platform_code: string; status: string; is_published: boolean; model: string; serial_number: string | null;
  owner_user_id?: string | null; owner_onboarding_agent_id?: string | null; owner_requested_psn_account_id?: string | null;
  location: string; description: string; connection: Conn; tests: { test_type: string; result: string; simulated: boolean; message: string; run_at: string }[];
  last_health: Record<string, unknown> | null; current_assignment: { title: string; ends_at: string } | null; active_session: { id: string } | null;
  pairing: { status: string } | null; method_history?: { id: string; from_method: string; to_method: string; reason: string; created_at: string }[];
  hours?: { weekday: number; opens_at: string; closes_at: string }[] };
type Agent = { id: string; name: string; is_simulated: boolean };
type PsnAccount = { id: string; label: string; agent_id: string; owner_user_id?: string | null; status: string };
type Dev = { id: string; agent_id: string; manufacturer: string; model: string; device_identifier?: string; identifier?: string; input_port?: string; used_by_console: string | null; authorized?: boolean };
type Diagnostic = { id: string; status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed'; test_type?: string; error?: string; results: { test_type: string; result: string; message: string }[] };

const ROUTE_HINT: Record<string, string> = {
  lan: 'O PC do agente fica na mesma rede (de preferência no cabo) que o console. Menor atraso; liga o console pela rede.',
  internet_psn: 'O agente conecta ao console pela PSN, sem abrir portas. O agente precisa estar logado na conta PSN do console.',
  internet_port_forward: 'O agente conecta pelo IP público do roteador do console. Exige redirecionar as portas do Remote Play no roteador.',
};

const TESTS: [string, string][] = [['discover', 'Descobrir console'], ['pair', 'Parear'], ['connection', 'Testar conexão'], ['video_audio', 'Testar imagem e áudio'],
  ['controls', 'Testar controles'], ['heartbeat', 'Verificar heartbeat'], ['latency', 'Medir latência'], ['psn_auth', 'Testar autenticação PSN']];
const TEST_DETAILS: Record<string, [string, string]> = {
  discover: ['Localiza o console pela rota configurada.', 'Console desligado ou identificação incorreta.'],
  pair: ['Registra o agente para uso remoto.', 'Código expirado ou uso remoto desativado no console.'],
  connection: ['Tenta iniciar a conexão com o console.', 'Console indisponível, rota, pareamento ou autenticação incorretos.'],
  video_audio: ['Verifica se o adaptador recebe vídeo e áudio.', 'Conexão ainda indisponível ou captura incompatível.'],
  controls: ['Valida o canal de comandos do controle.', 'Dispositivo de entrada não associado ou sem permissão.'],
  heartbeat: ['Verifica se o agente está acessível.', 'Agente offline ou credenciais inválidas.'],
  latency: ['Consulta uma medição de latência disponível.', 'A medição pode exigir uma sessão ativa.'],
  psn_auth: ['Verifica a autenticação da conta PSN configurada para a rota pela internet.', 'Login Sony expirado ou agente sem acesso à PSN.'],
};
const RESULT_PT: Record<string, string> = { passed: 'aprovado', failed: 'falhou', not_available: 'não disponível' };
const DAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export function ConsoleEditor({ c, onChange, onDelete, onboarding = false }: {
  c: AdminConsole; onChange: () => void; onDelete?: () => void; onboarding?: boolean;
}) {
  const methods = useApi<Method[]>(`/admin/connection-methods?platform=${c.platform_code}`).data;
  const agents = useApi<Agent[]>('/admin/agents').data;
  const psnAccounts = useApi<PsnAccount[]>('/admin/psn-accounts').data;
  const caps = useApi<Dev[]>('/admin/capture-devices').data;
  const ctls = useApi<Dev[]>('/admin/control-adapters').data;
  const [cfg, setCfg] = useState<Record<string, unknown>>({});
  const [basic, setBasic] = useState({ name: c.name, model: c.model, serial_number: c.serial_number || '', location: c.location, description: c.description });
  const [pairCode, setPairCode] = useState('');
  const [runId, setRunId] = useState<string>();
  const [requestedTest, setRequestedTest] = useState<string>();
  const [cancelRequested, setCancelRequested] = useState(false);
  const [cancelError, setCancelError] = useState<string>();
  const [finishedRun, setFinishedRun] = useState<Diagnostic>();
  const batch = useApi<Diagnostic>(runId ? `/admin/consoles/${c.id}/diagnostic-runs/${runId}` : null, 2500);
  const activeRun = batch.data?.id === runId ? batch.data : null;
  const [statusReason, setStatusReason] = useState('');
  const [hours, setHours] = useState(c.hours || []);
  const { run, msg, busy } = useAction();
  const [sure, confirmation] = useConfirm();
  const deletion = useDelete();
  useEffect(() => {
    if (!activeRun || !['completed', 'failed', 'cancelled'].includes(activeRun.status)) return;
    setFinishedRun(activeRun);
    setRunId(undefined);
    setCancelRequested(false);
    onChange();
  }, [activeRun, onChange]);
  useEffect(() => {
    const x = c.connection;
    setCfg({ method: x.method, agent_id: x.agent_id || c.owner_onboarding_agent_id || '', internal_host: x.internal_host || '', console_identifier: x.console_identifier || '', discovery_mode: x.discovery_mode,
      network_route: x.network_route || 'lan', public_host: x.public_host || '', public_port: x.public_port || '',
      resolution: x.resolution, fps: x.fps, codec: x.codec, bitrate_kbps: x.bitrate_kbps, low_latency: x.low_latency, audio_enabled: x.audio_enabled,
      capture_device_id: x.capture_device_id || '', control_adapter_id: x.control_adapter_id || '', video_encoder: x.video_encoder || '', capture_color_space: x.capture_color_space || '',
      psn_account_id: x.psn_account_id || c.owner_requested_psn_account_id || '', psn_device_uid: x.psn_device_uid || '',
      standby_after_session: x.standby_after_session ?? true, keep_awake_minutes: x.keep_awake_minutes ?? 15, reason: '' });
  }, [c]);
  const m = String(cfg.method || 'unconfigured');
  const savedMethod = c.connection.method;
  const queueDiagnostic = (test_type?: string) => void run(async () => {
    const job = await post<{ id: string }>(`/admin/consoles/${c.id}/diagnostic-runs`, { code: pairCode || null, test_type });
    setRequestedTest(test_type);
    setCancelError(undefined);
    setFinishedRun(undefined);
    setRunId(job.id);
  });
  const savedRoute = c.connection.network_route || 'lan';
  const nativePsnRoute = savedMethod === 'remote_play_native' && savedRoute === 'internet_psn';
  const lanPairing = savedMethod === 'remote_play_direct' ||
    (savedMethod === 'remote_play_native' && savedRoute === 'lan');
  const info = methods?.find((x) => x.method === m);
  const set = (k: string, v: unknown) => setCfg({ ...cfg, [k]: v });
  const save = () => run(async () => {
    const body: Record<string, unknown> = { ...cfg, fps: Number(cfg.fps), bitrate_kbps: Number(cfg.bitrate_kbps), public_port: cfg.public_port ? Number(cfg.public_port) : null };
    if (body.method !== 'remote_play_chiaki' && body.method !== 'remote_play_native') body.network_route = 'lan';
    body.keep_awake_minutes = Number(body.keep_awake_minutes);
    if (!body.psn_account_id) body.psn_account_id = null;
    if (c.platform_code === 'PS4' && body.method === 'remote_play_native') body.psn_device_uid = null;
    for (const k of ['agent_id', 'capture_device_id', 'control_adapter_id', 'internal_host', 'console_identifier', 'video_encoder', 'capture_color_space', 'public_host']) if (!body[k]) body[k] = null;
    await put(`/admin/consoles/${c.id}/connection`, body); onChange();
  }, 'Configuração salva. Execute os testes para validar novamente.');
  const unlinkPsn = async () => {
    const confirmed = await sure({
      title: 'Desvincular conta PSN',
      message: `A conexão de ${c.code} será desativada e precisará ser configurada e validada novamente. A conta permanece cadastrada em Contas PSN.`,
      confirm: 'Desvincular',
      danger: true,
    });
    if (!confirmed) return;
    await run(async () => {
      await put(`/admin/consoles/${c.id}/connection`, {
        method: 'unconfigured', agent_id: c.connection.agent_id, reason: 'Conta PSN desvinculada no painel',
      });
      onChange();
    }, 'Conta PSN desvinculada deste console.');
  };
  const flag = (v: unknown) => (v ? <span className="pill green">validado</span> : <span className="pill red">não validado</span>);
  return (
    <div className="stack">
      {confirmation}
      {msg}
      {deletion.dialog}
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

      <section className="card stack"><h2>Método de conexão e transmissão</h2>
        
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
          {m === 'remote_play_native' && <>
            <Field label="Rota de rede"><select value={String(cfg.network_route || 'lan')} onChange={(e) => set('network_route', e.target.value)}>
              <option value="lan">Mesma rede (LAN)</option>
              <option value="internet_psn" disabled={c.platform_code !== 'PS4'}>Outra rede (PSN) — PS4</option>
            </select></Field>
            {cfg.network_route === 'lan' ? <>
              <Field label="IP / hostname LAN do console"><input value={String(cfg.internal_host || '')} onChange={(e) => set('internal_host', e.target.value)} /></Field>
              <Field label="Identificação do console"><input value={String(cfg.console_identifier || '')} onChange={(e) => set('console_identifier', e.target.value)} /></Field>
            </> : <>
              <Field label="Conta PSN vinculada"><select value={String(cfg.psn_account_id || '')} onChange={(e) => set('psn_account_id', e.target.value)}>
                <option value="">Selecione uma conta</option>
                {psnAccounts?.filter((a) => a.agent_id === cfg.agent_id && a.status === 'linked' &&
                  (a.owner_user_id ?? null) === (c.owner_user_id ?? null)).map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              </select></Field>
              {c.platform_code === 'PS4' ? (
                <p className="small muted">Usar o PS4 principal da conta selecionada.</p>
              ) : (
                <p className="small muted" role="alert">Remote Play nativo pela PSN ainda funciona só com PS4. Use a rota “Mesma rede” para o PS5.</p>
              )}
            </>}
            <label className="check"><input type="checkbox" checked={!!cfg.standby_after_session} onChange={(e) => set('standby_after_session', e.target.checked)} />Hibernar ao terminar (rota PSN do PS4)</label>
            <Field label="Manter acordado se houver reserva em X minutos"><input type="number" min={0} max={240} value={Number(cfg.keep_awake_minutes ?? 15)} onChange={(e) => set('keep_awake_minutes', Number(e.target.value))} /></Field>
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
          <button className="btn" disabled={busy || m === 'unconfigured'} onClick={() => run(async () => { await put(`/admin/consoles/${c.id}/connection`, { method: 'unconfigured', reason: 'Desativado no painel' }); onChange(); }, 'Conexão desativada.')}>Desativar</button>
          {c.connection.psn_account_id && <button className="btn danger" disabled={busy} onClick={unlinkPsn}>Desvincular conta PSN</button>}
        </div>
      </section>

      <section className="card stack"><h2>Testes e diagnóstico</h2>
        
        <div className="row">Vídeo {flag(c.connection.video_validated_at)} Áudio {flag(c.connection.audio_validated_at)} Controle {flag(c.connection.control_validated_at)} Heartbeat {flag(c.connection.heartbeat_validated_at)}
          Conexão <StatusPill status={c.connection.connection_status} /></div>
        {nativePsnRoute && <p className="small muted">O registro remoto é realizado automaticamente no teste de conexão.</p>}
        {savedMethod === 'remote_play_chiaki' && <Field label="Código de pareamento exibido no console (assistente do admin)"><input value={pairCode} onChange={(e) => setPairCode(e.target.value)} maxLength={12} /></Field>}
        {lanPairing && <Field label="PIN de registro (8 dígitos)" hint="No console: Configurações → Configurações da Conexão de Uso Remoto → Adicionar Dispositivo. Digite o PIN e clique em Parear.">
          <input inputMode="numeric" value={pairCode} onChange={(e) => setPairCode(e.target.value.replace(/\D/g, '').slice(0, 8))} maxLength={8} placeholder="12345678" /></Field>}
        <button className="btn" disabled={busy || Boolean(runId) || savedMethod === 'unconfigured'} onClick={() => queueDiagnostic()}>Executar todos os testes</button>
        {runId && <ProgressModal
          status={cancelRequested || activeRun?.status === 'cancelling' ? 'Cancelando diagnóstico…' : activeRun?.status === 'running' ? 'Executando diagnóstico…' : 'Na fila de diagnósticos.'}
          error={cancelError ?? batch.error?.message}
          tests={TESTS.filter(([test]) => {
            const selected = activeRun ? activeRun.test_type : requestedTest;
            return selected ? test === selected : test !== 'psn_auth' || nativePsnRoute;
          }).map(([id, label], index) => {
            const result = activeRun?.results.find((item) => item.test_type === id);
            return { id, label, state: result ? (RESULT_PT[result.result] || result.result) :
              activeRun?.status === 'running' && index === activeRun.results.length ? 'Em execução' : 'Na fila' };
          })}
          onCancel={async () => {
            if (cancelRequested) return;
            setCancelError(undefined);
            setCancelRequested(true);
            try {
              await post(`/admin/consoles/${c.id}/diagnostic-runs/${runId}/cancel`);
              await batch.reload();
            } catch (error) {
              setCancelRequested(false);
              setCancelError(error instanceof Error ? error.message : 'Erro ao cancelar diagnóstico.');
            }
          }} />}
        {finishedRun && <div>
          <p role="status">{finishedRun.status === 'cancelled' ? 'Diagnóstico cancelado.' : finishedRun.status === 'failed' ? (finishedRun.error ?? 'Diagnóstico interrompido.') : 'Diagnóstico concluído.'}</p>
          <ul>{finishedRun.results.map((item) => <li key={item.test_type}>
            {TESTS.find(([test]) => test === item.test_type)?.[1] ?? item.test_type} · {RESULT_PT[item.result]} · {item.message}
          </li>)}</ul>
        </div>}
        <div className="row">{TESTS.filter(([test]) => test !== 'psn_auth' || nativePsnRoute).map(([t, l]) =>
          <button key={t} className="btn sm" disabled={busy || Boolean(runId) || (t === 'pair' && nativePsnRoute)}
            onClick={() => queueDiagnostic(t)}>{l}</button>)}</div>
        {!onboarding && <div className="row">
          <button className="btn primary" disabled={busy || c.is_published} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/publish`); onChange(); }, 'Console publicado para vendas.')}>Publicar</button>
          <button className="btn" disabled={busy || !c.is_published} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/unpublish`); onChange(); }, 'Console despublicado.')}>Despublicar</button>
        </div>}
        <div className="spread"><h3 style={{ margin: 0 }}>Histórico de testes</h3>
          <button className="btn sm" disabled={busy || (!c.tests?.length && !finishedRun)} title="Apaga o histórico exibido e preserva as validações"
            onClick={() => deletion.remove(`/admin/consoles/${c.id}/tests`, 'Limpar o histórico de testes?',
              (request) => run(async () => { await request(); setFinishedRun(undefined); onChange(); }, 'Histórico de testes limpo.'),
              'As validações do console permanecem registradas.')}>
            <Eraser size={14} aria-hidden />Limpar diagnóstico</button></div>
        <DataTable rows={c.tests as unknown as Record<string, unknown>[]} empty="Nenhum teste executado." cols={[['Teste', (r) => (
          <details>
            <summary>{TESTS.find(([type]) => type === r.test_type)?.[1] ?? String(r.test_type)}</summary>
            <dl>
              <dt>Objetivo</dt><dd>{TEST_DETAILS[String(r.test_type)]?.[0]}</dd>
              <dt>Resultado</dt><dd>{RESULT_PT[String(r.result)] ?? String(r.result)}</dd>
              <dt>Duração</dt><dd>{typeof r.duration_ms === 'number' ? `${r.duration_ms} ms` : 'Indisponível'}</dd>
              {Boolean(r.network_route) && <><dt>Rota</dt><dd>{String(r.network_route)}</dd></>}
              <dt>Registro do adaptador</dt><dd>{String(r.message)}</dd>
              {r.result !== 'passed' && <><dt>Possíveis causas</dt><dd>{TEST_DETAILS[String(r.test_type)]?.[1]}</dd></>}
            </dl>
          </details>
        )], ['Resultado', (r) => <StatusPill status={String(r.result)} />],
          ['Simulado', (r) => (r.simulated ? 'sim' : 'não')], ['Mensagem', (r) => String(r.message)], ['Quando', (r) => dateTime(String(r.run_at))]]} />
        <p className="small muted">Telemetria: {c.last_health ? `${c.last_health.status} · FPS ${c.last_health.fps ?? 'não disponível'} · RTT ${c.last_health.rtt_ms ?? 'não disponível'} · bitrate ${c.last_health.bitrate_kbps ?? 'não disponível'} · ${dateTime(String(c.last_health.checked_at))}${c.last_health.simulated ? ' (simulado)' : ''}` : 'sem amostras'}</p>
        <p className="small muted">Jogo vinculado agora: {c.current_assignment ? `${c.current_assignment.title} até ${dateTime(c.current_assignment.ends_at)}` : 'nenhum'} · Sessão ativa: {c.active_session ? 'sim' : 'não'} · Pareamento: {c.pairing?.status || '—'}</p>
      </section>

      <div className="grid2">
        <section className="card stack"><h2>Manutenção / status</h2>
          
          <Field label="Justificativa"><input maxLength={500} value={statusReason} onChange={(e) => setStatusReason(e.target.value)} /></Field>
          <div className="row">
            <button className="btn" disabled={busy || statusReason.length < 3} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'maintenance', reason: statusReason }); onChange(); }, 'Em manutenção.')}>Manutenção</button>
            <button className="btn danger" disabled={busy || statusReason.length < 3} onClick={async () => {
              if (await sure({ title: 'Manutenção com reembolso?', danger: true, confirm: 'Cancelar e reembolsar',
                message: 'O console entra em manutenção e todas as reservas afetadas são canceladas e reembolsadas. Os clientes são avisados.' }))
                run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'maintenance', reason: statusReason, resolution: 'cancel_and_refund' }); onChange(); }, 'Em manutenção; reservas afetadas canceladas e reembolsadas.');
            }}>Manutenção + reembolsar afetados</button>
            <button className="btn" disabled={busy || statusReason.length < 3} onClick={() => run(async () => { await post(`/admin/consoles/${c.id}/status`, { status: 'online', reason: statusReason }); onChange(); }, 'Retornou à operação.')}>Retornar à operação</button>
          </div>
        </section>
        <section className="card stack"><h2>Horário de funcionamento</h2>
          
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
      <section className="card stack" style={{ borderColor: 'rgba(255, 75, 92, .45)' }}><h2>Excluir console</h2>
        
        <p className="small muted" style={{ margin: 0 }}>Remove o console da operação: despublica, arquiva os vínculos futuros e libera capturadora/controle. O histórico (reservas, sessões, auditoria) é mantido.
          Bloqueado se houver sessão ativa ou reservas futuras.</p>
        {onDelete && <div><button className="btn danger" onClick={onDelete}>Excluir este console</button></div>}
      </section>
    </div>
  );
}

export default function Consoles() {
  const list = useApi<AdminConsole[]>('/admin/consoles', 20000);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminConsole | null>(null);
  const [viewing, setViewing] = useState<AdminConsole | null>(null);
  const [nc, setNc] = useState({ code: '', name: '', platform_code: 'PS5' });
  const { run, msg } = useAction();
  const load = async (id: string) => setDetail(await get<AdminConsole>(`/admin/consoles/${id}`));
  const [delC, setDelC] = useState<{ id: string; code: string; name: string } | null>(null);
  const [delTyped, setDelTyped] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const del_ = useAction();
  async function confirmDelete() {
    if (!delC || delTyped !== delC.code || deleteReason.trim().length < 3) return;
    const ok = await del_.run(async () => { await del(`/admin/consoles/${delC.id}`, { reason: deleteReason.trim() }); return true; }, `Console ${delC.name} excluído.`);
    if (ok) { if (sel === delC.id) { setSel(null); setDetail(null); } setDelC(null); list.reload(); }
  }
  const askDelete = (x: { id: string; code: string; name: string }) => { setDelTyped(''); setDeleteReason(''); setDelC(x); };
  useEffect(() => { if (sel) load(sel); }, [sel]);
  return (
    <div className="stack">
      <PageHeader title="Consoles e conexão" subtitle="Cadastro independente de jogos; método de conexão individual por console." />
      {msg}
      {!delC && del_.msg}
      <NewRecord title="Novo console">{(close) => <div className="row">
        <input className="btn" placeholder="Código (PS5-05)" value={nc.code} onChange={(e) => setNc({ ...nc, code: e.target.value.toUpperCase() })} />
        <input className="btn" placeholder="Nome (PS5 nº 05)" value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })} />
        <select className="btn" value={nc.platform_code} onChange={(e) => setNc({ ...nc, platform_code: e.target.value })}>{['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((p) => <option key={p}>{p}</option>)}</select>
        <button className="btn primary" onClick={() => run(async () => { const c = await post<AdminConsole>('/admin/consoles', nc); list.reload(); setSel(c.id); setNc({ code: '', name: '', platform_code: 'PS5' }); close(); }, 'Console criado como "não configurado".')}>Cadastrar</button></div>}</NewRecord>
      <section className="card"><h2>Consoles cadastrados</h2><DataTable rows={list.data as unknown as Record<string, unknown>[] | null} cols={[
        ['Console', (r) => String(r.name)], ['Plataforma', (r) => String(r.platform_code)],
        ['Método', (r) => String((r.connection as Conn)?.method_label || '—')], ['Status', (r) => <StatusPill status={String(r.status)} />],
        ['Publicado', (r) => (r.is_published ? 'sim' : 'não')], ['Jogo agora', (r) => String((r.current_assignment as { title?: string })?.title || '—')],
        ['Ações', (r) => <div className="row">
          <button className="btn sm" onClick={() => run(async () => setViewing(await get<AdminConsole>(`/admin/consoles/${r.id}`)))}>Ver</button>
          <button className="btn sm" onClick={() => setSel(String(r.id))}>Editar</button>
          <button className="btn sm danger" onClick={() => askDelete({ id: String(r.id), code: String(r.code), name: String(r.name) })}>Excluir</button>
        </div>]]} /></section>
      {viewing && <Modal title={viewing.name} onClose={() => setViewing(null)} allowEscape>
        <dl><dt>Código</dt><dd>{viewing.code}</dd><dt>Plataforma</dt><dd>{viewing.platform_code}</dd>
          <dt>Conexão</dt><dd>{viewing.connection.method_label ?? viewing.connection.method}</dd>
          <dt>Status</dt><dd><StatusPill status={viewing.status} /></dd></dl>
      </Modal>}
      {detail && detail.id === sel && !delC && <Modal title={`Editar ${detail.name}`} onClose={() => { setSel(null); setDetail(null); }}>
        <ConsoleEditor key={detail.id + JSON.stringify(detail.connection.version)} c={detail} onChange={() => { load(detail.id); list.reload(); }} onDelete={() => askDelete(detail)} />
      </Modal>}
      {delC && (
        <Modal title="Excluir console" onClose={() => setDelC(null)}>
          <div className="stack">
            <p style={{ margin: 0 }}>Excluir <b>{delC.name}</b>? Ele sai da operação e do painel; o histórico é mantido.</p>
            <Field label={`Digite o código do console para confirmar: ${delC.code}`}><input value={delTyped} onChange={(e) => setDelTyped(e.target.value.toUpperCase())} /></Field>
            <Field label="Motivo da exclusão" required><textarea maxLength={500} value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} /></Field>
            <div className="row"><button className="btn danger" disabled={del_.busy || delTyped !== delC.code || deleteReason.trim().length < 3} onClick={confirmDelete}>Excluir console</button>
              <button className="btn" onClick={() => setDelC(null)}>Cancelar</button></div>
            {del_.msg}
          </div>
        </Modal>)}
    </div>
  );
}
