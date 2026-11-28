'use client';
import { useEffect } from 'react';
import { CheckCircle2, Wifi } from 'lucide-react';
import { Alert, Field } from '@/components/ui';
import { put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { useAction } from '@/components/admin/common';
import type { OwnerConsole } from './shared';
import { useDraftValue } from './registrationDraft';

type Settings = { method: 'remote_play_native' | 'remote_play_chiaki'; network_route: 'lan' | 'internet_psn' | 'internet_port_forward';
  console_identifier: string; internal_host: string; public_host: string; public_port: number | null; resolution: '720p' | '1080p';
  fps: 30 | 60; bitrate_kbps: number; standby_after_session: boolean; keep_awake_minutes: number };
const DEFAULT: Settings = { method: 'remote_play_native', network_route: 'internet_psn', console_identifier: '', internal_host: '', public_host: '',
  public_port: null, resolution: '720p', fps: 30, bitrate_kbps: 6000, standby_after_session: true, keep_awake_minutes: 15 };

/** Método de conexão e qualidade da transmissão propostos pelo proprietário (a equipe aplica com o agente). */
export default function OwnerConnection({ console: c, onSaved, wizard = false }: { console: OwnerConsole; onSaved: () => void; wizard?: boolean }) {
  const data = useApi<{ current: (Omit<Partial<Settings>, 'method'> & { method: string }) | null; pending: Settings | null }>(`/owner/consoles/${c.id}/connection-settings`);
  const [s, setS, cached] = useDraftValue<Settings>('connection', DEFAULT);
  const { run, msg, busy } = useAction();
  useEffect(() => {
    const src = data.data?.pending ?? (data.data?.current && data.data.current.method !== 'unconfigured' ? data.data.current : null);
    if (src && !cached) setS({ ...DEFAULT, ...src, console_identifier: src.console_identifier ?? '', internal_host: src.internal_host ?? '', public_host: src.public_host ?? '' } as Settings);
  }, [data.data, cached]);
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS((x) => ({ ...x, [k]: v }));
  const locked = c.review_status === 'submitted';
  const isPs4 = c.platform_code === 'PS4';

  return <div className="card stack">
    {!wizard && <h2 style={{ margin: 0 }}>Conexão e transmissão</h2>}
    <p className="small muted" style={{ margin: 0 }}>Defina como o agente se conecta ao console e a qualidade da imagem enviada ao jogador.</p>
    {msg}{!wizard && data.data?.pending && <Alert kind="info">Configuração salva{c.approved_at ? ': clique em "Aplicar configuração e testar" em Validação e publicação.' : ' e enviada junto com a análise.'}</Alert>}
    {!isPs4 && <Alert kind="warn">Por enquanto o aluguel pela internet (PSN) funciona só com PS4. Este console ainda não pode ser configurado.</Alert>}
    <div className="stack" style={{ gap: 6 }}>
      <span className="small muted">Tipo de conexão</span>
      <div className="owner-wizard-method"><Wifi size={21} aria-hidden /><strong>Remote Play (PSN)</strong><CheckCircle2 size={18} aria-hidden /></div>
    </div>
    <div className="grid2">
      <Field label="Identificação do console" hint="Nome do console na PSN (Configurações › Sistema › Informações do sistema)">
        <input maxLength={80} disabled={locked} value={s.console_identifier} onChange={(e) => set('console_identifier', e.target.value)} /></Field>
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
    <div><button className="btn primary" disabled={busy || locked || !isPs4} onClick={() => run(async () => {
      await put(`/owner/consoles/${c.id}/connection-settings`, { method: 'remote_play_native', network_route: 'internet_psn',
        console_identifier: s.console_identifier || null, resolution: s.resolution, fps: s.fps, bitrate_kbps: s.bitrate_kbps,
        standby_after_session: s.standby_after_session, keep_awake_minutes: s.keep_awake_minutes });
      data.reload(); onSaved();
    }, 'Configuração de conexão salva.')}>{wizard ? 'Salvar e continuar' : 'Salvar conexão e transmissão'}</button></div>
  </div>;
}
