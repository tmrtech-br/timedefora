'use client';
import { useState } from 'react';
import LaunchScripts from '@/components/LaunchScripts';
import { ConsolePicker, type OwnerConsole } from './shared';

/** Menu Roteiros do proprietário: como o agente abre cada jogo vinculado ao console. */
export default function OwnerScripts({ consoles }: { consoles: OwnerConsole[] | null }) {
  const [selected, setSelected] = useState('');
  const id = selected || (consoles?.length === 1 ? consoles[0].id : '');
  return <section className="stack" id="roteiros">
    <div className="card stack">
      <ConsolePicker consoles={consoles} value={id} onChange={setSelected} />
      <p className="small muted" style={{ margin: 0 }}>Cada jogo vinculado precisa de um roteiro: são os botões que o sistema aperta para abrir o jogo
        quando um jogador aluga o console. Sem roteiro, o console não é liberado para o aluguel daquele jogo.</p>
    </div>
    {id && <LaunchScripts key={id} base={`/owner/consoles/${id}`} />}
  </section>;
}
