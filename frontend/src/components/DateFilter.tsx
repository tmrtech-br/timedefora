'use client';
import { useLayoutEffect, useRef, useState } from 'react';

const monthLabel = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' });
const weekdays = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export default function DateFilter({ label, value, onChange, min, max, isDateDisabled, disabled = false }: {
  label: string; value: string; onChange: (value: string) => void; min?: string; max?: string; isDateDisabled?: (date: string) => boolean; disabled?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const calendar = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => new Date());
  const year = month.getFullYear();
  const index = month.getMonth();
  const offset = new Date(year, index, 1).getDay();
  const last = new Date(year, index + 1, 0).getDate();
  useLayoutEffect(() => {
    const popup = calendar.current;
    const anchor = trigger.current;
    if (!open || disabled || !popup || !anchor) return;
    popup.showPopover();
    function position() {
      if (!popup || !anchor) return;
      const rect = anchor.getBoundingClientRect();
      const { clientWidth, clientHeight } = document.documentElement;
      const left = Math.max(8, Math.min(rect.left, clientWidth - popup.offsetWidth - 8));
      const below = rect.bottom + 6;
      const above = rect.top - popup.offsetHeight - 6;
      const preferredTop = below + popup.offsetHeight <= clientHeight - 8 ? below : above >= 8 ? above : below;
      popup.style.left = `${left}px`;
      popup.style.top = `${Math.max(8, Math.min(preferredTop, clientHeight - popup.offsetHeight - 8))}px`;
    }
    const close = (e: PointerEvent) => {
      if (!container.current?.contains(e.target as Node)) setOpen(false);
    };
    position();
    const observer = new ResizeObserver(position);
    observer.observe(popup);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    window.addEventListener('pointerdown', close);
    return () => {
      observer.disconnect();
      if (popup.matches(':popover-open')) popup.hidePopover();
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
      window.removeEventListener('pointerdown', close);
    };
  }, [open, disabled]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return <div className="field date-filter" ref={container} onKeyDown={(e) => {
    if (open && e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }}>
    <span>{label}</span>
    <button type="button" className="btn" ref={trigger} aria-label={label} aria-expanded={open && !disabled} disabled={disabled} onClick={() => {
      if (!open) setMonth(value || min ? new Date((value || min) + 'T12:00:00') : new Date());
      setOpen(!open);
    }}>{value ? value.split('-').reverse().join('/') : 'dd/mm/yyyy'}</button>
    {open && !disabled && <div className="card date-calendar" ref={calendar} popover="manual" role="group" aria-label={label}>
      <div className="spread">
        <button type="button" className="btn sm" aria-label="Mês anterior" onClick={() => setMonth(new Date(year, index - 1, 1))}>‹</button>
        <strong aria-live="polite">{monthLabel.format(month)}</strong>
        <button type="button" className="btn sm" aria-label="Próximo mês" onClick={() => setMonth(new Date(year, index + 1, 1))}>›</button>
      </div>
      <div className="date-days">
        {weekdays.map((day) => <small key={day}>{day}</small>)}
        {Array.from({ length: offset }, (_, i) => <span key={i} />)}
        {Array.from({ length: last }, (_, i) => {
          const day = i + 1;
          const iso = [year, String(index + 1).padStart(2, '0'), String(day).padStart(2, '0')].join('-');
          return <button key={iso} type="button" className={'btn sm' + (value === iso ? ' primary' : '')}
            disabled={Boolean((min && iso < min) || (max && iso > max) || isDateDisabled?.(iso))}
            aria-pressed={value === iso} onClick={() => { onChange(iso); close(); }}>{day}</button>;
        })}
      </div>
      <button type="button" className="btn sm" onClick={() => { onChange(''); close(); }}>Limpar data</button>
    </div>}
  </div>;
}
