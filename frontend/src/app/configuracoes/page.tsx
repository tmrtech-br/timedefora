'use client';
import { useState } from 'react';
import LimitedScroll from '@/components/LimitedScroll';
import RequireAuth from '@/components/RequireAuth';
import QrCode from '@/components/QrCode';
import { toast } from '@/components/Toaster';
import { Alert, Empty, ErrorBox, Field, PageHeader, Skeleton } from '@/components/ui';
import { ApiError, del, get, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { DATA_REQUEST_STATUS, dateTime } from '@/lib/format';
import styles from './settings.module.css';

type Prefs = { email_queue_updates: boolean; email_reminders: boolean; email_marketing: boolean; in_app_enabled: boolean; reminder_minutes: number[] };
type Sess = { id: string; ip: string; user_agent: string; created_at: string; last_seen_at: string; current: boolean };
type DR = { id: string; request_type: string; status: string; created_at: string; resolution: string | null };
const DR_LABEL: Record<string, string> = { access: 'Acesso', rectification: 'Retificação', deletion: 'Exclusão da conta', portability: 'Portabilidade', consent_revocation: 'Revogar consentimento' };
const NOTIFICATION_OPTIONS = [
  ['in_app_enabled', 'Notificações no site'],
  ['email_reminders', 'E-mails de lembrete (15/10/1 min). O aviso de 5 minutos e o “sua vez chegou” são sempre enviados.'],
  ['email_queue_updates', 'E-mails de mudança na fila'],
  ['email_marketing', 'Novidades e promoções (opcional)'],
] as const;

function NotificationSwitch({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) {
  return <label className={styles.switchRow}>
    <span>{label}</span>
    <input type="checkbox" role="switch" className={`switch ${styles.toggle}`} checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
  </label>;
}

function Config() {
  const { me, refresh } = useAuth();
  const prefs = useApi<Prefs>('/me/notification-preferences');
  const sessions = useApi<Sess[]>('/me/sessions');
  const drs = useApi<DR[]>('/me/data-requests');
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [mfa, setMfa] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[]>([]);
  const [dr, setDr] = useState({ request_type: 'access', details: '' });
  const run = async (fn: () => Promise<unknown>, message: string, kind: 'ok' | 'info' = 'ok') => {
    try {
      await fn();
      toast(kind, message);
    } catch (error) {
      toast('error', error instanceof ApiError ? error.message : 'Não foi possível concluir a ação.');
    }
  };
  async function savePrefs(patch: Partial<Prefs>) {
    if (savingPrefs) return;
    setSavingPrefs(true);
    try {
      await run(async () => prefs.setData(await put<Prefs>('/me/notification-preferences', patch)), 'Preferências salvas.');
    } finally {
      setSavingPrefs(false);
    }
  }
  async function exportData() {
    const data = await get('/me/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'meus-dados-timedefora.json'; a.click(); URL.revokeObjectURL(url);
  }
  if (!me) return null;
  const p = prefs.data;
  return (
    <div className="stack">
      <PageHeader title="Configurações" subtitle="Notificações, segurança e privacidade." />
      <div className={`grid2 ${styles.cards}`}>
        <section className={`card stack ${styles.notifications}`}>
          <h2>Notificações</h2>
          <ErrorBox error={prefs.error} onRetry={prefs.reload} />
          {p && <>
            {NOTIFICATION_OPTIONS.map(([key, label]) => <NotificationSwitch key={key} label={label} checked={p[key]} disabled={savingPrefs}
              onChange={(checked) => void savePrefs({ [key]: checked })} />)}
            <fieldset className={styles.reminders}>
              <legend>Avisos antes da vez</legend>
              {[15, 10, 5, 1].map((minutes) => <NotificationSwitch key={minutes} label={`${minutes} min`}
                checked={minutes === 5 || p.reminder_minutes.includes(minutes)} disabled={savingPrefs || minutes === 5}
                onChange={(checked) => void savePrefs({ reminder_minutes: checked ? [...p.reminder_minutes, minutes] : p.reminder_minutes.filter((value) => value !== minutes) })} />)}
            </fieldset>
          </>}
        </section>
        <section className="card stack">
          <h2>Autenticação em dois fatores (TOTP)</h2>
          <p className="muted small">Obrigatória para operadores e administradores; recomendada para todos.</p>
          {me.mfa_enabled ? <>
            <div><span className="pill green">Ativa</span></div>
            <Field label="Código atual para desativar"><input maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <button className="btn danger" onClick={() => run(async () => { await post('/me/mfa/disable', { code }); setCode(''); await refresh(); }, 'Autenticação em dois fatores desativada.')}>Desativar</button>
          </> : !mfa ? <button className="btn primary" onClick={() => run(async () => setMfa(await post('/me/mfa/setup')), 'Escaneie ou digite a chave no seu app autenticador.', 'info')}>Ativar</button> : <>
            <div className="mfa-qr">
              <p className="small" style={{ margin: 0 }}>Escaneie o QR code com o aplicativo autenticador (Google Authenticator, Microsoft Authenticator, Authy…):</p>
              <QrCode value={mfa.otpauth_uri} label="QR code para configurar o aplicativo autenticador" />
              <p className="small" style={{ margin: 0 }}>Ou digite a chave manualmente:<br /><code style={{ wordBreak: 'break-all' }}>{mfa.secret}</code></p>
            </div>
            <Field label="Código de 6 dígitos"><input maxLength={6} inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <button className="btn primary" onClick={() => run(async () => { const r = await post<{ recovery_codes: string[] }>('/me/mfa/confirm', { code }); setRecovery(r.recovery_codes); setMfa(null); setCode(''); await refresh(); }, 'Autenticação em dois fatores ativada.')}>Confirmar</button>
          </>}
          {recovery.length > 0 && <Alert kind="warn" dismissible={false}><span>Códigos de recuperação (guarde agora, não serão exibidos de novo): <code>{recovery.join('  ')}</code></span></Alert>}
        </section>
        <section className="card stack">
          <h2>Privacidade e dados (LGPD)</h2>
          <div className="row"><button className="btn" onClick={exportData}>Baixar meus dados (JSON)</button><a className="btn" href="/privacidade">Política de privacidade</a></div>
          <div className="row">
            <select className="btn" value={dr.request_type} onChange={(e) => setDr({ ...dr, request_type: e.target.value })} aria-label="Tipo de solicitação">
              {Object.entries(DR_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <input className={`btn ${styles.details}`} placeholder="Detalhes (opcional)" maxLength={500} value={dr.details} onChange={(e) => setDr({ ...dr, details: e.target.value })} />
            <button className="btn primary" onClick={() => run(async () => { await post('/me/data-requests', dr); drs.reload(); }, 'Solicitação registrada.')}>Enviar solicitação</button>
          </div>
          {!!drs.data?.length && <LimitedScroll label="Solicitações de privacidade" limit={2}>
            {drs.data.map((d) => <div key={d.id} className={`small ${styles.request}`}>{DR_LABEL[d.request_type]} · {DATA_REQUEST_STATUS[d.status] || d.status} · {dateTime(d.created_at)} {d.resolution && `— ${d.resolution}`}</div>)}
          </LimitedScroll>}
        </section>
        <section className="card stack">
          <div className="spread"><h2>Sessões ativas</h2><button className="btn sm" disabled={!sessions.data?.some((session) => !session.current)} onClick={() => run(async () => { await post('/me/sessions/revoke-others'); await sessions.reload(); }, 'Outras sessões encerradas.')}>Encerrar as outras</button></div>
          <ErrorBox error={sessions.error} onRetry={sessions.reload} />
          {sessions.data?.length ? <LimitedScroll label="Lista de sessões ativas">
            {sessions.data.map((session) => (
              <div key={session.id} className={`spread small ${styles.session}`}>
                <span>{session.current && <span className="pill green">Esta sessão</span>} {session.user_agent?.slice(0, 60) || 'Navegador'} · {session.ip} · Último acesso em {dateTime(session.last_seen_at)}</span>
                {!session.current && <button className="btn sm danger" onClick={() => run(async () => { await del(`/me/sessions/${session.id}`); await sessions.reload(); }, 'Sessão encerrada.')}>Encerrar</button>}
              </div>
            ))}
          </LimitedScroll> : !sessions.error && (sessions.data ? <Empty>Nenhuma sessão ativa.</Empty> : <Skeleton h={100} />)}
        </section>
      </div>
    </div>
  );
}
export default function Page() { return <RequireAuth><Config /></RequireAuth>; }
