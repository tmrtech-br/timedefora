'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useId, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import GoogleButton from '@/components/GoogleButton';
import { PasswordConfirmation, PasswordField, PasswordRequirements, passwordMeetsRequirements } from '@/components/PasswordFields';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useFeatures } from '@/lib/features';
import styles from './register.module.css';
import settingsStyles from '../configuracoes/settings.module.css';

export default function Cadastro() {
  const router = useRouter();
  const { refresh } = useAuth();
  const features = useFeatures();
  const [f, setF] = useState({ full_name: '', username: '', email: '', password: '', password_confirm: '', accept_terms: false, accept_privacy: false, marketing_opt_in: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const requirementsId = useId();
  const confirmationId = useId();
  const meetsRequirements = passwordMeetsRequirements(f.password);
  const mismatch = Boolean(f.password_confirm) && f.password !== f.password_confirm;
  const set = (k: keyof typeof f, v: string | boolean) => setF((current) => ({ ...current, [k]: v }));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || features?.signup_enabled === false || !meetsRequirements) return;
    setError('');
    if (f.password !== f.password_confirm) return;
    setErrors({});
    if (!f.accept_terms || !f.accept_privacy) {
      setError('Aceite os termos de uso e a política de privacidade para continuar.');
      return;
    }
    setBusy(true);
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
      <form className={`stack ${styles.form}`} onSubmit={submit} noValidate>
        <Field label="Nome completo" required error={errors.full_name}><input autoComplete="name" value={f.full_name} onChange={(e) => set('full_name', e.target.value)} required /></Field>
        <Field label="Nome de usuário público" required error={errors.username} hint="3 a 24 caracteres: letras, números, _ ou ."><input maxLength={24} autoComplete="username" value={f.username} onChange={(e) => set('username', e.target.value)} required /></Field>
        <Field label="E-mail" required error={errors.email}><input maxLength={254} type="email" autoComplete="email" value={f.email} onChange={(e) => set('email', e.target.value)} required /></Field>
        <PasswordField label="Senha" value={f.password} onChange={(value) => set('password', value)}
          describedBy={requirementsId} error={errors.password} />
        <PasswordRequirements password={f.password} id={requirementsId} />
        <PasswordField label="Confirmar senha" value={f.password_confirm} onChange={(value) => set('password_confirm', value)}
          describedBy={confirmationId} invalid={mismatch} error={errors.password_confirm} />
        <PasswordConfirmation id={confirmationId} value={f.password_confirm} mismatch={mismatch} />
        <div className={styles.consents}>
          <label className={settingsStyles.switchRow}><span>Li e aceito os <Link className="link-purple" href="/termos" target="_blank">termos de uso</Link>.</span><input className={`switch ${settingsStyles.toggle}`} type="checkbox" role="switch" checked={f.accept_terms} onChange={(e) => set('accept_terms', e.target.checked)} /></label>
          <label className={settingsStyles.switchRow}><span>Li e aceito a <Link className="link-purple" href="/privacidade" target="_blank">política de privacidade</Link>.</span><input className={`switch ${settingsStyles.toggle}`} type="checkbox" role="switch" checked={f.accept_privacy} onChange={(e) => set('accept_privacy', e.target.checked)} /></label>
          <label className={settingsStyles.switchRow}><span>Quero receber novidades e promoções por e-mail (opcional).</span><input className={`switch ${settingsStyles.toggle}`} type="checkbox" role="switch" checked={f.marketing_opt_in} onChange={(e) => set('marketing_opt_in', e.target.checked)} /></label>
        </div>
        <button className="btn primary block" disabled={busy || !meetsRequirements || f.password !== f.password_confirm || features?.signup_enabled === false}>{busy ? 'Criando conta…' : 'Cadastrar'}</button>
      </form>
      {features?.signup_enabled !== false && <GoogleButton label="Cadastrar com Google" />}
      <p className="small muted" style={{ textAlign: 'center' }}>Já tem conta? <Link className="link-purple" href="/entrar">Entrar</Link></p>
    </AuthCard>
  );
}
