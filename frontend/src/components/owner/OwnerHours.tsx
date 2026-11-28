'use client';
import { useEffect, useState } from 'react';
import DateFilter from '@/components/DateFilter';
import { post, put } from '@/lib/api';
import { time } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { useAction } from '@/components/admin/common';
import type { GameWindow } from './OwnerGames';
import { useDraftValue } from './registrationDraft';
import { ConsolePicker, type OwnerConsole } from './shared';

type Hour = { weekday: number; opens_at: string; closes_at: string };
const DAYS = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado'];
type DayRow = { on: boolean; opens_at: string; closes_at: string };
const DAY_MS = 86400000;
const dayLabel = (timestamp: number) => new Date(timestamp - 10800000).toISOString().slice(0, 10);
const today = () => dayLabel(Date.now());

function AvailabilityCalendar({ consoleId, rows }: { consoleId: string; rows: DayRow[] }) {
  const [day, setDay] = useState(today);
  const games = useApi<{ assignments: GameWindow[] }>(`/owner/consoles/${consoleId}/games`);
  const start = Date.parse(day + 'T00:00:00-03:00');
  const end = start + DAY_MS;
  const pct = (instant: number) => Math.min(100, Math.max(0, (instant - start) / DAY_MS * 100));
  const hours = rows[new Date(day + 'T00:00:00Z').getUTCDay()];
  const blocks = (games.data?.assignments ?? []).filter((item) => Date.parse(item.starts_at) < end && Date.parse(item.ends_at) > start);

  return <div className="card stack">
    <div className="spread"><h2 style={{ margin: 0 }}>Calendário do dia</h2>
      <div className="row agenda-day-picker">
        <button className="btn" disabled={day <= today()} onClick={() => setDay(dayLabel(start - DAY_MS))} aria-label="Dia anterior">‹</button>
        <DateFilter label="Dia" value={day} min={today()} onChange={(value) => { if (value) setDay(value); }} />
        <button className="btn" onClick={() => setDay(dayLabel(end))} aria-label="Próximo dia">›</button>
      </div>
    </div>
    <div className="cal2-legend">
      <span><i className="reservation" />Horário selecionado</span>
      <span><i className="assignment" />Período ativo</span>
      <span><i className="assignment owner-calendar-pending" />Período em análise</span>
    </div>
    <div className="cal2 owner-calendar">
      <div className="cal2-row"><span /><div className="cal2-ruler">{Array.from({ length: 13 }, (_, i) =>
        <span key={i} style={{ left: `${i / 12 * 100}%` }}>{String(i * 2).padStart(2, '0')}h</span>)}</div></div>
      <div className="cal2-row"><div className="cal2-name">Disponibilidade</div>
        <div className="cal2-track">
          {hours.on && hours.opens_at < hours.closes_at ? <span className="cal2-ev reservation"
            style={{ left: `${pct(Date.parse(`${day}T${hours.opens_at}:00-03:00`))}%`,
              width: `${pct(Date.parse(`${day}T${hours.closes_at}:00-03:00`)) - pct(Date.parse(`${day}T${hours.opens_at}:00-03:00`))}%` }}>
            {hours.opens_at}–{hours.closes_at}
          </span> : <span className="owner-calendar-empty">{rows.some((row) => row.on) ? 'Sem horário selecionado para este dia' : 'Vale o período de cada jogo'}</span>}
        </div>
      </div>
      {blocks.map((item) => {
        const left = pct(Date.parse(item.starts_at));
        const width = Math.max(0.5, pct(Date.parse(item.ends_at)) - left);
        const title = item.title.replace(/ \(aguardando validação\)$/, '');
        const range = `${Date.parse(item.starts_at) < start ? '00:00' : time(item.starts_at)}–${Date.parse(item.ends_at) >= end ? '24:00' : time(item.ends_at)}`;
        return <div key={item.id} className="cal2-row">
          <div className="cal2-name">{title}<small>{range}</small></div>
          <div className="cal2-track"><span className={`cal2-ev assignment${item.status === 'pending_review' ? ' owner-calendar-pending' : ''}`}
            style={{ left: `${left}%`, width: `${width}%` }} title={`${title} · ${range}`}>{title} · {range}</span></div>
        </div>;
      })}
    </div>
    {games.error && <p className="small err">{games.error.message}</p>}
    {games.data && !blocks.length && <p className="small muted" style={{ margin: 0 }}>Nenhum período de jogo neste dia.</p>}
  </div>;
}

