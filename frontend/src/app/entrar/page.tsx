'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import GoogleButton from '@/components/GoogleButton';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';

const GOOGLE_ERR: Record<string, string> = {
  cadastro_desativado: 'Novos cadastros estão desativados no momento.',
  google_vincular: 'Já existe uma conta com este e-mail. Entre com sua senha e vincule o Google em Perfil > Contas vinculadas.',
  google_cancelado: 'Login com Google cancelado.', conta_suspensa: 'Conta suspensa. Fale com o suporte.',
  google_not_configured: 'Login com Google não configurado.', invalid_state: 'Sessão de login expirada. Tente novamente.',
};

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get('proximo') || '/';
  const { refresh } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(params.get('erro') ? GOOGLE_ERR[params.get('erro')!] || 'Não foi possível entrar com Google.' : '');
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const r = await post<{ mfa_required: boolean; email_verified: boolean }>('/auth/login', { email, password });
      await refresh();
      if (r.mfa_required) router.push(`/mfa?proximo=${encodeURIComponent(next)}`);
      else if (!r.email_verified) router.push('/verificar-email');
      else router.push(next.startsWith('/') ? next : '/');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erro ao entrar.');
    } finally { setBusy(false); }
  }
  return (
    <AuthCard title="Entrar no LocaPlay" subtitle="Acesse sua conta para reservar e jogar.">
      {error && <Alert kind="error">{error}</Alert>}
      <form className="stack" onSubmit={submit} noValidate>
        <Field label="E-mail"><input maxLength={254} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Senha"><input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <button className="btn primary block" disabled={busy || !email || !password}>{busy ? 'Entrando…' : 'Entrar'}</button>
      </form>
      <GoogleButton />
      <div className="spread small">
        <Link className="link-purple" href="/recuperar-senha">Esqueci minha senha</Link>
        <Link className="link-purple" href="/cadastrar">Criar conta</Link>
      </div>
    </AuthCard>
  );
}

export default function Page() { return <Suspense><LoginForm /></Suspense>; }
