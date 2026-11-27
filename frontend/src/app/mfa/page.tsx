'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { isStaff, useAuth } from '@/lib/auth';

function Mfa() {
  const router = useRouter();
  const next = useSearchParams().get('proximo') || '/admin';
  const { me, loading, refresh } = useAuth();
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (loading || isStaff(me)) return;
    router.replace(!me ? '/entrar' : me.email_verified ? '/' : '/verificar-email');
  }, [loading, me, router]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { await post('/auth/mfa/verify', { code }); await refresh(); router.push(next.startsWith('/') && !next.startsWith('//') && !next.includes('\\') ? next : '/'); }
    catch (err) { setError(err instanceof ApiError ? err.message : 'Erro.'); }
  }
  if (loading || !isStaff(me)) return null;
  return (
    <AuthCard title="Verificação em duas etapas" subtitle="Digite o código do seu aplicativo autenticador (ou um código de recuperação).">
      {error && <Alert kind="error">{error}</Alert>}
      <form className="stack" onSubmit={submit}>
        <Field label="Código"><input maxLength={20} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.trim())} /></Field>
        <button type="button" className="btn" onClick={async () => {
          try { setCode((await navigator.clipboard.readText()).trim().slice(0, 20)); setError(''); }
          catch { setError('Cole o código diretamente no campo.'); }
        }}>Colar código</button>
        <button className="btn primary block" disabled={code.length < 6}>Confirmar</button>
      </form>
    </AuthCard>
  );
}
export default function Page() { return <Suspense><Mfa /></Suspense>; }
