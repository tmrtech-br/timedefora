'use client';
import { useEffect, useState } from 'react';
import { Alert, Field } from '@/components/ui';
import { put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { useAction } from '@/components/admin/common';
import type { OwnerConsole } from './shared';

type Settings = { method: 'remote_play_native' | 'remote_play_chiaki'; network_route: 'lan' | 'internet_psn' | 'internet_port_forward';
  console_identifier: string; internal_host: string; public_host: string; public_port: number | null; resolution: '720p' | '1080p';
  fps: 30 | 60; bitrate_kbps: number; standby_after_session: boolean; keep_awake_minutes: number };
const DEFAULT: Settings = { method: 'remote_play_native', network_route: 'internet_psn', console_identifier: '', internal_host: '', public_host: '',
  public_port: null, resolution: '720p', fps: 30, bitrate_kbps: 6000, standby_after_session: true, keep_awake_minutes: 15 };
const ROUTES: Record<string, string> = { internet_psn: 'Pela internet (PSN) — o console pode estar em outro lugar', lan: 'Mesma rede do agente',
  internet_port_forward: 'Pela internet com redirecionamento de porta' };

/** Método de conexão e qualidade da transmissão propostos pelo proprietário (a equipe aplica com o agente). */
export default function OwnerConnection({ console: c, onSaved }: { console: OwnerConsole; onSaved: () => void }) {
  const data = useApi<{ current: (Omit<Partial<Settings>, 'method'> & { method: string }) | null; pending: Settings | null }>(`/owner/consoles/${c.id}/connection-settings`);
  const [s, setS] = useState<Settings>(DEFAULT);
  const { run, msg, busy } = useAction();
  useEffect(() => {
    const src = data.data?.pending ?? (data.data?.current && data.data.current.method !== 'unconfigured' ? data.data.current : null);
    if (src) setS({ ...DEFAULT, ...src, console_identifier: src.console_identifier ?? '', internal_host: src.internal_host ?? '', public_host: src.public_host ?? '' } as Settings);
  }, [data.data]);
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS((x) => ({ ...x, [k]: v }));
  const locked = c.review_status === 'submitted';
  const isPs4 = c.platform_code === 'PS4';
  // Rotas válidas para este console/método (PSN pelo Remote Play nativo só existe no PS4; porta redirecionada só no chiaki).
  const routes = (['internet_psn', 'lan', 'internet_port_forward'] as const).filter((r) => r !== 'internet_port_forward' || s.method === 'remote_play_chiaki')
    .filter((r) => r !== 'internet_psn' || isPs4 || s.method === 'remote_play_chiaki');
  useEffect(() => { if (!routes.includes(s.network_route)) setS((x) => ({ ...x, network_route: routes[0] })); }, [routes.join(), s.network_route]);
  return <div className="card stack">
    <h2 style={{ margin: 0 }}>Conexão e transmissão</h2>
    <p className="small muted" style={{ margin: 0 }}>Como o agente vai se conectar ao console e a qualidade da imagem enviada ao jogador.
      A equipe aplica essa configuração ao aprovar; depois você testa e publica.</p>
    {msg}{data.data?.pending && <Alert kind="info">Configuração salva{c.approved_at ? ': clique em "Aplicar configuração e testar" em Validação e publicação.' : ' e enviada junto com a análise.'}</Alert>}
    <div className="grid2">
      <Field label="Método de conexão"><select value={s.method} disabled={locked} onChange={(e) => set('method', e.target.value as Settings['method'])}>
        <option value="remote_play_native">Remote Play (recomendado)</option><option value="remote_play_chiaki">Remote Play via chiaki-ng</option></select></Field>
      <Field label="Rota de rede"><select value={s.network_route} disabled={locked} onChange={(e) => set('network_route', e.target.value as Settings['network_route'])}>
        {routes.map((r) => <option key={r} value={r}>{ROUTES[r]}</option>)}</select></Field>
      <Field label="Identificação do console" hint="Nome do console na PSN ou o código cadastrado (ex.: PS4-JOAO-01)">
        <input maxLength={80} disabled={locked} value={s.console_identifier} onChange={(e) => set('console_identifier', e.target.value)} /></Field>
      {s.network_route === 'lan' && <Field label="IP do console na rede" hint="Fixe o IP no roteador (ex.: 192.168.0.50)">
        <input maxLength={120} disabled={locked} value={s.internal_host} onChange={(e) => set('internal_host', e.target.value)} /></Field>}
      {s.network_route === 'internet_port_forward' && <Field label="IP público ou DDNS do roteador">
        <input maxLength={253} disabled={locked} value={s.public_host} onChange={(e) => set('public_host', e.target.value)} /></Field>}
      <Field label="Resolução"><select value={s.resolution} disabled={locked} onChange={(e) => set('resolution', e.target.value as Settings['resolution'])}>
        <option value="720p">720p (recomendado)</option><option value="1080p">1080p (PS4 Pro/PS5)</option></select></Field>
      <Field label="Quadros por segundo"><select value={s.fps} disabled={locked} onChange={(e) => set('fps', Number(e.target.value) as Settings['fps'])}>
        <option value={30}>30 fps</option><option value={60}>60 fps</option></select></Field>
      <Field label="Taxa de vídeo (kbps)" hint="6000 é o padrão; internet do local mais fraca: 3000"><input type="number" min={1500} max={15000} disabled={locked}
        value={s.bitrate_kbps} onChange={(e) => set('bitrate_kbps', Number(e.target.value))} /></Field>
      <Field label="Manter ligado se houver reserva em (min)"><input type="number" min={0} max={240} disabled={locked}
        value={s.keep_awake_minutes} onChange={(e) => set('keep_awake_minutes', Number(e.target.value))} /></Field>
    </div>
    <label className="check"><input type="checkbox" disabled={locked} checked={s.standby_after_session} onChange={(e) => set('standby_after_session', e.target.checked)} />
      Colocar o console em repouso quando ninguém for usar</label>
    <div><button className="btn primary" disabled={busy || locked} onClick={() => run(async () => {
      await put(`/owner/consoles/${c.id}/connection-settings`, { ...s, public_port: s.public_port || null, internal_host: s.internal_host || null,
        public_host: s.public_host || null, console_identifier: s.console_identifier || null });
      data.reload(); onSaved();
    }, c.approved_at ? 'Configuração salva: envie para análise para a equipe validar.' : 'Configuração de conexão salva.')}>Salvar conexão e transmissão</button></div>
  </div>;
}