/** Dias e horários da semana em que o console fica disponível para aluguel. */
export default function OwnerHours({ consoles, selected, setSelected, onReviewChange, wizard = false, onAdvance }: {
  consoles: OwnerConsole[] | null; selected: string; setSelected: (id: string) => void; onReviewChange: () => void; wizard?: boolean; onAdvance?: () => void;
}) {
  const current = consoles?.find((c) => c.id === selected);
  const data = useApi<{ hours: Hour[]; pending: Hour[] | null }>(current ? `/owner/consoles/${current.id}/hours` : null);
  const [rows, setRows, cached] = useDraftValue<DayRow[]>('hours', DAYS.map(() => ({ on: false, opens_at: '08:00', closes_at: '22:00' })));
  const { busy, msg, run } = useAction();
  useEffect(() => {
    const src = data.data?.pending ?? data.data?.hours;
    if (!src || cached) return;
    setRows(DAYS.map((_, wd) => {
      const h = src.find((x) => x.weekday === wd);
      return h ? { on: true, opens_at: h.opens_at, closes_at: h.closes_at } : { on: false, opens_at: '08:00', closes_at: '22:00' };
    }));
  }, [data.data, cached]);
  const set = (i: number, patch: Partial<DayRow>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const invalid = rows.some((r) => r.on && r.opens_at >= r.closes_at);
  const locked = current?.review_status === 'submitted';
  return <section className="stack" id="disponibilidade">
    {!wizard && <div className="card"><ConsolePicker consoles={consoles} value={selected} onChange={setSelected} /></div>}
    {msg}
    {current && <AvailabilityCalendar consoleId={current.id} rows={rows} />}
    {current && <div className="card stack">
      <h2 style={{ margin: 0 }}>Dias e horários disponíveis</h2>
      <p className="small muted" style={{ margin: 0 }}>O console só aceita reservas nesses horários (horário de Brasília), dentro dos períodos dos jogos.
        Sem nenhum dia marcado, vale o período inteiro de cada jogo.</p>
      {data.data?.pending && <p className="small muted">{locked ? 'Os novos horários foram enviados para análise.' : 'Há horários salvos para enviar à análise.'} Os horários em vigor valem até a aprovação.</p>}
      {locked && <p className="small muted">Para editar, cancele o envio em Cadastro de console.</p>}
      <div className="owner-hours">
        {rows.map((r, i) => <div key={DAYS[i]} className={`owner-hour${r.on ? ' on' : ''}`}>
          <label className="check"><input type="checkbox" checked={r.on} disabled={locked} onChange={(e) => set(i, { on: e.target.checked })} />{DAYS[i]}</label>
          <input type="time" step={60} value={r.opens_at} disabled={!r.on || locked} aria-label={`${DAYS[i]}: abre às`} onChange={(e) => set(i, { opens_at: e.target.value })} />
          <span className="small muted">até</span>
          <input type="time" step={60} value={r.closes_at} disabled={!r.on || locked} aria-label={`${DAYS[i]}: fecha às`} onChange={(e) => set(i, { closes_at: e.target.value })} />
          {r.on && r.opens_at >= r.closes_at && <span className="small" style={{ color: '#ff8f9a' }}>Abertura antes do fechamento</span>}
        </div>)}
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy || invalid || locked || data.loading} onClick={() => run(async () => {
          const result = await put<{ pending: boolean }>(`/owner/consoles/${current.id}/hours`, { hours: rows.flatMap((r, wd) => (r.on ? [{ weekday: wd, opens_at: r.opens_at, closes_at: r.closes_at }] : [])) });
          try {
            if (result.pending && !wizard) await post(`/owner/consoles/${current.id}/submit`);
            onAdvance?.();
          } finally {
            data.reload();
            onReviewChange();
          }
        }, current.approved_at && !wizard ? 'Novos horários enviados para análise.' : 'Horários salvos.')}>{wizard ? 'Salvar e continuar' : current.approved_at ? 'Salvar e enviar para análise' : 'Salvar horários'}</button>
        <button className="btn" disabled={locked} onClick={() => setRows((r) => r.map((x, i) => ({ ...x, on: i >= 1 && i <= 5 })))}>Segunda a sexta</button>
        <button className="btn" disabled={locked} onClick={() => setRows((r) => r.map((x) => ({ ...x, on: true })))}>Todos os dias</button>
      </div>
    </div>}
  </section>;
}
