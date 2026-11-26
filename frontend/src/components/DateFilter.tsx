'use client';
import { useEffect, useRef, useState } from 'react';

const monthLabel = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' });
const weekdays = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export default function DateFilter({ label, value, onChange, min, max }: {
  label: string; value: string; onChange: (value: string) => void; min?: string; max?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => new Date());
  const year = month.getFullYear();
  const index = month.getMonth();
  const offset = new Date(year, index, 1).getDay();
  const last = new Date(year, index + 1, 0).getDate();
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!container.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('pointerdown', close);
    return () => window.removeEventListener('pointerdown', close);
  }, [open]);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return <div className="field date-filter" ref={container} onKeyDown={(e) => {
    if (open && e.key === 'Escape') close();
  }}>
    <span>{label}</span>
    <button type="button" className="btn" ref={trigger} aria-label={label} aria-expanded={open} onClick={() => {
      if (!open) setMonth(value ? new Date(value + 'T12:00:00') : new Date());
      setOpen(!open);
    }}>{value ? value.split('-').reverse().join('/') : 'dd/mm/aaaa'}</button>
    {open && <div className="card date-calendar" role="group" aria-label={label}>
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
            disabled={Boolean((min && iso < min) || (max && iso > max))}
            aria-pressed={value === iso} onClick={() => { onChange(iso); close(); }}>{day}</button>;
        })}
      </div>
      <button type="button" className="btn sm" onClick={() => { onChange(''); close(); }}>Limpar data</button>
    </div>}
  </div>;
}
