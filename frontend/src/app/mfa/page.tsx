'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';

function Mfa() {
  const router = useRouter();
  const next = useSearchParams().get('proximo') || '/admin';
  const { refresh } = useAuth();
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { await post('/auth/mfa/verify', { code }); await refresh(); router.push(next.startsWith('/') ? next : '/'); }
    catch (err) { setError(err instanceof ApiError ? err.message : 'Erro.'); }
  }
  return (
    <AuthCard title="Verificação em duas etapas" subtitle="Digite o código do seu aplicativo autenticador (ou um código de recuperação).">
      {error && <Alert kind="error">{error}</Alert>}
      <form className="stack" onSubmit={submit}>
        <Field label="Código"><input maxLength={20} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.trim())} /></Field>
        <button className="btn primary block" disabled={code.length < 6}>Confirmar</button>
      </form>
    </AuthCard>
  );
}
export default function Page() { return <Suspense><Mfa /></Suspense>; }
