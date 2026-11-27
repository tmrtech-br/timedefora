'use client';
import DateFilter from '@/components/DateFilter';
import LimitedScroll from '@/components/LimitedScroll';
import DateTimeField, { isLocalDateTime } from './DateTimeField';
import { useMemo, useState } from 'react';
import { Alert, Field, Modal, PageHeader } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime, minutesLabel, time } from '@/lib/format';
import { DataTable, fromLocalInput, NewRecord, toLocalInput, useAction, useDelete } from './common';

type Ev = { id: string; console_id: string; starts_at: string; ends_at: string; title: string; kind: 'assignment' | 'reservation' | 'blackout'; status?: string; cancel_requested?: boolean };
type Cal = { consoles: { id: string; code: string; name: string; status: string; is_published: boolean }[]; events: Ev[] };
type A = { id: string; console_name: string; game_title: string; starts_at: string; ends_at: string; recurrence_group_id: string | null; notes: string };
type Dialog = { kind: 'end'; a: A; ends_at: string; reason: string } | { kind: 'cancel'; a: A; refund: boolean; reason: string };

const KIND_LABEL: Record<Ev['kind'], string> = { assignment: 'Jogo vinculado', reservation: 'Reserva', blackout: 'Manutenção/bloqueio' };
const RES_STATUS: Record<string, string> = { pending_payment: 'aguardando pagamento', confirmed: 'confirmada', active: 'em andamento', completed: 'concluída', no_show: 'ausência' };
const HOURS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24];
/** Distribui reservas em faixas para não sobrepor blocos de horários próximos. */
function laneOf(evs: Ev[]): Map<string, number> {
  const ends: number[] = [];
  const out = new Map<string, number>();
  [...evs].sort((a, b) => a.starts_at.localeCompare(b.starts_at)).forEach((e) => {
    const s = new Date(e.starts_at).getTime();
    let i = ends.findIndex((end) => end <= s);
    if (i < 0) { i = ends.length; ends.push(0); }
    ends[i] = new Date(e.ends_at).getTime() + 60000; // 1 min de folga visual
    out.set(e.id, i);
  });
  return out;
}
const mins = (a: string, b: string) => Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);

/** Valida no navegador antes de enviar (mensagens claras em vez do erro técnico da API). */
function checkWindow(v: { console_id?: string; game_id?: string; starts_at: string; ends_at: string }, need: ('console_id' | 'game_id')[]) {
  const e: Record<string, string> = {};
  if (need.includes('console_id') && !v.console_id) e.console_id = 'Selecione o console.';
  if (need.includes('game_id') && !v.game_id) e.game_id = 'Selecione o jogo.';
  if (!isLocalDateTime(v.starts_at)) e.starts_at = 'Informe a data e hora de início.';
  if (!isLocalDateTime(v.ends_at)) e.ends_at = 'Informe a data e hora de fim.';
  if (v.starts_at && v.ends_at && v.ends_at <= v.starts_at) e.ends_at = 'O fim deve ser depois do início.';
  return e;
}

