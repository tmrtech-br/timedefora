'use client';

import DateFilter from '@/components/DateFilter';
import { Field } from '@/components/ui';

export const isLocalDateTime = (value: string) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value);

export default function DateTimeField({ label, value, min, error, required, onChange }: {
  label: string; value: string; min?: string; error?: string; required?: boolean; onChange: (value: string) => void;
}) {
  const [day = '', time = ''] = value.split('T');
  const [minDay, minTime] = min?.split('T') ?? [];
  return <div className="admin-datetime" role="group" aria-label={label}>
    <div className="admin-datetime-controls">
      <DateFilter label={label} value={day} min={minDay} onChange={(next) => onChange(next && time ? `${next}T${time}` : next ? `${next}T` : '')} />
      <Field label="Hora"><input type="time" aria-label={`Hora · ${label}`} required={required}
        disabled={!day} value={time} min={day === minDay ? minTime : undefined} onChange={(e) => onChange(`${day}T${e.target.value}`)} /></Field>
    </div>
    {error && <p className="small err" role="alert">{error}</p>}
  </div>;
}
