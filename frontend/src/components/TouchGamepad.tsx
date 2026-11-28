'use client';
import { useRef } from 'react';
import type { InputCommand } from '@/lib/gamebridge';

/**
 * Controle na tela para celular/tablet (estilo dos jogos mobile): gatilhos em cima, direcional à esquerda, botões
 * de ação à direita, analógicos embaixo e Share/Options na barra. Multitoque: cada dedo controla um botão.
 * Os comandos são os mesmos do controle físico (validados no servidor; PS/Touchpad continuam bloqueados).
 */
type Send = (c: InputCommand) => void;

function Btn({ name, label, className, send }: { name: string; label: string; className: string; send: Send }) {
  const down = useRef(false);
  const press = (pressed: boolean) => {
    if (down.current === pressed) return;
    down.current = pressed;
    if (pressed && navigator.vibrate) navigator.vibrate(8);
    send({ type: 'button', name, pressed });
  };
  return (
    <button type="button" className={`tg-btn ${className}`} aria-label={label}
      onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); press(true); }}
      onPointerUp={() => press(false)} onPointerCancel={() => press(false)} onLostPointerCapture={() => press(false)}
      onContextMenu={(e) => e.preventDefault()}>
      {label}
    </button>
  );
}

function Stick({ side, send }: { side: 'left' | 'right'; send: Send }) {
  const base = useRef<HTMLDivElement>(null);
  const knob = useRef<HTMLDivElement>(null);
  const lastSent = useRef(0);
  const axes = side === 'left' ? (['left_x', 'left_y'] as const) : (['right_x', 'right_y'] as const);
  function move(clientX: number, clientY: number, force = false) {
    const el = base.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const radius = r.width / 2;
    let dx = (clientX - (r.left + radius)) / radius, dy = (clientY - (r.top + radius)) / radius;
    const len = Math.hypot(dx, dy);
    if (len > 1) { dx /= len; dy /= len; }
    if (knob.current) knob.current.style.transform = `translate(${dx * radius * 0.6}px, ${dy * radius * 0.6}px)`;
    const now = performance.now();
    if (!force && now - lastSent.current < 33) return;          // ~30 envios/s
    lastSent.current = now;
    send({ type: 'axis', name: axes[0], value: Math.round(dx * 100) / 100 });
    send({ type: 'axis', name: axes[1], value: Math.round(dy * 100) / 100 });
  }
  function release() {
    if (knob.current) knob.current.style.transform = '';
    send({ type: 'axis', name: axes[0], value: 0 });
    send({ type: 'axis', name: axes[1], value: 0 });
  }
  return (
    <div ref={base} className={`tg-stick tg-stick-${side}`} role="slider" aria-label={`Analógico ${side === 'left' ? 'esquerdo' : 'direito'}`}
      aria-valuenow={0} aria-valuemin={-1} aria-valuemax={1}
      onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); move(e.clientX, e.clientY, true); }}
      onPointerMove={(e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) move(e.clientX, e.clientY); }}
      onPointerUp={release} onPointerCancel={release}>
      <div ref={knob} className="tg-knob" />
    </div>
  );
}

export default function TouchGamepad({ send, shareOn }: { send: Send; shareOn: boolean }) {
  return (
    <div className="touch-gamepad" aria-label="Controle na tela">
      <div className="tg-shoulders tg-left"><Btn name="l2" label="L2" className="tg-trigger" send={send} /><Btn name="l1" label="L1" className="tg-trigger" send={send} /></div>
      <div className="tg-shoulders tg-right"><Btn name="r2" label="R2" className="tg-trigger" send={send} /><Btn name="r1" label="R1" className="tg-trigger" send={send} /></div>
      <div className="tg-dpad">
        <Btn name="dpad_up" label="▲" className="tg-up" send={send} />
        <Btn name="dpad_left" label="◀" className="tg-left-btn" send={send} />
        <Btn name="dpad_right" label="▶" className="tg-right-btn" send={send} />
        <Btn name="dpad_down" label="▼" className="tg-down" send={send} />
      </div>
      <div className="tg-face">
        <Btn name="triangle" label="△" className="tg-triangle" send={send} />
        <Btn name="square" label="□" className="tg-square" send={send} />
        <Btn name="circle" label="○" className="tg-circle" send={send} />
        <Btn name="cross" label="✕" className="tg-cross" send={send} />
      </div>
      <Stick side="left" send={send} />
      <Stick side="right" send={send} />
      <div className="tg-bar">
        {shareOn && <Btn name="share" label="SHARE" className="tg-small" send={send} />}
        <Btn name="l3" label="L3" className="tg-small" send={send} />
        <Btn name="r3" label="R3" className="tg-small" send={send} />
        <Btn name="options" label="OPTIONS" className="tg-small" send={send} />
      </div>
    </div>
  );
}
