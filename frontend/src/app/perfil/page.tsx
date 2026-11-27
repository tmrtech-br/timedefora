'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { Camera } from 'lucide-react';
import GoogleButton from '@/components/GoogleButton';
import PasswordForm from '@/components/PasswordForm';
import RequireAuth from '@/components/RequireAuth';
import { Alert, Field, Modal, PageHeader } from '@/components/ui';
import { ApiError, api, del, patch, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';
import styles from './profile.module.css';

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
  const [passwordOpen, setPasswordOpen] = useState(false);
  const avatarInput = useRef<HTMLInputElement>(null);
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
  const passwordTitle = me.has_password ? 'Alterar senha' : 'Definir senha';
  return (
    <div className="stack">
      <PageHeader title="Perfil" subtitle="Seus dados, contas vinculadas e estatísticas." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <div className={styles.profileCards}>
        <section className={`card stack ${styles.compact} ${styles.personal}`}>
          <h2>Dados pessoais</h2>
          <button type="button" className={styles.avatarButton} aria-label="Trocar avatar" onClick={() => avatarInput.current?.click()}>
            {me.avatar_url ? <img src={me.avatar_url} alt="" /> : <span aria-hidden>{me.username[0]?.toUpperCase()}</span>}
            <span className={styles.avatarOverlay}><Camera size={18} aria-hidden /> Trocar avatar</span>
          </button>
          <input ref={avatarInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            event.currentTarget.value = '';
            if (file) void upload(file);
          }} />
          <Field label="Nome completo (privado)" required error={fields.full_name}><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Nome de usuário público" required hint="Aparece nas filas. Use 3 a 24 letras, números, _ ou . sem palavrões ou discriminação." error={fields.username}><input maxLength={24} value={f.username} onChange={(e) => { setF({ ...f, username: e.target.value }); setFields((current) => ({ ...current, username: '' })); }} /></Field>
          <div className={`row ${styles.actions}`}>
            <button className="btn primary" onClick={() => {
              const miss: Record<string, string> = {};
              if (!f.full_name.trim()) miss.full_name = 'Preencha este campo.';
              if (!f.username.trim()) miss.username = 'Preencha este campo.';
              if (Object.keys(miss).length) { setFields(miss); setMsg({ k: 'error', t: 'Preencha os campos obrigatórios.' }); return; }
              run(() => patch('/me', { full_name: f.full_name.trim(), username: f.username.trim() }), 'Perfil atualizado.');
            }}>Salvar</button>
            <button type="button" className="btn" onClick={() => setPasswordOpen(true)}>{passwordTitle}</button>
          </div>
          {!me.email_verified && <a className="link-purple small" href="/verificar-email">Confirmar e-mail da conta</a>}
        </section>
        <section className={`card stack ${styles.compact} ${styles.stats}`}>
          <h2>Estatísticas</h2>
          {stats.data && <dl className="kv"><dt>Horas jogadas</dt><dd>{(stats.data.minutes_played / 60).toFixed(1)} h</dd><dt>Sessões</dt><dd>{stats.data.sessions}</dd>
            <dt>Total gasto</dt><dd>{money(stats.data.total_spent_cents)}</dd><dt>Favoritos</dt><dd>{stats.data.favorites}</dd>
            <dt>Mais jogados</dt><dd>{stats.data.top_games.map((t) => `${t.title} (${t.minutes} min)`).join(', ') || '—'}</dd></dl>}
          <p className="small dim">Conta criada em {dateTime(me.created_at)}. Conquistas internas: em breve.</p>
        </section>
        <section className={`card stack ${styles.compact} ${styles.linked}`}>
          <h2>Contas vinculadas</h2>
          {links.data?.map((l) => (
            <div key={l.id} className="spread">
              {l.provider === 'google' ? (
                <span className={styles.googleAccount}>
                  <span className={styles.googleMark}><img src="/google.svg" alt="Google" width={18} height={18} /></span>
                  <span>{l.provider_email || l.display_name || 'Conta vinculada'}</span>
                </span>
              ) : (
                <span><b>{l.provider[0].toUpperCase() + l.provider.slice(1)}</b> · perfil público: <a className="link-purple" href={l.public_url || '#'} target="_blank" rel="noopener noreferrer">{l.display_name}</a></span>
              )}
              <button className="btn sm danger" onClick={() => run(async () => { await del(`/me/linked-accounts/${l.id}`); links.reload(); }, 'Desvinculado.')}>Remover</button>
            </div>
          ))}
          {!links.data?.some((l) => l.provider === 'google') && <GoogleButton intent="link" label="Vincular conta Google" />}
          <div className={`row ${styles.linkForm}`}>
            <select className="btn" value={profile.provider} onChange={(e) => setProfile({ ...profile, provider: e.target.value })} aria-label="Serviço">
              <option value="twitch">Twitch</option><option value="kick">Kick</option><option value="discord">Discord</option></select>
            <input className="btn" aria-label="URL do perfil público" placeholder="URL do perfil público" maxLength={500} value={profile.public_url} onChange={(e) => setProfile({ ...profile, public_url: e.target.value })} />
            <button className="btn" onClick={() => run(async () => { await post('/me/linked-accounts', profile); setProfile({ ...profile, public_url: '' }); links.reload(); }, 'Perfil público adicionado.')}>Adicionar</button>
          </div>
          <p className="small dim">Twitch, Kick e Discord: apenas link de perfil público (sem login nem senha desses serviços). Isso é diferente do canal oficial de transmissão dos consoles.</p>
        </section>
      </div>
      {passwordOpen && <Modal title={passwordTitle} onClose={() => setPasswordOpen(false)} allowEscape compact>
        <PasswordForm hasPassword={me.has_password} onChanged={refresh} className={styles.form} />
      </Modal>}
    </div>
  );
}
export default function Page() { return <RequireAuth><Suspense><Perfil /></Suspense></RequireAuth>; }
