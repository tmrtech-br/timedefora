'use client';
import { useState } from 'react';
import LaunchScripts from '@/components/LaunchScripts';
import { Field, PageHeader } from '@/components/ui';
import { useApi } from '@/lib/hooks';

type ConsoleRow = { id: string; code: string; name: string; platform_code: string; owner_user_id: string | null };

/** Roteiros de abertura de qualquer console (equipe). O roteiro do painel tem prioridade sobre o config.json do agente. */
export default function AdminScripts() {
  const consoles = useApi<ConsoleRow[]>('/admin/consoles');
  const [id, setId] = useState('');
  return <div className="stack">
    <PageHeader title="Roteiros de abertura" subtitle="Botões e conferências de tela que o agente executa para abrir cada jogo." />
    <div className="card"><Field label="Console"><select value={id} onChange={(e) => setId(e.target.value)}>
      <option value="">Selecione o console</option>
      {(consoles.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name} · {c.platform_code}{c.owner_user_id ? ' · proprietário' : ''}</option>)}
    </select></Field></div>
    {id && <LaunchScripts key={id} base={`/admin/consoles/${id}`} />}
  </div>;
}
