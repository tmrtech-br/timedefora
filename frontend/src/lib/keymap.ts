'use client';
import { useCallback, useEffect, useState } from 'react';
import { del, get, put } from './api';

/** Ações que o jogador pode ligar a teclas/botões do mouse (mesma lista de backend/app/routers/me.py → BINDABLE). */
export type Action =
  | 'cross' | 'circle' | 'square' | 'triangle' | 'l1' | 'r1' | 'l2' | 'r2' | 'l3' | 'r3' | 'options' | 'share'
  | 'dpad_up' | 'dpad_down' | 'dpad_left' | 'dpad_right'
  | 'ls_up' | 'ls_down' | 'ls_left' | 'ls_right' | 'rs_up' | 'rs_down' | 'rs_left' | 'rs_right';

export const ACTIONS: { id: Action; label: string; sym: string; group: string }[] = [
  { id: 'cross', label: 'Xis', sym: '✕', group: 'Botões' },
  { id: 'circle', label: 'Círculo', sym: '○', group: 'Botões' },
  { id: 'square', label: 'Quadrado', sym: '□', group: 'Botões' },
  { id: 'triangle', label: 'Triângulo', sym: '△', group: 'Botões' },
  { id: 'l1', label: 'L1', sym: 'L1', group: 'Gatilhos' }, { id: 'r1', label: 'R1', sym: 'R1', group: 'Gatilhos' },
  { id: 'l2', label: 'L2', sym: 'L2', group: 'Gatilhos' }, { id: 'r2', label: 'R2', sym: 'R2', group: 'Gatilhos' },
  { id: 'l3', label: 'L3', sym: 'L3', group: 'Gatilhos' }, { id: 'r3', label: 'R3', sym: 'R3', group: 'Gatilhos' },
  { id: 'options', label: 'Options', sym: '≡', group: 'Botões' }, { id: 'share', label: 'Share', sym: '⧉', group: 'Botões' },
  { id: 'dpad_up', label: 'Direcional cima', sym: '↑', group: 'Direcional' }, { id: 'dpad_down', label: 'Direcional baixo', sym: '↓', group: 'Direcional' },
  { id: 'dpad_left', label: 'Direcional esquerda', sym: '←', group: 'Direcional' }, { id: 'dpad_right', label: 'Direcional direita', sym: '→', group: 'Direcional' },
  { id: 'ls_up', label: 'Analógico esq. — frente', sym: 'LS↑', group: 'Analógico esquerdo (andar)' },
  { id: 'ls_down', label: 'Analógico esq. — trás', sym: 'LS↓', group: 'Analógico esquerdo (andar)' },
  { id: 'ls_left', label: 'Analógico esq. — esquerda', sym: 'LS←', group: 'Analógico esquerdo (andar)' },
  { id: 'ls_right', label: 'Analógico esq. — direita', sym: 'LS→', group: 'Analógico esquerdo (andar)' },
  { id: 'rs_up', label: 'Analógico dir. — cima', sym: 'RS↑', group: 'Analógico direito (câmera)' },
  { id: 'rs_down', label: 'Analógico dir. — baixo', sym: 'RS↓', group: 'Analógico direito (câmera)' },
  { id: 'rs_left', label: 'Analógico dir. — esquerda', sym: 'RS←', group: 'Analógico direito (câmera)' },
  { id: 'rs_right', label: 'Analógico dir. — direita', sym: 'RS→', group: 'Analógico direito (câmera)' },
];

/** Padrão do site. Valores = KeyboardEvent.code, ou Mouse0 (esq.), Mouse1 (meio), Mouse2 (dir.). */
export const DEFAULT_KEYS: Record<Action, string> = {
  cross: 'Space', circle: 'KeyE', square: 'KeyQ', triangle: 'KeyR', l1: 'ShiftLeft', r1: 'ControlLeft', l2: 'Mouse0', r2: 'Mouse2',
  l3: 'KeyC', r3: 'KeyV', options: 'Enter', share: 'Backspace',
  dpad_up: 'ArrowUp', dpad_down: 'ArrowDown', dpad_left: 'ArrowLeft', dpad_right: 'ArrowRight',
  ls_up: 'KeyW', ls_down: 'KeyS', ls_left: 'KeyA', ls_right: 'KeyD', rs_up: 'KeyI', rs_down: 'KeyK', rs_left: 'KeyJ', rs_right: 'KeyL',
};

