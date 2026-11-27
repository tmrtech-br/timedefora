'use client';
import { ClipboardPaste } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert, Field } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import styles from './verification.module.css';

export default function Verificar() {
  const router = useRouter();
  const { me, loading, refresh } = useAuth();
  const [code, setCode] = useState('');
  const codeInput = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  const [cooldown, setCooldown] = useState(0);
  useEffect(() => { if (!loading && !me) router.replace('/entrar?proximo=/verificar-email'); }, [loading, me, router]);
  useEffect(() => { if (cooldown <= 0) return; const t = setTimeout(() => setCooldown(cooldown - 1), 1000); return () => clearTimeout(t); }, [cooldown]);
  if (me?.email_verified) return <AuthCard title="E-mail confirmado"><Alert kind="ok">Seu e-mail já está confirmado.</Alert><a className="btn primary block" href="/jogos">Ir para o catálogo</a></AuthCard>;
  async function verify(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post('/auth/verify-email', { code });
      await refresh();
      setMsg({ k: 'ok', t: 'E-mail confirmado! Agora você pode reservar e jogar.' });
      setTimeout(() => router.push('/jogos'), 1200);
    } catch (err) { setMsg({ k: 'error', t: err instanceof ApiError ? err.message : 'Erro.' }); }
  }
  async function resend() {
    try { await post('/auth/resend-code'); setMsg({ k: 'ok', t: 'Novo código enviado.' }); setCooldown(60); }
    catch (err) { const e = err as ApiError; setMsg({ k: 'error', t: e.message }); if (e.data?.retry_after) setCooldown(Number(e.data.retry_after)); }
  }
  async function pasteCode() {
    try {
      const copied = (await navigator.clipboard.readText()).trim();
      const pastedCode = copied.match(/\b\d{6}\b/)?.[0];
      if (!pastedCode) {
        setMsg({ k: 'error', t: 'Copie o código de 6 dígitos do e-mail e tente novamente.' });
        return;
      }
      setCode(pastedCode);
      setMsg(null);
    } catch {
      setMsg({ k: 'error', t: 'O navegador não permitiu ler a área de transferência. Cole o código diretamente no campo.' });
    } finally {
      codeInput.current?.focus();
    }
  }
  return (
    <AuthCard title="Confirme seu e-mail" subtitle={me ? `Enviamos um código de 6 dígitos para ${me.email}. Ele expira em 10 minutos.` : ''}>
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <form className="stack" onSubmit={verify}>
        <div className={styles.code}>
          <Field label="Código de verificação"><input ref={codeInput} inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="\d{6}" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} /></Field>
          <button type="button" className={`icon-btn ${styles.paste}`} aria-label="Colar código" title="Colar código" onClick={pasteCode}>
            <ClipboardPaste size={19} aria-hidden />
          </button>
        </div>
        <button className="btn primary block" disabled={code.length !== 6}>Confirmar</button>
      </form>
      <button className="btn block" onClick={resend} disabled={cooldown > 0}>{cooldown > 0 ? `Reenviar em ${cooldown}s` : 'Reenviar código'}</button>
      <p className="small dim">Recursos pagos ficam bloqueados até a confirmação.</p>
    </AuthCard>
  );
}
