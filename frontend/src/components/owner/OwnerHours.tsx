'use client';
import { useEffect, useState } from 'react';
import { Alert } from '@/components/ui';
import { put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { useAction } from '@/components/admin/common';
import { ConsolePicker, type OwnerConsole } from './shared';

type Hour = { weekday: number; opens_at: string; closes_at: string };
const DAYS = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado'];
type DayRow = { on: boolean; opens_at: string; closes_at: string };

/** Dias e horários da semana em que o console fica disponível para aluguel. */
export default function OwnerHours({ consoles, selected, setSelected }: { consoles: OwnerConsole[] | null; selected: string; setSelected: (id: string) => void }) {
  const current = consoles?.find((c) => c.id === selected);
  const data = useApi<{ hours: Hour[]; pending: Hour[] | null }>(current ? `/owner/consoles/${current.id}/hours` : null);
  const [rows, setRows] = useState<DayRow[]>(DAYS.map(() => ({ on: false, opens_at: '08:00', closes_at: '22:00' })));
  const { busy, msg, run } = useAction();
  useEffect(() => {
    const src = data.data?.pending ?? data.data?.hours;
    if (!src) return;
    setRows(DAYS.map((_, wd) => {
      const h = src.find((x) => x.weekday === wd);
      return h ? { on: true, opens_at: h.opens_at, closes_at: h.closes_at } : { on: false, opens_at: '08:00', closes_at: '22:00' };
    }));
  }, [data.data]);
  const set = (i: number, patch: Partial<DayRow>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const invalid = rows.some((r) => r.on && r.opens_at >= r.closes_at);
  const locked = current?.review_status === 'submitted';
  return <section className="stack" id="disponibilidade">
    <div className="card"><ConsolePicker consoles={consoles} value={selected} onChange={setSelected} /></div>
    {msg}
    {current && <div className="card stack">
      <h2 style={{ margin: 0 }}>Dias e horários disponíveis</h2>
      <p className="small muted" style={{ margin: 0 }}>O console só aceita reservas nesses horários (horário de Brasília), dentro dos períodos dos jogos.
        Sem nenhum dia marcado, vale o período inteiro de cada jogo.</p>
      {data.data?.pending && <Alert kind="info">Há horários novos aguardando a validação da equipe; os anteriores continuam valendo até lá.</Alert>}
      {locked && <Alert kind="info">Console em análise: cancele o envio em Cadastro de console para editar.</Alert>}
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
        <button className="btn primary" disabled={busy || invalid || locked} onClick={() => run(async () => {
          await put(`/owner/consoles/${current.id}/hours`, { hours: rows.flatMap((r, wd) => (r.on ? [{ weekday: wd, opens_at: r.opens_at, closes_at: r.closes_at }] : [])) });
          data.reload();
        }, current.approved_at ? 'Horários enviados para a validação da equipe.' : 'Horários salvos.')}>Salvar horários</button>
        <button className="btn" disabled={locked} onClick={() => setRows((r) => r.map((x, i) => ({ ...x, on: i >= 1 && i <= 5 })))}>Segunda a sexta</button>
        <button className="btn" disabled={locked} onClick={() => setRows((r) => r.map((x) => ({ ...x, on: true })))}>Todos os dias</button>
      </div>
    </div>}
  </section>;
}