export default function Agenda() {
  const games = useApi<{ id: string; title: string; platform_codes: string[] }[]>('/admin/games').data;
  const consoles = useApi<{ id: string; name: string; platform_code: string }[]>('/admin/consoles').data;
  const [day, setDay] = useState(() => new Date(Date.now() - 3 * 3600e3).toISOString().slice(0, 10));
  const from = new Date(day + 'T00:00:00-03:00'), to = new Date(from.getTime() + 864e5);
  const cal = useApi<Cal>(`/admin/calendar?date_from=${from.toISOString()}&date_to=${to.toISOString()}`, 15000);
  // Data fixada na montagem: gerar `new Date()` a cada render mudava a URL e disparava requisições em loop.
  const [assignsFrom] = useState(() => new Date().toISOString());
  const assigns = useApi<A[]>(`/admin/assignments?date_from=${assignsFrom}`);
  const blackouts = useApi<{ id: string; console_name: string; starts_at: string; ends_at: string; reason: string }[]>('/admin/blackouts');
  const [f, setF] = useState({ console_id: '', game_id: '', starts_at: '', ends_at: '', repeat: 'none', occurrences: 1, notes: '' });
  const [fErr, setFErr] = useState<Record<string, string>>({});
  const [b, setB] = useState({ console_id: '', starts_at: '', ends_at: '', reason: '' });
  const [bErr, setBErr] = useState<Record<string, string>>({});
  const [dlg, setDlg] = useState<Dialog | null>(null);
  const [dlgErr, setDlgErr] = useState('');
  const [listConsole, setListConsole] = useState('');
  const groups = useMemo(() => {
    const m = new Map<string, A[]>();
    for (const a of assigns.data || []) {
      if (listConsole && a.console_name !== listConsole) continue;
      const label = new Date(a.starts_at).toLocaleDateString('pt-BR', { timeZone: 'America/Fortaleza', weekday: 'long', day: '2-digit', month: '2-digit' });
      (m.get(label) || m.set(label, []).get(label)!).push(a);
    }
    for (const rows of m.values()) rows.sort((x, y) => x.console_name.localeCompare(y.console_name) || x.starts_at.localeCompare(y.starts_at));
    return Array.from(m.entries());
  }, [assigns.data, listConsole]);
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const refresh = () => { cal.reload(); assigns.reload(); blackouts.reload(); };
  const pct = (iso: string) => Math.min(100, Math.max(0, (new Date(iso).getTime() - from.getTime()) / 864e5 * 100));
  const nowPct = (Date.now() - from.getTime()) / 864e5 * 100;
  const consoleName = useMemo(() => Object.fromEntries((consoles || []).map((c) => [c.id, `${c.name} (${c.platform_code})`])), [consoles]);
  const consoleOptions = useMemo(() => consoles?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.platform_code})</option>), [consoles]);
  const selConsole = consoles?.find((c) => c.id === f.console_id);
  const gameOptions = (games || []).filter((g) => !selConsole || g.platform_codes.includes(selConsole.platform_code));

  function createAssignment(close: () => void) {
    const e = checkWindow(f, ['console_id', 'game_id']);
    setFErr(e);
    if (Object.keys(e).length) return;
    run(async () => { await post('/admin/assignments', { ...f, starts_at: fromLocalInput(f.starts_at), ends_at: fromLocalInput(f.ends_at) }); refresh(); setF({ ...f, starts_at: '', ends_at: '' }); close(); }, 'Vínculo criado.');
  }
  function createBlackout(refund: boolean, close: () => void) {
    const e = checkWindow(b, ['console_id']);
    if (!b.reason.trim()) e.reason = 'Informe o motivo.';
    setBErr(e);
    if (Object.keys(e).length) return;
    run(async () => { await post('/admin/blackouts', { ...b, starts_at: fromLocalInput(b.starts_at), ends_at: fromLocalInput(b.ends_at), ...(refund ? { resolution: 'cancel_and_refund' } : {}) }); refresh(); close(); },
      refund ? 'Bloqueio criado; reservas afetadas reembolsadas.' : 'Bloqueio criado.');
  }
  async function confirmDialog(refund: boolean) {
    if (!dlg) return;
    setDlgErr('');
    if (dlg.reason.trim().length < 5) { setDlgErr('Informe a justificativa com pelo menos 5 caracteres (fica registrada na auditoria).'); return; }
    if (dlg.kind === 'end') {
      if (!isLocalDateTime(dlg.ends_at)) { setDlgErr('Informe a nova data e hora de fim.'); return; }
      if (dlg.ends_at <= toLocalInput(dlg.a.starts_at)) { setDlgErr('O novo fim deve ser depois do início do vínculo.'); return; }
      const body = { ends_at: fromLocalInput(dlg.ends_at), reason: dlg.reason, ...(refund ? { resolution: 'cancel_and_refund' } : {}) };
      const ok = await run(async () => { await patch(`/admin/assignments/${dlg.a.id}`, body); refresh(); return true; }, refund ? 'Fim alterado; reservas afetadas reembolsadas.' : 'Fim do vínculo alterado.');
      if (ok) setDlg(null);
    } else {
      const body = { reason: dlg.reason, ...(dlg.refund ? { resolution: 'cancel_and_refund' } : {}) };
      const ok = await run(async () => { await post(`/admin/assignments/${dlg.a.id}/cancel`, body); refresh(); return true; }, dlg.refund ? 'Vínculo cancelado; reservas reembolsadas.' : 'Vínculo cancelado.');
      if (ok) setDlg(null);
    }
  }

  return (
    <div className="stack">
      <PageHeader title="Vínculos jogo × console e calendário" subtitle="Janelas por período, sem sobreposição. Horários em America/Fortaleza." />
      {msg}
      {deletion.dialog}
      <NewRecord title="Novo vínculo">{(close) => <>
        <div className="grid3">
          <Field label="Console" required error={fErr.console_id}><select value={f.console_id} onChange={(e) => setF({ ...f, console_id: e.target.value, game_id: '' })}><option value="">Selecione</option>{consoleOptions}</select></Field>
          <Field label="Jogo" required error={fErr.game_id} hint={selConsole ? `Somente jogos de ${selConsole.platform_code}` : undefined}>
            <select value={f.game_id} onChange={(e) => setF({ ...f, game_id: e.target.value })}><option value="">Selecione</option>{gameOptions.map((g) => <option key={g.id} value={g.id}>{g.title} ({g.platform_codes.join('/')})</option>)}</select></Field>
          <Field label="Recorrência"><select value={f.repeat} onChange={(e) => setF({ ...f, repeat: e.target.value })}><option value="none">Sem recorrência</option><option value="daily">Diária</option><option value="weekly">Semanal</option></select></Field>
          <DateTimeField label="Início" required error={fErr.starts_at} value={f.starts_at} onChange={(value) => setF({ ...f, starts_at: value })} />
          <DateTimeField label="Fim" required error={fErr.ends_at} value={f.ends_at} onChange={(value) => setF({ ...f, ends_at: value })} />
          {f.repeat !== 'none' && <Field label="Ocorrências" hint="1 a 60"><input type="number" min={1} max={60} value={f.occurrences} onChange={(e) => setF({ ...f, occurrences: Math.min(60, Math.max(1, Number(e.target.value) || 1)) })} /></Field>}
        </div>
        <div><button className="btn primary" disabled={busy} onClick={() => createAssignment(close)}>Vincular</button></div>
      </>}</NewRecord>

      <section className="card stack">
        <div className="spread"><h2 style={{ margin: 0 }}>Calendário do dia</h2>
          <div className="row agenda-day-picker"><button className="btn" onClick={() => setDay(new Date(from.getTime() - 864e5 + 3 * 3600e3).toISOString().slice(0, 10))} aria-label="Dia anterior">‹</button>
            <DateFilter label="Dia" value={day} onChange={(value) => { if (value) setDay(value); }} />
            <button className="btn" onClick={() => setDay(new Date(to.getTime() + 3 * 3600e3).toISOString().slice(0, 10))} aria-label="Próximo dia">›</button></div></div>
        <div className="cal2-legend">
          <span><i className="assignment" />Jogo vinculado (faixa de cima: qual jogo o console oferece)</span>
          <span><i className="reservation" />Reserva paga (faixas de baixo)</span>
          <span><i className="reservation pending" />Aguardando pagamento</span>
          <span><i className="reservation cancel-req" />Cancelamento solicitado</span>
          <span><i className="blackout" />Manutenção/bloqueio</span>
          {nowPct > 0 && nowPct < 100 && <span><i className="now" />Agora</span>}
          <span className="dim">Passe o mouse sobre um bloco para ver detalhes.</span>
        </div>
        <div className="cal2">
          <div className="cal2-row"><span /><div className="cal2-ruler">{HOURS.map((h) => <span key={h} style={{ left: `${h / 24 * 100}%` }}>{String(h).padStart(2, '0')}h</span>)}</div></div>
          <LimitedScroll label="Consoles no calendário do dia">
          {(cal.data?.consoles ?? []).map((c) => {
            const evs = cal.data!.events.filter((e) => e.console_id === c.id);
            const lanes = laneOf(evs.filter((e) => e.kind === 'reservation'));
            const nLanes = Math.max(1, ...Array.from(lanes.values()).map((x) => x + 1));
            return (
              <div key={c.id} className="cal2-row">
                <div className="cal2-name">{c.name}<small>{c.code}{!c.is_published ? ' · não publicado' : ''}</small></div>
                <div className="cal2-track" role="list" aria-label={`Agenda de ${c.name}`} style={{ height: 30 + nLanes * 24 }}>
                  {evs.map((e) => {
                    const left = pct(e.starts_at), width = Math.max(0.5, pct(e.ends_at) - left);
                    const range = `${time(e.starts_at)}–${time(e.ends_at)}`;
                    const tip = `${KIND_LABEL[e.kind]}: ${e.title} · ${range} (${minutesLabel(mins(e.starts_at, e.ends_at))})${e.status ? ' · ' + (RES_STATUS[e.status] || e.status) : ''}${e.cancel_requested ? ' · cancelamento solicitado' : ''}`;
                    const extra = e.kind === 'reservation' ? `${e.status === 'pending_payment' ? ' pending' : ''}${e.cancel_requested ? ' cancel-req' : ''}${['completed', 'no_show'].includes(e.status || '') ? ' past' : ''}` : '';
                    const top = e.kind === 'reservation' ? { top: 27 + (lanes.get(e.id) || 0) * 24 } : {};
                    return <span key={e.kind + e.id} role="listitem" className={`cal2-ev ${e.kind}${extra}`} style={{ left: `${left}%`, width: `${width}%`, ...top }} title={tip} aria-label={tip}>
                      {width > 7 ? `${e.title} · ${range}` : width > 3 ? e.title : ''}</span>;
                  })}
                  {nowPct > 0 && nowPct < 100 && <span className="cal2-now" style={{ left: `${nowPct}%` }} aria-hidden />}
                </div>
              </div>);
          })}
          </LimitedScroll>
          {cal.data && !cal.data.consoles.length && <div className="empty">Nenhum console cadastrado.</div>}
        </div>
      </section>

      <section className="card stack"><h2>Próximos vínculos</h2>
        <div className="spread">
          <select className="btn sm" value={listConsole} onChange={(e) => { setListConsole(e.target.value); }} aria-label="Filtrar por console">
            <option value="">Todos os consoles</option>{consoles?.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}</select></div>
        <DataTable limit={5} rows={assigns.data ? groups.flatMap(([day, rows]) => rows.map((row) => ({ ...row, day }))) : null}
          error={assigns.error?.message} empty="Nenhum vínculo futuro." cols={[
            ['Dia', (r) => r.day], ['Console', (r) => r.console_name], ['Jogo', (r) => r.game_title],
            ['Início', (r) => dateTime(r.starts_at)], ['Fim', (r) => dateTime(r.ends_at)],
            ['Duração', (r) => minutesLabel(mins(r.starts_at, r.ends_at))],
            ['Recorrência', (r) => r.recurrence_group_id ? 'recorrente' : 'única'],
            ['Ações', (r) => <div className="row">
              <button className="btn sm" onClick={() => { setDlgErr(''); setDlg({ kind: 'end', a: r, ends_at: toLocalInput(r.ends_at), reason: '' }); }}>Alterar fim</button>
              <button className="btn sm danger" onClick={() => { setDlgErr(''); setDlg({ kind: 'cancel', a: r, refund: false, reason: '' }); }}>Cancelar</button>
            </div>],
          ]} />
      </section>

      {dlg && (
        <Modal title={dlg.kind === 'end' ? 'Alterar fim do vínculo' : 'Cancelar vínculo'} onClose={() => setDlg(null)}>
          <div className="stack">
            <p className="small muted" style={{ margin: 0 }}><b>{dlg.a.game_title}</b> em <b>{dlg.a.console_name}</b><br />Atual: {dateTime(dlg.a.starts_at)} → {dateTime(dlg.a.ends_at)}</p>
            {dlg.kind === 'end'
              ? <DateTimeField label="Novo fim" required value={dlg.ends_at} min={toLocalInput(dlg.a.starts_at)} onChange={(ends_at) => setDlg({ ...dlg, ends_at })} />
              : <label className="check"><input type="checkbox" checked={dlg.refund} onChange={(e) => setDlg({ ...dlg, refund: e.target.checked })} />Cancelar e reembolsar as reservas afetadas</label>}
            <Field label="Justificativa (registrada na auditoria)" required><input maxLength={500} value={dlg.reason} onChange={(e) => setDlg({ ...dlg, reason: e.target.value })} /></Field>
            {dlg.kind === 'end' && <p className="small dim" style={{ margin: 0 }}>Reservas que deixarem de caber na nova janela: “Salvar” bloqueia a alteração e lista as reservas; “Salvar e reembolsar” cancela e reembolsa essas reservas.</p>}
            {dlgErr && <Alert kind="error">{dlgErr}</Alert>}
            <div className="row">
              {dlg.kind === 'end' ? <>
                <button className="btn primary" disabled={busy} onClick={() => confirmDialog(false)}>Salvar</button>
                <button className="btn danger" disabled={busy} onClick={() => confirmDialog(true)}>Salvar e reembolsar afetados</button>
              </> : <button className="btn danger" disabled={busy} onClick={() => confirmDialog(false)}>Confirmar cancelamento</button>}
              <button className="btn" onClick={() => setDlg(null)}>Voltar</button>
            </div>
          </div>
        </Modal>)}
    </div>
  );
}
