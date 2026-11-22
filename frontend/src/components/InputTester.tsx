'use client';
import { useEffect, useState } from 'react';

// Ordem do "standard mapping" da Gamepad API (índices 0–15).
const NAMES = ['cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'share', 'options', 'l3', 'r3', 'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right'];
export const GAMEPAD_BUTTONS = NAMES;

/** Símbolo e nome em português de cada botão do controle. */
const BUTTON_PT: Record<string, { sym: string; label: string }> = {
  cross: { sym: '✕', label: 'Xis' }, circle: { sym: '○', label: 'Círculo' }, square: { sym: '□', label: 'Quadrado' }, triangle: { sym: '△', label: 'Triângulo' },
  l1: { sym: 'L1', label: 'Gatilho sup. esq.' }, r1: { sym: 'R1', label: 'Gatilho sup. dir.' }, l2: { sym: 'L2', label: 'Gatilho esq.' }, r2: { sym: 'R2', label: 'Gatilho dir.' },
  share: { sym: '⧉', label: 'Compartilhar' }, options: { sym: '≡', label: 'Opções' }, l3: { sym: 'L3', label: 'Clique analóg. esq.' }, r3: { sym: 'R3', label: 'Clique analóg. dir.' },
  dpad_up: { sym: '↑', label: 'Direcional cima' }, dpad_down: { sym: '↓', label: 'Direcional baixo' }, dpad_left: { sym: '←', label: 'Direcional esq.' }, dpad_right: { sym: '→', label: 'Direcional dir.' },
};

/** Mapeamento padrão teclado/mouse → controle (exibido como teclas). */
const KEYMAP: [string[], string][] = [
  [['W', 'A', 'S', 'D'], 'Analógico esquerdo'], [['Mouse'], 'Analógico direito'], [['Espaço'], '✕ Xis'], [['E'], '○ Círculo'],
  [['Q'], '□ Quadrado'], [['R'], '△ Triângulo'], [['Shift'], 'L1'], [['Ctrl'], 'R1'], [['Botão esq.'], 'L2'], [['Botão dir.'], 'R2'],
  [['↑', '↓', '←', '→'], 'Direcional'], [['Enter'], 'Opções'],
];

const SPECIAL: Record<string, string> = {
  Space: 'Espaço', Enter: 'Enter', NumpadEnter: 'Enter', Escape: 'Esc', Backspace: 'Backspace', Tab: 'Tab', CapsLock: 'Caps Lock',
  ShiftLeft: 'Shift', ShiftRight: 'Shift', ControlLeft: 'Ctrl', ControlRight: 'Ctrl', AltLeft: 'Alt', AltRight: 'Alt Gr', MetaLeft: 'Win', MetaRight: 'Win',
  ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Delete: 'Delete', Insert: 'Insert', Home: 'Home', End: 'End', PageUp: 'Page Up', PageDown: 'Page Down',
};

/** Converte o código da tecla (ex.: "KeyW", "Digit1", "ShiftLeft") no rótulo da tecla ("W", "1", "Shift"). */
export function keyLabel(e: KeyboardEvent): string {
  const c = e.code;
  if (SPECIAL[c]) return SPECIAL[c];
  if (c.startsWith('Key')) return c.slice(3);
  if (c.startsWith('Digit')) return c.slice(5);
  if (c.startsWith('Numpad')) return 'Num ' + c.slice(6);
  if (/^F\d+$/.test(c)) return c;
  return e.key.length === 1 ? e.key.toUpperCase() : e.key;
}

const MOUSE = ['Botão esquerdo do mouse', 'Botão do meio do mouse', 'Botão direito do mouse'];

/** Teste de controle (Gamepad API) e de teclado/mouse. Não garante compatibilidade de todos os modelos. */
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
    const k = (e: KeyboardEvent) => setLastKey(keyLabel(e));
    const m = (e: MouseEvent) => setLastKey(MOUSE[e.button] || `Botão ${e.button + 1} do mouse`);
    window.addEventListener('keydown', k);
    window.addEventListener('mousedown', m);
    return () => { window.removeEventListener('keydown', k); window.removeEventListener('mousedown', m); };
  }, [mode]);
  if (mode === 'keyboard_mouse') {
    return (
      <div className="stack small">
        <p className="muted" style={{ margin: 0 }}>Mapeamento padrão (sensibilidade do mouse ajustável durante a sessão):</p>
        <div className="keymap">
          {KEYMAP.map(([keys, action]) => <div key={action}><span className="row" style={{ gap: 4 }}>{keys.map((k) => <kbd key={k}>{k}</kbd>)}</span><span>{action}</span></div>)}
        </div>
        <div className="keytest">Pressione uma tecla ou clique para testar: {lastKey ? <kbd aria-live="polite">{lastKey}</kbd> : <span className="dim">—</span>}</div>
        <p className="dim" style={{ margin: 0 }}>Jogos de console foram feitos para controle; alguns movimentos podem ficar menos precisos no teclado.</p>
      </div>
    );
  }
  return (
    <div className="stack small">
      {pads.length ? <p>Controle detectado: <b>{pads[0]}</b></p> : <p className="muted">Conecte o controle USB/Bluetooth e pressione qualquer botão para detectá-lo.</p>}
      <div className="gamepad-vis">{NAMES.map((n, i) => (
        <span key={n} className={pressed[i] ? 'on' : ''} title={BUTTON_PT[n].label}>
          <span className={`sym ${n}`} aria-hidden>{BUTTON_PT[n].sym}</span><span className="lbl">{BUTTON_PT[n].label}</span>
        </span>))}</div>
      {axes.length > 0 && <p>Analógico esquerdo: {axes[0]?.toFixed(2)} / {axes[1]?.toFixed(2)} · direito: {axes[2]?.toFixed(2)} / {axes[3]?.toFixed(2)}</p>}
      <p className="dim">Compatibilidade varia conforme modelo, sistema e navegador — especialmente no celular.</p>
    </div>
  );
}
