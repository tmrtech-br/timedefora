'use client';
import { useEffect, useState } from 'react';

const NAMES = ['cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'share', 'options', 'l3', 'r3', 'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right'];
export const GAMEPAD_BUTTONS = NAMES;

/** Teste de controle (Gamepad API) e de teclado. Não garante compatibilidade de todos os modelos. */
export default function InputTester({ mode }: { mode: 'keyboard_mouse' | 'gamepad' }) {
  const [pads, setPads] = useState<string[]>([]);
  const [pressed, setPressed] = useState<boolean[]>([]);
  const [axes, setAxes] = useState<number[]>([]);
  const [lastKey, setLastKey] = useState('');
  useEffect(() => {
    if (mode !== 'gamepad') return;
    let raf = 0;
    const loop = () => {
      const list = (navigator.getGamepads?.() || []).filter(Boolean) as Gamepad[];
      setPads(list.map((g) => g.id));
      if (list[0]) { setPressed(list[0].buttons.map((b) => b.pressed)); setAxes(list[0].axes.map((a) => Math.round(a * 100) / 100)); }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [mode]);
  useEffect(() => {
    if (mode !== 'keyboard_mouse') return;
    const h = (e: KeyboardEvent) => setLastKey(e.code);
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [mode]);
  if (mode === 'keyboard_mouse') {
    return (
      <div className="stack small">
        <p className="muted">Mapeamento padrão: <b>WASD</b> analógico esquerdo · <b>mouse</b> analógico direito (sensibilidade ajustável) · <b>Espaço</b> ✕ · <b>E</b> ○ · <b>Q</b> □ · <b>R</b> △ · <b>Shift</b> L1 · <b>Ctrl</b> R1 · <b>Botões do mouse</b> L2/R2 · setas = direcional · <b>Enter</b> Options.</p>
        <p>Pressione uma tecla para testar: <b>{lastKey || '—'}</b></p>
        <p className="dim">Jogos de console foram feitos para controle; alguns movimentos podem ficar menos precisos no teclado.</p>
      </div>
    );
  }
  return (
    <div className="stack small">
      {pads.length ? <p>Controle detectado: <b>{pads[0]}</b></p> : <p className="muted">Conecte o controle USB/Bluetooth e pressione qualquer botão para detectá-lo.</p>}
      <div className="gamepad-vis">{NAMES.map((n, i) => <span key={n} className={pressed[i] ? 'on' : ''}>{n.replace('dpad_', '↕ ')}</span>)}</div>
      {axes.length > 0 && <p>Analógicos: {axes.map((a) => a.toFixed(2)).join(' · ')}</p>}
      <p className="dim">Compatibilidade varia conforme modelo, sistema e navegador — especialmente no celular.</p>
    </div>
  );
}
