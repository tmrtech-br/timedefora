'use client';
import { Check, Circle, Eye, EyeOff } from 'lucide-react';
import { useId, useState } from 'react';
import styles from './password.module.css';

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

export function PasswordField({ label, value, onChange, describedBy, invalid, error }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  describedBy: string;
  invalid?: boolean;
  error?: string;
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const VisibilityIcon = visible ? EyeOff : Eye;

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className={styles.input}>
        <input id={id} type={visible ? 'text' : 'password'} autoComplete="new-password"
          autoCapitalize="none" spellCheck={false} value={value} required aria-describedby={[describedBy, error && id + '-error'].filter(Boolean).join(' ')}
          aria-invalid={Boolean(error) || invalid || undefined} onChange={(event) => onChange(event.target.value)} />
        <button type="button" className={styles.visibility} aria-controls={id}
          aria-label={`${visible ? 'Ocultar' : 'Mostrar'}: ${label.toLowerCase()}`}
          onClick={() => setVisible(!visible)}>
          <VisibilityIcon size={19} aria-hidden />
        </button>
      </div>
      {error && <span className="err" id={id + "-error"}>{error}</span>}
    </div>
  );
}

export function passwordMeetsRequirements(password: string) {
  return rules.every((rule) => rule.test(password));
}

export function PasswordRequirements({ password, id }: { password: string; id: string }) {
  const checks = rules.map((rule) => ({ label: rule.label, met: rule.test(password) }));
  const score = checks.filter((check) => check.met).length;
  const strength = password ? strengthLabels[score] : 'Aguardando senha';
  return (
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
      <ul className={styles.checks} id={id}>
        {checks.map(({ label, met }) => (
          <li key={label} data-met={met}>
            {met ? <Check size={15} aria-hidden /> : <Circle size={10} aria-hidden />}
            <span>{label}<span className="sr-only">{met ? ', atendido' : ', pendente'}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PasswordConfirmation({ id, value, mismatch }: { id: string; value: string; mismatch: boolean }) {
  return (
    <span className={styles.confirmation} id={id} aria-live="polite" data-mismatch={mismatch}>
      {value && (mismatch ? 'As senhas ainda não conferem.' : 'As senhas conferem.')}
    </span>
  );
}
