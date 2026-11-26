'use client';
import { useMemo, useState } from 'react';
import { Alert, Field, Modal, PageHeader } from '@/components/ui';
import { put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { useAction } from './common';

type S = { values: Record<string, unknown>; defaults: Record<string, unknown>; critical: string[] };
type Platform = { code: string; name: string; family: string };

/** Parâmetros liga/desliga: cada um é aplicado no servidor (a interface apenas esconde o que estiver desligado). */
const TOGGLES: { key: string; title: string; desc: string; invert?: boolean }[] = [
  { key: 'sales_paused', invert: true, title: 'Vendas de tempo (fichas)', desc: 'Desligado: ninguém consegue comprar tempo novo. Reservas já pagas continuam valendo.' },
  { key: 'queue_mode_enabled', title: 'Compra em modo fila', desc: 'Cliente entra na fila do console e joga assim que chegar a vez.' },
  { key: 'scheduled_mode_enabled', title: 'Compra com horário marcado', desc: 'Cliente escolhe dia e hora exatos para jogar.' },
  { key: 'coupons_enabled', title: 'Cupons de desconto', desc: 'Desligado: o campo de cupom some e cupons são recusados.' },
  { key: 'signup_enabled', title: 'Novos cadastros', desc: 'Desligado: cadastro por e-mail e criação de conta pelo Google ficam bloqueados. Quem já tem conta continua entrando.' },
  { key: 'google_login_enabled', title: 'Entrar com Google', desc: 'Mostra/oculta e habilita o login com Google.' },
  { key: 'keyboard_mouse_enabled', title: 'Jogar com teclado e mouse', desc: 'Desligado: só é possível jogar com controle.' },
  { key: 'public_streams_enabled', title: 'Transmissões ao vivo (Assistir ao vivo)', desc: 'Mostra/oculta os links para Twitch/Kick nas páginas dos jogos e na home.' },
  { key: 'support_tickets_enabled', title: 'Abertura de chamados no suporte', desc: 'Desligado: novos chamados bloqueados; respostas em chamados abertos continuam.' },
  { key: 'share_button_enabled', title: 'Botão Share do controle', desc: 'Desligado (recomendado): o cliente não abre o menu de compartilhar/transmitir nem publica capturas pela conta do console.' },
];

const NUMBERS: { key: string; title: string; unit: string; min: number; max: number }[] = [
  { key: 'hold_minutes', title: 'Tempo para pagar a reserva', unit: 'min', min: 1, max: 60 },
  { key: 'setup_minutes', title: 'Intervalo de preparação entre jogadores', unit: 'min', min: 0, max: 30 },
  { key: 'scheduled_lead_minutes', title: 'Antecedência mínima do horário marcado', unit: 'min', min: 0, max: 1440 },
  { key: 'queue_lead_minutes', title: 'Antecedência mínima no modo fila', unit: 'min', min: 0, max: 120 },
  { key: 'booking_horizon_days', title: 'Reservar com até quantos dias de antecedência', unit: 'dias', min: 1, max: 90 },
  { key: 'max_pending_holds_per_user', title: 'Reservas aguardando pagamento por cliente', unit: 'reservas', min: 1, max: 10 },
  { key: 'max_future_reservations_per_user', title: 'Reservas futuras por cliente', unit: 'reservas', min: 1, max: 50 },
  { key: 'cancel_full_refund_min_minutes_before', title: 'Reembolso integral se cancelar com antecedência de', unit: 'min', min: 0, max: 10080 },
  { key: 'no_show_tolerance_minutes', title: 'Tolerância de ausência', unit: 'min', min: 0, max: 60 },
  { key: 'featured_window_days', title: 'Período para calcular o "mais jogado"', unit: 'dias', min: 1, max: 90 },
  { key: 'agent_heartbeat_timeout_seconds', title: 'Tempo sem sinal do agente para marcar console offline', unit: 's', min: 30, max: 900 },
  { key: 'player_video_max_kbps', title: 'Qualidade máxima do vídeo para o jogador (720p30: 4000 · 720p60: 6000 · internet fraca: 2500)', unit: 'kbps', min: 1000, max: 15000 },
  { key: 'owner_share_bps', title: 'Parcela do proprietário (3000 = 30%)', unit: 'pontos-base', min: 0, max: 10000 },
];

const FAMILY: Record<string, string> = { playstation: 'PlayStation', xbox: 'Xbox', nintendo: 'Nintendo', other: 'Outros' };

type Pending = { key: string; value: unknown; label: string };

export default function Params() {
  const s = useApi<S>('/admin/settings');
  const plats = useApi<Platform[]>('/admin/platforms').data;
  const consoles = useApi<{ id: string; platform_code: string }[]>('/admin/consoles').data;
  const { run, msg, busy } = useAction();
  const [pending, setPending] = useState<Pending | null>(null);
  const [reason, setReason] = useState('');
  const [nums, setNums] = useState<Record<string, string>>({});
  const [pausedReason, setPausedReason] = useState<string | null>(null);
  const v = s.data?.values || {};
  const off = (v.disabled_platforms as string[] | undefined) || [];
  const byFamily = useMemo(() => {
    const m: Record<string, Platform[]> = {};
    (plats || []).forEach((p) => { (m[p.family] ||= []).push(p); });
    return m;
  }, [plats]);
  const consoleCount = (code: string) => (consoles || []).filter((c) => c.platform_code === code).length;

  function ask(key: string, value: unknown, label: string) { setReason(''); setPending({ key, value, label }); }
  async function confirm() {
    if (!pending) return;
    const ok = await run(async () => { await put(`/admin/settings/${pending.key}`, { value: pending.value, reason }); s.reload(); return true; }, 'Parâmetro salvo.');
    if (ok) setPending(null);
  }
  const togglePlatforms = (codes: string[], turnOn: boolean, label: string) => {
    const next = turnOn ? off.filter((c) => !codes.includes(c)) : Array.from(new Set([...off, ...codes]));
    ask('disabled_platforms', next, `${turnOn ? 'Ligar' : 'Desligar'} ${label}`);
  };

  if (!s.data) return <div className="skeleton" style={{ height: 300 }} />;
  return (
    <div className="stack">
      <PageHeader title="Parâmetros do sistema" subtitle="Ligue e desligue funções. Cada alteração vale na hora, é aplicada no servidor e fica registrada na auditoria." />
      {msg}

      <section className="card stack"><h2 style={{ margin: 0 }}>Plataformas e consoles</h2>
        <p className="small muted" style={{ margin: 0 }}>Desligar uma plataforma tira da venda todos os consoles dela e esconde do catálogo os jogos que só existem nela. Reservas já pagas continuam valendo.</p>
        <div className="params">
          {Object.entries(byFamily).map(([fam, list]) => {
            const codes = list.map((p) => p.code);
            const famOn = codes.some((c) => !off.includes(c));
            return (
              <div key={fam} className="param-group">
                <div className={`param ${famOn ? '' : 'off'}`}>
                  <div><h3>{FAMILY[fam] || fam} (todas)</h3><p>{list.map((p) => p.name).join(', ')}</p></div>
                  <button className="switch" role="switch" aria-checked={famOn} aria-label={`${FAMILY[fam] || fam}: ${famOn ? 'ligado' : 'desligado'}`} disabled={busy}
                    onClick={() => togglePlatforms(codes, !famOn, `todas as plataformas ${FAMILY[fam] || fam}`)} />
                </div>
                {list.length > 1 && list.map((p) => {
                  const on = !off.includes(p.code);
                  return (
                    <div key={p.code} className={`param sub ${on ? '' : 'off'}`}>
                      <div><h3>{p.name}</h3><p>{consoleCount(p.code)} console(s) cadastrado(s)</p></div>
                      <button className="switch" role="switch" aria-checked={on} aria-label={`${p.name}: ${on ? 'ligado' : 'desligado'}`} disabled={busy}
                        onClick={() => togglePlatforms([p.code], !on, p.name)} />
                    </div>);
                })}
              </div>);
          })}
        </div>
      </section>

      <section className="card stack"><h2 style={{ margin: 0 }}>Funções</h2>
        <div className="params">
          {TOGGLES.map((t) => {
            const raw = Boolean(v[t.key]);
            const on = t.invert ? !raw : raw;
            return (
              <div key={t.key} className={`param ${on ? '' : 'off'}`}>
                <div><h3>{t.title}{s.data!.critical.includes(t.key) && <span className="pill amber" style={{ marginLeft: 8 }}>crítico</span>}</h3><p>{t.desc}</p>
                  {t.key === 'sales_paused' && raw && <p style={{ marginTop: 4 }}>Mensagem aos clientes: <i>{String(v.sales_paused_reason || '(sem mensagem)')}</i>
                    <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => setPausedReason(String(v.sales_paused_reason || ''))}>Editar</button></p>}</div>
                <button className="switch" role="switch" aria-checked={on} aria-label={`${t.title}: ${on ? 'ligado' : 'desligado'}`} disabled={busy}
                  onClick={() => ask(t.key, t.invert ? on : !on, `${on ? 'Desligar' : 'Ligar'}: ${t.title}`)} />
              </div>);
          })}
        </div>
      </section>

      <section className="card stack"><h2 style={{ margin: 0 }}>Regras de agenda e limites</h2>
        <div className="params">
          {NUMBERS.filter((n) => n.key in v).map((n) => {
            const cur = String(v[n.key]);
            const val = nums[n.key] ?? cur;
            const num = Number(val);
            const invalid = val.trim() === '' || !Number.isInteger(num) || num < n.min || num > n.max;
            return (
              <div key={n.key} className="param">
                <div><h3>{n.title}{s.data!.critical.includes(n.key) && <span className="pill amber" style={{ marginLeft: 8 }}>crítico</span>}</h3><p>Atual: {cur} {n.unit} · padrão {String(s.data!.defaults[n.key])} · de {n.min} a {n.max}</p></div>
                <div className="param-ctrl">
                  <input className="btn sm" type="number" min={n.min} max={n.max} value={val} aria-label={n.title} aria-invalid={invalid || undefined}
                    onChange={(e) => setNums({ ...nums, [n.key]: e.target.value })} />
                  <span className="small dim">{n.unit}</span>
                  <button className="btn sm" disabled={busy || invalid || val === cur} onClick={() => ask(n.key, num, `${n.title}: ${cur} → ${num} ${n.unit}`)}>Salvar</button>
                </div>
              </div>);
          })}
        </div>
      </section>

      {pausedReason !== null && (
        <Modal title="Mensagem de vendas pausadas" onClose={() => setPausedReason(null)}>
          <div className="stack">
            <Field label="Mensagem exibida aos clientes" hint="Ex.: Voltamos às 18h."><input maxLength={200} value={pausedReason} onChange={(e) => setPausedReason(e.target.value)} /></Field>
            <div className="row"><button className="btn primary" disabled={busy} onClick={() => { const val = pausedReason; setPausedReason(null); ask('sales_paused_reason', val, 'Alterar a mensagem de vendas pausadas'); }}>Continuar</button>
              <button className="btn" onClick={() => setPausedReason(null)}>Voltar</button></div>
          </div>
        </Modal>)}

      {pending && (
        <Modal title="Confirmar alteração" onClose={() => setPending(null)}>
          <div className="stack">
            <Alert kind="warn">{pending.label}</Alert>
            <Field label="Motivo (registrado na auditoria)" hint="Opcional, mas recomendado."><input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <div className="row"><button className="btn primary" disabled={busy} onClick={confirm}>Confirmar</button><button className="btn" onClick={() => setPending(null)}>Cancelar</button></div>
            {msg}
          </div>
        </Modal>)}
    </div>
  );
}