export type Bindings = { keys: Record<Action, string>; mouse_look: boolean; mouse_sensitivity: number; custom: boolean };
export const DEFAULT_BINDINGS: Bindings = { keys: DEFAULT_KEYS, mouse_look: true, mouse_sensitivity: 1, custom: false };

const SPECIAL: Record<string, string> = {
  Space: 'Espaço', Enter: 'Enter', NumpadEnter: 'Enter', Escape: 'Esc', Backspace: 'Backspace', Tab: 'Tab', CapsLock: 'Caps Lock',
  ShiftLeft: 'Shift', ShiftRight: 'Shift dir.', ControlLeft: 'Ctrl', ControlRight: 'Ctrl dir.', AltLeft: 'Alt', AltRight: 'Alt Gr',
  MetaLeft: 'Win', MetaRight: 'Win', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Delete: 'Delete', Insert: 'Insert',
  Home: 'Home', End: 'End', PageUp: 'Page Up', PageDown: 'Page Down', Backquote: "'", Minus: '-', Equal: '=', BracketLeft: '´',
  BracketRight: '[', Semicolon: 'Ç', Quote: '~', Backslash: ']', Comma: ',', Period: '.', Slash: ';', IntlRo: '/',
  Mouse0: 'Botão esq. do mouse', Mouse1: 'Botão do meio', Mouse2: 'Botão dir. do mouse', Mouse3: 'Mouse voltar', Mouse4: 'Mouse avançar',
};

/** Rótulo amigável de um código de tecla ("KeyW" → "W", "ControlLeft" → "Ctrl", "Mouse0" → "Botão esq. do mouse"). */
export function codeLabel(code: string | undefined): string {
  if (!code) return '—';
  if (SPECIAL[code]) return SPECIAL[code];
  if (code.startsWith('Key')) return code.slice(3);
  if (code.startsWith('Digit')) return code.slice(5);
  if (code.startsWith('Numpad')) return 'Num ' + code.slice(6);
  return code;
}

/** Teclas que o navegador/sistema usa e não podem ser mapeadas (Esc sai da tela cheia; F5 recarrega etc.). */
export const RESERVED = new Set(['Escape', 'F1', 'F5', 'F11', 'F12', 'MetaLeft', 'MetaRight', 'Tab']);

/** Mapeamento do jogador (perfil) com fallback para o padrão. */
export function useBindings(enabled = true) {
  const [b, setB] = useState<Bindings>(DEFAULT_BINDINGS);
  const [loaded, setLoaded] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await get<{ keys: Partial<Record<Action, string>> | null; mouse_look: boolean; mouse_sensitivity: number }>('/me/input-bindings');
      setB({ keys: { ...DEFAULT_KEYS, ...(r.keys || {}) } as Record<Action, string>, mouse_look: r.mouse_look ?? true,
        mouse_sensitivity: r.mouse_sensitivity ?? 1, custom: !!r.keys });
    } catch { setB(DEFAULT_BINDINGS); }
    setLoaded(true);
  }, []);
  useEffect(() => { if (enabled) load(); else setLoaded(true); }, [enabled, load]);
  const save = async (next: Omit<Bindings, 'custom'>) => {
    await put('/me/input-bindings', { keys: next.keys, mouse_look: next.mouse_look, mouse_sensitivity: next.mouse_sensitivity });
    setB({ ...next, custom: true });
  };
  const reset = async () => { await del('/me/input-bindings'); setB(DEFAULT_BINDINGS); };
  return { bindings: b, loaded, save, reset, reload: load };
}

/** Índice reverso: código da tecla → ação. */
export function byCode(keys: Record<Action, string>): Record<string, Action> {
  return Object.fromEntries(Object.entries(keys).map(([a, c]) => [c, a as Action]));
}
