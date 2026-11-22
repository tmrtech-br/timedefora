'use client';
import { useMemo, useState } from 'react';
import { Field, PageHeader } from '@/components/ui';
import { del, patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime, time } from '@/lib/format';
import { DataTable, fromLocalInput, useAction } from './common';

type Cal = { consoles: { id: string; code: string; name: string }[]; events: { id: string; console_id: string; starts_at: string; ends_at: string; title: string; kind: string; status?: string }[] };
type A = { id: string; console_name: string; game_title: string; starts_at: string; ends_at: string; recurrence_group_id: string | null };

export default function Agenda() {
  const games = useApi<{ id: string; title: string; platform_codes: string[] }[]>('/admin/games').data;
  const consoles = useApi<{ id: string; name: string; platform_code: string }[]>('/admin/consoles').data;
  const [day, setDay] = useState(() => new Date(Date.now() - 3 * 3600e3).toISOString().slice(0, 10));
  const from = new Date(day + 'T00:00:00-03:00'), to = new Date(from.getTime() + 864e5);
  const cal = useApi<Cal>(`/admin/calendar?date_from=${from.toISOString()}&date_to=${to.toISOString()}`, 15000);
  const assigns = useApi<A[]>(`/admin/assignments?date_from=${new Date().toISOString()}`);
  const blackouts = useApi<{ id: string; console_name: string; starts_at: string; ends_at: string; reason: string }[]>('/admin/blackouts');
  const [f, setF] = useState({ console_id: '', game_id: '', starts_at: '', ends_at: '', repeat: 'none', occurrences: 1, notes: '' });
  const [b, setB] = useState({ console_id: '', starts_at: '', ends_at: '', reason: '' });
  const [edit, setEdit] = useState<{ id: string; ends_at: string; reason: string } | null>(null);
  const { run, msg, busy } = useAction();
  const refresh = () => { cal.reload(); assigns.reload(); blackouts.reload(); };
  const pct = (iso: string) => Math.min(100, Math.max(0, (new Date(iso).getTime() - from.getTime()) / 864e5 * 100));
  const consoleOptions = useMemo(() => consoles?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.platform_code})</option>), [consoles]);
  return (
    <div className="stack">
      <PageHeader title="Vínculos jogo × console e calendário" subtitle="Janelas por período, sem sobreposição. Horários em America/Fortaleza." />
      {msg}
      <section className="card stack"><h2>Novo vínculo</h2>
        <div className="grid3">
          <Field label="Console"><select value={f.console_id} onChange={(e) => setF({ ...f, console_id: e.target.value })}><option value="">Selecione</option>{consoleOptions}</select></Field>
          <Field label="Jogo"><select value={f.game_id} onChange={(e) => setF({ ...f, game_id: e.target.value })}><option value="">Selecione</option>{games?.map((g) => <option key={g.id} value={g.id}>{g.title} ({g.platform_codes.join('/')})</option>)}</select></Field>
          <Field label="Recorrência"><select value={f.repeat} onChange={(e) => setF({ ...f, repeat: e.target.value })}><option value="none">Sem recorrência</option><option value="daily">Diária</option><option value="weekly">Semanal</option></select></Field>
          <Field label="Início"><input type="datetime-local" value={f.starts_at} onChange={(e) => setF({ ...f, starts_at: e.target.value })} /></Field>
          <Field label="Fim"><input type="datetime-local" value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} /></Field>
          {f.repeat !== 'none' && <Field label="Ocorrências"><input type="number" min={1} max={60} value={f.occurrences} onChange={(e) => setF({ ...f, occurrences: Number(e.target.value) })} /></Field>}
        </div>
        <button className="btn primary" disabled={busy} onClick={() => run(async () => { await post('/admin/assignments', { ...f, starts_at: fromLocalInput(f.starts_at), ends_at: fromLocalInput(f.ends_at) }); refresh(); }, 'Vínculo criado.')}>Vincular</button>
      </section>
      <section className="card stack">
        <div className="spread"><h2 style={{ margin: 0 }}>Calendário do dia</h2><input className="btn" type="date" value={day} onChange={(e) => setDay(e.target.value)} /></div>
        <div className="row small"><span className="pill purple">jogo vinculado</span><span className="pill cyan">reserva</span><span className="pill red">manutenção/bloqueio</span><span className="dim">00h → 24h</span></div>
        <div className="cal">{cal.data?.consoles.map((c) => (
          <div key={c.id} className="cal-row"><b className="small">{c.name}</b><div className="cal-track">
            {cal.data!.events.filter((e) => e.console_id === c.id).map((e) => (
              <span key={e.kind + e.id} className={`cal-ev ${e.kind}`} style={{ left: `${pct(e.starts_at)}%`, width: `${Math.max(0.6, pct(e.ends_at) - pct(e.starts_at))}%` }}
                title={`${e.title} · ${time(e.starts_at)}–${time(e.ends_at)}${e.status ? ' · ' + e.status : ''}`}>{e.title}</span>))}
          </div></div>))}</div>
      </section>
      <section className="card"><h2>Próximos vínculos</h2>
        <DataTable rows={assigns.data as unknown as Record<string, unknown>[] | null} cols={[['Console', (r) => String(r.console_name)], ['Jogo', (r) => String(r.game_title)],
          ['Início', (r) => dateTime(String(r.starts_at))], ['Fim', (r) => dateTime(String(r.ends_at))], ['Recorrente', (r) => (r.recurrence_group_id ? 'sim' : 'não')],
          ['Ações', (r) => <div className="row">
            <button className="btn sm" onClick={() => setEdit({ id: String(r.id), ends_at: '', reason: '' })}>Alterar fim</button>
            <button className="btn sm danger" onClick={() => { const reason = prompt('Justificativa do cancelamento:') || ''; if (reason) run(async () => { await post(`/admin/assignments/${r.id}/cancel`, { reason }); refresh(); }, 'Vínculo cancelado.'); }}>Cancelar</button>
            <button className="btn sm danger" onClick={() => { const reason = prompt('Justificativa (reservas afetadas serão canceladas e reembolsadas):') || ''; if (reason) run(async () => { await post(`/admin/assignments/${r.id}/cancel`, { reason, resolution: 'cancel_and_refund' }); refresh(); }, 'Vínculo cancelado; reservas reembolsadas.'); }}>Cancelar + reembolsar</button></div>]]} />
        {edit && <div className="row" style={{ marginTop: 10 }}><input className="btn" type="datetime-local" value={edit.ends_at} onChange={(e) => setEdit({ ...edit, ends_at: e.target.value })} />
          <input className="btn" placeholder="Justificativa" value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} />
          <button className="btn primary" onClick={() => run(async () => { await patch(`/admin/assignments/${edit.id}`, { ends_at: fromLocalInput(edit.ends_at), reason: edit.reason }); setEdit(null); refresh(); }, 'Janela alterada.')}>Salvar</button>
          <button className="btn danger" onClick={() => run(async () => { await patch(`/admin/assignments/${edit.id}`, { ends_at: fromLocalInput(edit.ends_at), reason: edit.reason, resolution: 'cancel_and_refund' }); setEdit(null); refresh(); }, 'Janela alterada; reservas afetadas reembolsadas.')}>Salvar e reembolsar afetados</button></div>}
      </section>
      <section className="card stack"><h2>Manutenção / bloqueios</h2>
        <div className="grid3">
          <Field label="Console"><select value={b.console_id} onChange={(e) => setB({ ...b, console_id: e.target.value })}><option value="">Selecione</option>{consoleOptions}</select></Field>
          <Field label="Início"><input type="datetime-local" value={b.starts_at} onChange={(e) => setB({ ...b, starts_at: e.target.value })} /></Field>
          <Field label="Fim"><input type="datetime-local" value={b.ends_at} onChange={(e) => setB({ ...b, ends_at: e.target.value })} /></Field>
        </div>
        <Field label="Motivo"><input value={b.reason} onChange={(e) => setB({ ...b, reason: e.target.value })} /></Field>
        <div className="row"><button className="btn" onClick={() => run(async () => { await post('/admin/blackouts', { ...b, starts_at: fromLocalInput(b.starts_at), ends_at: fromLocalInput(b.ends_at) }); refresh(); }, 'Bloqueio criado.')}>Bloquear</button>
          <button className="btn danger" onClick={() => run(async () => { await post('/admin/blackouts', { ...b, starts_at: fromLocalInput(b.starts_at), ends_at: fromLocalInput(b.ends_at), resolution: 'cancel_and_refund' }); refresh(); }, 'Bloqueio criado; reservas afetadas reembolsadas.')}>Bloquear + reembolsar afetados</button></div>
        <DataTable rows={blackouts.data as unknown as Record<string, unknown>[] | null} cols={[['Console', (r) => String(r.console_name)], ['Período', (r) => `${dateTime(String(r.starts_at))} – ${dateTime(String(r.ends_at))}`],
          ['Motivo', (r) => String(r.reason)], ['', (r) => <button className="btn sm" onClick={() => run(async () => { await del(`/admin/blackouts/${r.id}`); refresh(); }, 'Bloqueio removido.')}>Remover</button>]]} />
      </section>
    </div>
  );
}
