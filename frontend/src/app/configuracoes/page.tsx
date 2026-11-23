'use client';
import { useState } from 'react';
import KeyBindingsEditor from '@/components/KeyBindings';
import RequireAuth from '@/components/RequireAuth';
import QrCode from '@/components/QrCode';
import { Alert, Field, PageHeader } from '@/components/ui';
import { ApiError, del, get, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { DATA_REQUEST_STATUS, dateTime } from '@/lib/format';

type Prefs = { email_queue_updates: boolean; email_reminders: boolean; email_marketing: boolean; in_app_enabled: boolean; reminder_minutes: number[] };
type Sess = { id: string; ip: string; user_agent: string; created_at: string; last_seen_at: string; current: boolean };
type DR = { id: string; request_type: string; status: string; created_at: string; resolution: string | null };
const DR_LABEL: Record<string, string> = { access: 'Acesso', rectification: 'Retificação', deletion: 'Exclusão da conta', portability: 'Portabilidade', consent_revocation: 'Revogar consentimento' };

function Config() {
  const { me, refresh } = useAuth();
  const prefs = useApi<Prefs>('/me/notification-preferences');
  const sessions = useApi<Sess[]>('/me/sessions');
  const drs = useApi<DR[]>('/me/data-requests');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  const [pw, setPw] = useState({ current_password: '', new_password: '', new_password_confirm: '' });
  const [mfa, setMfa] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[]>([]);
  const [dr, setDr] = useState({ request_type: 'access', details: '' });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg({ k: 'ok', t: ok }); } catch (e) { setMsg({ k: 'error', t: (e as ApiError).message }); }
  };
  async function savePrefs(patch: Partial<Prefs>) { await run(async () => prefs.setData(await put<Prefs>('/me/notification-preferences', patch)), 'Preferências salvas.'); }
  async function exportData() {
    const data = await get('/me/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'meus-dados-locaplay.json'; a.click(); URL.revokeObjectURL(url);
  }
  if (!me) return null;
  const p = prefs.data;
  return (
    <div className="stack">
      <PageHeader title="Configurações" subtitle="Notificações, controles, segurança e privacidade." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <div className="grid2">
        <section className="card stack">
          <h2>Notificações</h2>
          {p && <>
            <label className="check"><input type="checkbox" checked={p.in_app_enabled} onChange={(e) => savePrefs({ in_app_enabled: e.target.checked })} /><span>Notificações no site</span></label>
            <label className="check"><input type="checkbox" checked={p.email_reminders} onChange={(e) => savePrefs({ email_reminders: e.target.checked })} /><span>E-mails de lembrete (15/10/1 min). O aviso de 5 minutos e o “sua vez chegou” são sempre enviados.</span></label>
            <label className="check"><input type="checkbox" checked={p.email_queue_updates} onChange={(e) => savePrefs({ email_queue_updates: e.target.checked })} /><span>E-mails de mudança na fila</span></label>
            <label className="check"><input type="checkbox" checked={p.email_marketing} onChange={(e) => savePrefs({ email_marketing: e.target.checked })} /><span>Novidades e promoções (opcional)</span></label>
            <div className="row small">Avisos antes da vez:{[15, 10, 5, 1].map((m) => (
              <label key={m} className="check"><input type="checkbox" disabled={m === 5} checked={p.reminder_minutes.includes(m)}
                onChange={(e) => savePrefs({ reminder_minutes: e.target.checked ? [...p.reminder_minutes, m] : p.reminder_minutes.filter((x) => x !== m) })} />{m} min</label>))}</div>
          </>}
        </section>
        <section className="card stack">
          <h2>Senha</h2>
          {me.has_password && <Field label="Senha atual"><input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>}
          <Field label="Nova senha" hint="Mínimo 10 caracteres, com letras e números."><input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <Field label="Confirmar nova senha"><input type="password" autoComplete="new-password" value={pw.new_password_confirm} onChange={(e) => setPw({ ...pw, new_password_confirm: e.target.value })} /></Field>
          <button className="btn primary" onClick={() => run(async () => { await post('/me/password', pw); setPw({ current_password: '', new_password: '', new_password_confirm: '' }); sessions.reload(); }, 'Senha alterada; outras sessões foram encerradas.')}>Alterar senha</button>
        </section>
      </div>
      <div className="grid2">
        <section className="card stack">
          <h2>Autenticação em dois fatores (TOTP)</h2>
          <p className="muted small">Obrigatória para operadores e administradores; recomendada para todos.</p>
          {me.mfa_enabled ? <>
            <Alert kind="ok">Ativa.</Alert>
            <Field label="Código atual para desativar"><input maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <button className="btn danger" onClick={() => run(async () => { await post('/me/mfa/disable', { code }); setCode(''); await refresh(); }, 'Autenticação em dois fatores desativada.')}>Desativar</button>
          </> : !mfa ? <button className="btn primary" onClick={() => run(async () => setMfa(await post('/me/mfa/setup')), 'Escaneie ou digite a chave no seu app autenticador.')}>Ativar</button> : <>
            <div className="mfa-qr">
              <p className="small" style={{ margin: 0 }}>Escaneie o QR code com o aplicativo autenticador (Google Authenticator, Microsoft Authenticator, Authy…):</p>
              <QrCode value={mfa.otpauth_uri} label="QR code para configurar o aplicativo autenticador" />
              <p className="small" style={{ margin: 0 }}>Ou digite a chave manualmente:<br /><code style={{ wordBreak: 'break-all' }}>{mfa.secret}</code></p>
            </div>
            <Field label="Código de 6 dígitos"><input maxLength={6} inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <button className="btn primary" onClick={() => run(async () => { const r = await post<{ recovery_codes: string[] }>('/me/mfa/confirm', { code }); setRecovery(r.recovery_codes); setMfa(null); setCode(''); await refresh(); }, 'Autenticação em dois fatores ativada.')}>Confirmar</button>
          </>}
          {recovery.length > 0 && <Alert kind="warn"><span>Códigos de recuperação (guarde agora, não serão exibidos de novo): <code>{recovery.join('  ')}</code></span></Alert>}
        </section>
        <section className="card stack">
          <div className="spread"><h2>Sessões ativas</h2><button className="btn sm" onClick={() => run(async () => { await post('/me/sessions/revoke-others'); sessions.reload(); }, 'Outras sessões encerradas.')}>Encerrar as outras</button></div>
          {sessions.data?.map((s) => (
            <div key={s.id} className="spread small"><span>{s.current && <span className="pill green">esta</span>} {s.user_agent.slice(0, 60) || 'Navegador'} · {s.ip} · visto {dateTime(s.last_seen_at)}</span>
              {!s.current && <button className="btn sm danger" onClick={() => run(async () => { await del(`/me/sessions/${s.id}`); sessions.reload(); }, 'Sessão encerrada.')}>Encerrar</button>}</div>
          ))}
        </section>
      </div>
      <KeyBindingsEditor />
      <section className="card stack">
        <h2>Privacidade e dados (LGPD)</h2>
        <div className="row"><button className="btn" onClick={exportData}>Baixar meus dados (JSON)</button><a className="btn" href="/privacidade">Política de privacidade</a></div>
        <div className="row">
          <select className="btn" value={dr.request_type} onChange={(e) => setDr({ ...dr, request_type: e.target.value })} aria-label="Tipo de solicitação">
            {Object.entries(DR_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <input className="btn" style={{ flex: 1, minWidth: 220 }} placeholder="Detalhes (opcional)" maxLength={500} value={dr.details} onChange={(e) => setDr({ ...dr, details: e.target.value })} />
          <button className="btn primary" onClick={() => run(async () => { await post('/me/data-requests', dr); drs.reload(); }, 'Solicitação registrada.')}>Enviar solicitação</button>
        </div>
        {drs.data?.map((d) => <div key={d.id} className="small">{DR_LABEL[d.request_type]} · {DATA_REQUEST_STATUS[d.status] || d.status} · {dateTime(d.created_at)} {d.resolution && `— ${d.resolution}`}</div>)}
      </section>
    </div>
  );
}
export default function Page() { return <RequireAuth><Config /></RequireAuth>; }
