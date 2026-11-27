'use client';
import { Check, Circle, Eye, EyeOff } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { Suspense, useId, useState } from 'react';
import AuthCard from '@/components/AuthCard';
import { Alert } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import styles from './reset.module.css';

const rules = [
  { label: 'De 10 a 128 caracteres', test: (password: string) => {
    const length = Array.from(password).length;
    return length >= 10 && length <= 128;
  } },
  { label: 'Uma letra minúscula', test: (password: string) => /\p{Ll}/u.test(password) },
  { label: 'Uma letra maiúscula', test: (password: string) => /\p{Lu}/u.test(password) },
  { label: 'Um número', test: (password: string) => /\p{Nd}/u.test(password) },
  { label: 'Um caractere especial', test: (password: string) => /[\p{P}\p{S}]/u.test(password) },
];

const strengthLabels = ['Muito fraca', 'Muito fraca', 'Fraca', 'Regular', 'Boa', 'Forte'];

function PasswordField({ label, value, onChange, describedBy, invalid }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  describedBy: string;
  invalid?: boolean;
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const VisibilityIcon = visible ? EyeOff : Eye;

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className={styles.input}>
        <input id={id} type={visible ? 'text' : 'password'} autoComplete="new-password"
          autoCapitalize="none" spellCheck={false} value={value} required aria-describedby={describedBy}
          aria-invalid={invalid || undefined} onChange={(event) => onChange(event.target.value)} />
        <button type="button" className={styles.visibility} aria-controls={id}
          aria-label={`${visible ? 'Ocultar' : 'Mostrar'}: ${label.toLowerCase()}`}
          onClick={() => setVisible(!visible)}>
          <VisibilityIcon size={19} aria-hidden />
        </button>
      </div>
    </div>
  );
}

function Reset() {
  const token = useSearchParams().get('token') || '';
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [msg, setMsg] = useState<{ k: 'ok' | 'error'; t: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const requirementsId = useId();
  const confirmationId = useId();
  const checks = rules.map((rule) => ({ label: rule.label, met: rule.test(pw) }));
  const score = checks.filter((check) => check.met).length;
  const strength = pw ? strengthLabels[score] : 'Aguardando senha';
  const mismatch = Boolean(pw2) && pw !== pw2;
  const canSubmit = score === rules.length && pw === pw2 && !saving;

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
          <div className={styles.requirements} data-score={score}>
            <div className={styles.strength}>
              <span>Força da senha</span>
              <strong aria-live="polite">{strength}</strong>
            </div>
            <div className={styles.meter} role="meter" aria-label="Força da senha"
              aria-valuemin={0} aria-valuemax={rules.length} aria-valuenow={score} aria-valuetext={strength}>
              {checks.map(({ label }, index) => (
                <span key={label} data-filled={index < score} aria-hidden />
              ))}
            </div>
            <ul className={styles.checks} id={requirementsId}>
              {checks.map(({ label, met }) => (
                <li key={label} data-met={met}>
                  {met ? <Check size={15} aria-hidden /> : <Circle size={10} aria-hidden />}
                  <span>{label}<span className="sr-only">{met ? ', atendido' : ', pendente'}</span></span>
                </li>
              ))}
            </ul>
          </div>
          <PasswordField label="Confirmar nova senha" value={pw2} onChange={setPw2}
            describedBy={confirmationId} invalid={mismatch} />
          <span className={styles.confirmation} id={confirmationId} aria-live="polite" data-mismatch={mismatch}>
            {pw2 && (mismatch ? 'As senhas ainda não conferem.' : 'As senhas conferem.')}
          </span>
          <button className="btn primary block" disabled={!canSubmit}>{saving ? 'Salvando…' : 'Salvar senha'}</button>
        </form>
      )}
    </AuthCard>
  );
}
export default function Page() { return <Suspense><Reset /></Suspense>; }
