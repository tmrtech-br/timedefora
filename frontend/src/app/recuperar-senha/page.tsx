'use client';
import { useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';

export default function Recuperar() {
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await post<{ message: string }>('/auth/password/forgot', { email }); setMsg({ k: 'ok', t: r.message }); }
    catch (err) { setMsg({ k: 'error', t: err instanceof ApiError ? err.message : 'Erro.' }); }
  }
  return (
    <AuthCard title="Recuperar senha" subtitle="Enviaremos um link válido por 30 minutos.">
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <form className="stack" onSubmit={submit}>
        <Field label="E-mail da conta"><input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <button className="btn primary block" disabled={!email}>Enviar instruções</button>
      </form>
    </AuthCard>
  );
}
