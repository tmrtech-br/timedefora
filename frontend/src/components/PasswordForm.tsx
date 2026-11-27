'use client';

import { useState, type FormEvent } from 'react';
import { ApiError, post } from '@/lib/api';
import { Alert, Field } from './ui';

const EMPTY = { current_password: '', new_password: '', new_password_confirm: '' };
const MAX_LENGTH = 128;

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
    if (form.new_password.length < 10 || !/\p{L}/u.test(form.new_password) || !/\p{Nd}/u.test(form.new_password)) {
      issues.new_password = 'Use pelo menos 10 caracteres, com letras e números.';
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
      {hasPassword && <Field label="Senha atual" required error={errors.current_password}>
        <input type="password" autoComplete="current-password" maxLength={MAX_LENGTH} value={form.current_password} onChange={(event) => setField('current_password', event.target.value)} />
      </Field>}
      <Field label="Nova senha" required hint="Mínimo de 10 caracteres, com letras e números." error={errors.new_password}>
        <input type="password" autoComplete="new-password" maxLength={MAX_LENGTH} value={form.new_password} onChange={(event) => setField('new_password', event.target.value)} />
      </Field>
      <Field label="Confirmar nova senha" required error={errors.new_password_confirm}>
        <input type="password" autoComplete="new-password" maxLength={MAX_LENGTH} value={form.new_password_confirm} onChange={(event) => setField('new_password_confirm', event.target.value)} />
      </Field>
      <button className="btn primary" type="submit" disabled={saving}>{saving ? 'Salvando…' : hasPassword ? 'Alterar senha' : 'Definir senha'}</button>
    </form>
  );
}
