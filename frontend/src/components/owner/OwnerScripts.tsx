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
      <p className="small muted" style={{ margin: 0 }}>Cada jogo vinculado precisa ser <b>reconhecido</b> uma vez: o sistema aprende o código do jogo
        no seu console e, a cada aluguel, abre o jogo pelo menu e só libera o jogador depois que o console confirmar que é o jogo certo.
        Mantenha o perfil do console com o status <b>Online</b>.</p>
    </div>
    {id && <LaunchScripts key={id} base={`/owner/consoles/${id}`} />}
  </section>;
}
