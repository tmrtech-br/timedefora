'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useId, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { PasswordConfirmation, PasswordField, PasswordRequirements, passwordMeetsRequirements } from '@/components/PasswordFields';

function Reset() {
  const token = useSearchParams().get('token') || '';
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const requirementsId = useId();
  const confirmationId = useId();
  const mismatch = Boolean(pw2) && pw !== pw2;
  const canSubmit = passwordMeetsRequirements(pw) && pw === pw2 && !saving;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setMsg(null);
    setSaving(true);
    try {
      const result = await post<{ message: string }>('/auth/password/reset', { token, password: pw, password_confirm: pw2 });
      setPw('');
      setPw2('');
      setMsg({ k: 'ok', t: result.message });
    }
    catch (err) { setMsg({ k: 'error', t: err instanceof ApiError ? err.message : 'Erro.' }); }
    finally { setSaving(false); }
  }
  if (!token) return <AuthCard title="Link inválido"><Alert kind="error">Abra o link enviado por e-mail.</Alert></AuthCard>;
  return (
    <AuthCard title="Criar nova senha">
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      {msg?.k === 'ok' ? <a className="btn primary block" href="/entrar">Entrar</a> : (
        <form className="stack" onSubmit={submit}>
          <PasswordField label="Nova senha" value={pw} onChange={setPw} describedBy={requirementsId} />
          <PasswordRequirements password={pw} id={requirementsId} />
          <PasswordField label="Confirmar nova senha" value={pw2} onChange={setPw2}
            describedBy={confirmationId} invalid={mismatch} />
          <PasswordConfirmation id={confirmationId} value={pw2} mismatch={mismatch} />
          <button className="btn primary block" disabled={!canSubmit}>{saving ? 'Salvando…' : 'Salvar senha'}</button>
        </form>
      )}
    </AuthCard>
  );
}
export default function Page() { return <Suspense><Reset /></Suspense>; }
