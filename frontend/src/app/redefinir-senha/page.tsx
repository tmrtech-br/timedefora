'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';

function Reset() {
  const token = useSearchParams().get('token') || '';
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await post<{ message: string }>('/auth/password/reset', { token, password: pw, password_confirm: pw2 }); setMsg({ k: 'ok', t: r.message }); }
    catch (err) { setMsg({ k: 'error', t: err instanceof ApiError ? err.message : 'Erro.' }); }
  }
  if (!token) return <AuthCard title="Link inválido"><Alert kind="error">Abra o link enviado por e-mail.</Alert></AuthCard>;
  return (
    <AuthCard title="Criar nova senha">
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      {msg?.k === 'ok' ? <a className="btn primary block" href="/entrar">Entrar</a> : (
        <form className="stack" onSubmit={submit}>
          <Field label="Nova senha" hint="Mínimo 10 caracteres, com letras e números."><input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label="Confirmar nova senha"><input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
          <button className="btn primary block" disabled={!pw || pw !== pw2}>Salvar senha</button>
        </form>
      )}
    </AuthCard>
  );
}
export default function Page() { return <Suspense><Reset /></Suspense>; }
