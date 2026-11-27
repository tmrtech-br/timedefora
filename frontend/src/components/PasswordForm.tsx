'use client';

import { useId, useState, type FormEvent } from 'react';
import { ApiError, post } from '@/lib/api';
import { PasswordConfirmation, PasswordField, PasswordRequirements, passwordMeetsRequirements } from './PasswordFields';
import { Alert } from './ui';

const EMPTY = { current_password: '', new_password: '', new_password_confirm: '' };

export default function PasswordForm({ hasPassword, onChanged, className }: {
  hasPassword: boolean;
  onChanged?: () => Promise<unknown> | void;
  className?: string;
}) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'error'; message: string }>();
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);

  const requirementsId = useId();
  const confirmationId = useId();
  const meetsRequirements = passwordMeetsRequirements(form.new_password);
  const mismatch = Boolean(form.new_password_confirm) && form.new_password_confirm !== form.new_password;

  function setField(field: keyof typeof EMPTY, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: '' }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setFeedback(undefined);
    const issues: Record<string, string> = {};
    if (hasPassword && !form.current_password) issues.current_password = 'Informe a senha atual.';
    if (!meetsRequirements) {
      issues.new_password = 'Atenda aos requisitos da nova senha.';
    } else if (hasPassword && form.new_password === form.current_password) {
      issues.new_password = 'Escolha uma senha diferente da atual.';
    }
    if (!form.new_password_confirm) issues.new_password_confirm = 'Confirme a nova senha.';
    else if (form.new_password_confirm !== form.new_password) issues.new_password_confirm = 'As senhas não conferem.';
    setErrors(issues);
    if (Object.keys(issues).length) return;

    setSaving(true);
    try {
      const result = await post<{ message: string }>('/me/password', form);
      setForm(EMPTY);
      setVersion((current) => current + 1);
      setFeedback({ kind: 'ok', message: result.message });
      await onChanged?.();
    } catch (error) {
      if (error instanceof ApiError) {
        setErrors(error.code === 'wrong_password' ? { current_password: error.message } : error.fields);
        setFeedback({ kind: 'error', message: error.message });
      } else {
        setFeedback({ kind: 'error', message: 'Não foi possível alterar a senha.' });
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <form key={version} className={className} onSubmit={submit} noValidate>
      {feedback && <Alert kind={feedback.kind}>{feedback.message}</Alert>}
      {hasPassword && <PasswordField label="Senha atual" autoComplete="current-password" value={form.current_password}
        error={errors.current_password} onChange={(value) => setField('current_password', value)} />}
      <PasswordField label="Nova senha" value={form.new_password} describedBy={requirementsId}
        error={errors.new_password} onChange={(value) => setField('new_password', value)} />
      <PasswordRequirements password={form.new_password} id={requirementsId} />
      <PasswordField label="Confirmar nova senha" value={form.new_password_confirm} describedBy={confirmationId}
        invalid={mismatch} error={errors.new_password_confirm} onChange={(value) => setField('new_password_confirm', value)} />
      <PasswordConfirmation id={confirmationId} value={form.new_password_confirm} mismatch={mismatch} />
      <button className="btn primary" type="submit" disabled={saving || !meetsRequirements || form.new_password !== form.new_password_confirm}>
        {saving ? 'Salvando?' : hasPassword ? 'Alterar senha' : 'Definir senha'}
      </button>
    </form>
  );
}
