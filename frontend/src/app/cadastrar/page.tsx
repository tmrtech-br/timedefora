'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import AuthCard from '@/components/AuthCard';
import GoogleButton from '@/components/GoogleButton';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useFeatures } from '@/lib/features';

export default function Cadastro() {
  const router = useRouter();
  const { refresh } = useAuth();
  const features = useFeatures();
  const [f, setF] = useState({ full_name: '', username: '', email: '', password: '', password_confirm: '', accept_terms: false, accept_privacy: false, marketing_opt_in: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string | boolean) => setF({ ...f, [k]: v });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (f.password !== f.password_confirm) local.password_confirm = 'As senhas não conferem.';
    if (!f.accept_terms || !f.accept_privacy) local.accept_terms = 'Aceite os termos e a política de privacidade.';
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true); setError('');
    try {
      await post('/auth/register', f);
      await refresh();
      router.push('/verificar-email');
    } catch (err) {
      if (err instanceof ApiError) { setError(err.message); setErrors(err.fields); } else setError('Erro ao cadastrar.');
    } finally { setBusy(false); }
  }
  return (
    <AuthCard title="Criar conta" subtitle="Seu nome de usuário é o único dado exibido nas filas públicas.">
      {features?.signup_enabled === false && <Alert kind="warn">Novos cadastros estão desativados no momento. Tente novamente mais tarde.</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      <form className="stack" style={{ gap: 8 }} onSubmit={submit} noValidate>
        <Field label="Nome completo" required error={errors.full_name}><input autoComplete="name" value={f.full_name} onChange={(e) => set('full_name', e.target.value)} required /></Field>
        <Field label="Nome de usuário público" required error={errors.username} hint="3 a 24 caracteres: letras, números, _ ou ."><input maxLength={24} autoComplete="username" value={f.username} onChange={(e) => set('username', e.target.value)} required /></Field>
        <Field label="E-mail" required error={errors.email}><input maxLength={254} type="email" autoComplete="email" value={f.email} onChange={(e) => set('email', e.target.value)} required /></Field>
        <Field label="Senha" error={errors.password} hint="Mínimo 10 caracteres, com letras e números."><input type="password" autoComplete="new-password" value={f.password} onChange={(e) => set('password', e.target.value)} required /></Field>
        <Field label="Confirmar senha" error={errors.password_confirm}><input type="password" autoComplete="new-password" value={f.password_confirm} onChange={(e) => set('password_confirm', e.target.value)} required /></Field>
        <label className="check"><input type="checkbox" checked={f.accept_terms} onChange={(e) => set('accept_terms', e.target.checked)} /><span>Li e aceito os <Link className="link-purple" href="/termos" target="_blank">termos de uso</Link>.</span></label>
        <label className="check"><input type="checkbox" checked={f.accept_privacy} onChange={(e) => set('accept_privacy', e.target.checked)} /><span>Li e aceito a <Link className="link-purple" href="/privacidade" target="_blank">política de privacidade</Link>.</span></label>
        <label className="check"><input type="checkbox" checked={f.marketing_opt_in} onChange={(e) => set('marketing_opt_in', e.target.checked)} /><span>Quero receber novidades e promoções por e-mail (opcional).</span></label>
        {errors.accept_terms && <span className="field"><span className="err">{errors.accept_terms}</span></span>}
        <button className="btn primary block" disabled={busy || features?.signup_enabled === false}>{busy ? 'Criando conta…' : 'Cadastrar'}</button>
      </form>
      {features?.signup_enabled !== false && <GoogleButton label="Cadastrar com Google" />}
      <p className="small muted" style={{ textAlign: 'center' }}>Já tem conta? <Link className="link-purple" href="/entrar">Entrar</Link></p>
    </AuthCard>
  );
}
