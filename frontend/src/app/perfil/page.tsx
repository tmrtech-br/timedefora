'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import GoogleButton from '@/components/GoogleButton';
import RequireAuth from '@/components/RequireAuth';
import { Alert, Field, PageHeader } from '@/components/ui';
import { ApiError, api, del, patch, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';

type Stats = { minutes_played: number; sessions: number; total_spent_cents: number; favorites: number; top_games: { title: string; minutes: number }[] };
type Link_ = { id: string; provider: string; link_type: string; provider_email: string | null; public_url: string | null; display_name: string | null };

function Perfil() {
  const { me, refresh } = useAuth();
  const sp = useSearchParams();
  const stats = useApi<Stats>('/me/stats');
  const links = useApi<Link_[]>('/me/linked-accounts');
  const [f, setF] = useState({ full_name: '', username: '' });
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(sp.get('google') === 'vinculado' ? { k: 'ok', t: 'Conta Google vinculada.' } : sp.get('google') === 'ja_vinculado' ? { k: 'error', t: 'Esta conta Google já está vinculada a outro usuário.' } : null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [email, setEmail] = useState({ new_email: '', password: '', code: '' });
  const [emailStep, setEmailStep] = useState(false);
  const [profile, setProfile] = useState({ provider: 'twitch', public_url: '' });
  useEffect(() => { if (me) setF({ full_name: me.full_name, username: me.username }); }, [me]);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null); setFields({});
    try { await fn(); setMsg({ k: 'ok', t: ok }); await refresh(); } catch (e) { const a = e as ApiError; setMsg({ k: 'error', t: a.message }); setFields(a.fields || {}); }
  };
  async function upload(file: File) {
    const fd = new FormData(); fd.append('file', file);
    await run(() => api('/me/avatar', { method: 'POST', body: fd }), 'Avatar atualizado.');
  }
  if (!me) return null;
  return (
    <div className="stack">
      <PageHeader title="Perfil" subtitle="Seus dados, contas vinculadas e estatísticas." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <div className="grid2">
        <section className="card stack">
          <h2>Dados pessoais</h2>
          <div className="row">{me.avatar_url ? <img className="avatar" style={{ width: 64, height: 64 }} src={me.avatar_url} alt="Seu avatar" /> : <span className="avatar" style={{ width: 64, height: 64, fontSize: 26 }}>{me.username[0]}</span>}
            <label className="btn sm">Trocar avatar<input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label></div>
          <Field label="Nome completo (privado)" required error={fields.full_name}><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Nome de usuário público (aparece nas filas)" required hint="3 a 24 caracteres: letras, números, _ ou ." error={fields.username}><input maxLength={24} value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
          <button className="btn primary" onClick={() => {
            const miss: Record<string, string> = {};
            if (!f.full_name.trim()) miss.full_name = 'Preencha este campo.';
            if (!f.username.trim()) miss.username = 'Preencha este campo.';
            if (Object.keys(miss).length) { setFields(miss); setMsg({ k: 'error', t: 'Preencha os campos obrigatórios.' }); return; }
            run(() => patch('/me', { full_name: f.full_name.trim(), username: f.username.trim() }), 'Perfil atualizado.');
          }}>Salvar</button>
        </section>
        <section className="card stack">
          <h2>E-mail</h2>
          <p className="muted">Atual: <b>{me.email}</b> {me.email_verified ? <span className="pill green">confirmado</span> : <a className="pill amber" href="/verificar-email">confirmar</a>}</p>
          {!emailStep ? <>
            <Field label="Novo e-mail"><input maxLength={254} type="email" value={email.new_email} onChange={(e) => setEmail({ ...email, new_email: e.target.value })} /></Field>
            {me.has_password && <Field label="Senha atual"><input type="password" value={email.password} onChange={(e) => setEmail({ ...email, password: e.target.value })} /></Field>}
            <button className="btn" onClick={() => run(async () => { await post('/me/email', { new_email: email.new_email, password: email.password }); setEmailStep(true); }, 'Código enviado para o novo e-mail.')}>Trocar e-mail</button>
          </> : <>
            <Field label="Código enviado ao novo e-mail"><input inputMode="numeric" maxLength={6} value={email.code} onChange={(e) => setEmail({ ...email, code: e.target.value })} /></Field>
            <div className="row"><button className="btn primary" onClick={() => run(async () => { await post('/me/email/confirm', { code: email.code }); setEmailStep(false); }, 'E-mail alterado.')}>Confirmar</button>
              <button className="btn" onClick={() => run(() => post('/me/email/resend'), 'Código reenviado.')}>Reenviar</button></div>
          </>}
        </section>
      </div>
      <div className="grid2">
        <section className="card">
          <h2>Estatísticas</h2>
          {stats.data && <dl className="kv"><dt>Horas jogadas</dt><dd>{(stats.data.minutes_played / 60).toFixed(1)} h</dd><dt>Sessões</dt><dd>{stats.data.sessions}</dd>
            <dt>Total gasto</dt><dd>{money(stats.data.total_spent_cents)}</dd><dt>Favoritos</dt><dd>{stats.data.favorites}</dd>
            <dt>Mais jogados</dt><dd>{stats.data.top_games.map((t) => `${t.title} (${t.minutes} min)`).join(', ') || '—'}</dd></dl>}
          <p className="small dim" style={{ marginTop: 10 }}>Conta criada em {dateTime(me.created_at)}. Conquistas internas: em breve.</p>
        </section>
        <section className="card stack">
          <h2>Contas vinculadas</h2>
          {links.data?.map((l) => (
            <div key={l.id} className="spread"><span><b>{l.provider === 'google' ? 'Google' : l.provider[0].toUpperCase() + l.provider.slice(1)}</b> · {l.link_type === 'oauth' ? `OAuth (${l.provider_email})` : <>perfil público: <a className="link-purple" href={l.public_url || '#'} target="_blank" rel="noopener noreferrer">{l.display_name}</a></>}</span>
              <button className="btn sm danger" onClick={() => run(async () => { await del(`/me/linked-accounts/${l.id}`); links.reload(); }, 'Desvinculado.')}>Remover</button></div>
          ))}
          {!links.data?.some((l) => l.provider === 'google') && <GoogleButton intent="link" label="Vincular conta Google" />}
          <div className="row">
            <select className="btn" value={profile.provider} onChange={(e) => setProfile({ ...profile, provider: e.target.value })} aria-label="Serviço">
              <option value="twitch">Twitch</option><option value="kick">Kick</option><option value="discord">Discord</option></select>
            <input className="btn" style={{ flex: 1, minWidth: 200 }} placeholder="URL do perfil público" maxLength={500} value={profile.public_url} onChange={(e) => setProfile({ ...profile, public_url: e.target.value })} />
            <button className="btn" onClick={() => run(async () => { await post('/me/linked-accounts', profile); setProfile({ ...profile, public_url: '' }); links.reload(); }, 'Perfil público adicionado.')}>Adicionar</button>
          </div>
          <p className="small dim">Twitch, Kick e Discord: apenas link de perfil público (sem login nem senha desses serviços). Isso é diferente do canal oficial de transmissão dos consoles.</p>
        </section>
      </div>
    </div>
  );
}
export default function Page() { return <RequireAuth><Suspense><Perfil /></Suspense></RequireAuth>; }
