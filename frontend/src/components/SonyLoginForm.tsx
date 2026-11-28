'use client';

import { Field } from '@/components/ui';

export default function SonyLoginForm({ url, value, onChange, busy, onSubmit }: {
  url: string; value: string; onChange: (value: string) => void; busy: boolean; onSubmit: () => void;
}) {
  return <form className="card stack" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
    <div><a className="btn primary" href={url} target="_blank" rel="noopener noreferrer">Abrir login Sony</a></div>
    <Field label="URL completa de retorno da Sony">
      <textarea rows={3} maxLength={8192} required autoComplete="off" value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
    <button className="btn primary" disabled={busy || !value.trim()}>Concluir vínculo</button>
    <span className="small muted">Depois de entrar, copie o endereço da página de retorno e cole acima. O link de autenticação vale por 10 minutos.</span>
  </form>;
}
