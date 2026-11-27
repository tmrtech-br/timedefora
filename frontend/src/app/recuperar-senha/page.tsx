'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';

export default function Recuperar() {
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (msg?.k !== 'ok') return;
    const timer = window.setTimeout(() => setMsg(null), 8000);
    return () => window.clearTimeout(timer);
  }, [msg]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    setSending(true);
    try { const r = await post<{ message: string }>('/auth/password/forgot', { email }); setMsg({ k: 'ok', t: r.message }); }
    catch (err) { setMsg({ k: 'error', t: err instanceof ApiError ? err.message : 'Erro.' }); }
    finally { setSending(false); }
  }
  return (
    <AuthCard title="Recuperar senha" subtitle="Enviaremos um link válido por 30 minutos.">
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <form className="stack" onSubmit={submit}>
        <Field label="E-mail da conta"><input maxLength={254} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <button className="btn primary block" disabled={!email || sending}>{sending ? 'Enviando…' : 'Enviar instruções'}</button>
      </form>
      <Link className="btn block" href="/entrar">Voltar para entrar</Link>
    </AuthCard>
  );
}
