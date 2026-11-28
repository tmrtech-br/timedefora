'use client';
import { useState } from 'react';
import { Alert, Field } from '@/components/ui';
import { patch, post, put } from '@/lib/api';
import { dateTime, money } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { DataTable, fromLocalInput, NewRecord, useAction, useDelete } from '@/components/admin/common';
import { EMPTY_GAME, GameRegistrationFields, gameRegistrationBody } from '@/components/admin/Games';
import DateFilter from '@/components/DateFilter';
import { ConsolePicker, type OwnerConsole } from './shared';

/** Data (calendário padrão do sistema) + hora, no formato YYYY-MM-DDTHH:MM. */
function DateTimePick({ label, value, min, onChange }: { label: string; value: string; min?: string; onChange: (v: string) => void }) {
  const [date = '', time = ''] = value.split('T');
  return <div className="owner-datetime">
    <DateFilter label={label} value={date} min={min} onChange={(d) => onChange(`${d}T${time || '08:00'}`)} />
    <label className="field">Hora<input type="time" step={60} value={time} disabled={!date} onChange={(e) => onChange(`${date}T${e.target.value}`)} /></label>
  </div>;
}

type Games = { games: { id: string; title: string }[]; assignments: { id: string; title: string; starts_at: string; ends_at: string }[]; drafts: { id: string; title: string }[] };
type Rate = { min_minutes: number; max_minutes: number; rate_unit: 'minute' | 'hour'; rate_cents: number; paused?: boolean };
const DEFAULT_RATE: Rate = { min_minutes: 10, max_minutes: 120, rate_unit: 'minute', rate_cents: 100 };

function Price({ consoleId, value, locked, approved, onSaved }: { consoleId: string; value: Rate | null; locked: boolean; approved: boolean; onSaved: () => void }) {
  const [rate, setRate] = useState<Rate>(value ?? DEFAULT_RATE);
  const [reais, setReais] = useState(((value ?? DEFAULT_RATE).rate_cents / 100).toFixed(2).replace('.', ','));
  const [editing, setEditing] = useState(!value);
  const { busy, msg, run } = useAction();
  const deletion = useDelete();
  return <div className="stack">{msg}{deletion.dialog}
    {value && <div className="stack">
      <p style={{ margin: 0 }}><strong>{value.paused ? 'Aluguel pausado' : 'Preço em vigor'}</strong> · {money(value.rate_cents)} por {value.rate_unit === 'hour' ? 'hora' : 'minuto'} · sessões de {value.min_minutes} a {value.max_minutes} min</p>
      <div className="row">
        <button className="btn sm" disabled={busy || locked} onClick={() => setEditing(true)}>Alterar preço</button>
        <button className="btn sm" disabled={busy} onClick={() => run(async () => { await patch(`/owner/consoles/${consoleId}/availability`, { paused: !value.paused }); onSaved(); },
          value.paused ? 'Aluguel retomado.' : 'Aluguel pausado: novas reservas bloqueadas.')}>{value.paused ? 'Retomar aluguel' : 'Pausar aluguel'}</button>
        {!approved && <button className="btn sm danger" disabled={busy || locked} onClick={() => deletion.remove(`/owner/consoles/${consoleId}/availability`, 'Excluir o preço?',
          (request) => run(async () => { await request(); setEditing(true); onSaved(); }, 'Preço excluído.'))}>Excluir</button>}
      </div>
    </div>}
    {editing && <form className="stack" onSubmit={(e) => {
      e.preventDefault();
      const cents = Math.round(Number(reais.replace(',', '.')) * 100);
      void run(async () => {
        const r = await put<{ pending?: boolean }>(`/owner/consoles/${consoleId}/availability`, { ...rate, rate_cents: cents });
        setEditing(false); onSaved();
        return r;
      }, approved ? 'Novo preço enviado para a validação da equipe (o atual continua valendo até lá).' : 'Preço salvo.');
    }}>
      <div className="grid2">
        <Field label="Preço (R$)" hint="Valor que o jogador paga"><input required inputMode="decimal" maxLength={10} value={reais} onChange={(e) => setReais(e.target.value.replace(/[^\d,.]/g, ''))} /></Field>
        <Field label="Cobrança"><select value={rate.rate_unit} onChange={(e) => setRate({ ...rate, rate_unit: e.target.value === 'hour' ? 'hour' : 'minute' })}>
          <option value="minute">Por minuto</option><option value="hour">Por hora</option></select></Field>
        <Field label="Sessão mínima (min)"><input required type="number" min={1} max={480} value={rate.min_minutes} onChange={(e) => setRate({ ...rate, min_minutes: Number(e.target.value) })} /></Field>
        <Field label="Sessão máxima (min)"><input required type="number" min={rate.min_minutes} max={480} value={rate.max_minutes} onChange={(e) => setRate({ ...rate, max_minutes: Number(e.target.value) })} /></Field>
      </div>
      <div className="row"><button className="btn primary" disabled={busy || locked}>Salvar preço</button>
        {value && <button type="button" className="btn" onClick={() => setEditing(false)}>Cancelar</button>}</div>
    </form>}
  </div>;
}

/** Jogos e preços: cadastrar o jogo (para revisão), vincular aos períodos do console e definir o preço. */
export default function OwnerGames({ consoles, selected, setSelected }: { consoles: OwnerConsole[] | null; selected: string; setSelected: (id: string) => void }) {
  const current = consoles?.find((c) => c.id === selected);
  const games = useApi<Games>(current ? `/owner/consoles/${current.id}/games` : null);
  const rate = useApi<Rate | null>(current ? `/owner/consoles/${current.id}/availability` : null);
  const [gameDraft, setGameDraft] = useState<Record<string, unknown>>(EMPTY_GAME);
  const [win, setWin] = useState({ game_id: '', starts_at: '', ends_at: '' });
  const { busy, msg, run } = useAction();
  const deletion = useDelete();
  const locked = current?.review_status === 'submitted';
  const today = new Date(Date.now() - 3 * 3600000).toISOString().slice(0, 10);
  return <section className="stack" id="jogos">
    <div className="card"><ConsolePicker consoles={consoles} value={selected} onChange={setSelected} /></div>
    {msg}{deletion.dialog}{locked && <Alert kind="info">Console em análise: para editar, cancele o envio em Cadastro de console.</Alert>}
    {current && games.data && <div className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Jogos</h2>
        {!locked && <NewRecord title="Cadastrar jogo">{(close) => <form className="stack" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const g = await post<{ id: string }>(`/owner/consoles/${current.id}/game-drafts`, gameRegistrationBody(gameDraft));
            setGameDraft(EMPTY_GAME); await games.reload(); setWin((w) => ({ ...w, game_id: g.id })); close();
          }, 'Jogo cadastrado para revisão. Agora defina o período em que ele fica disponível.');
        }}>
          <p className="small muted" style={{ margin: 0 }}>Plataforma: {current.platform_code}. A equipe confere as artes e a licença antes de liberar a venda.</p>
          <GameRegistrationFields f={gameDraft} set={(key, value) => setGameDraft((f) => ({ ...f, [key]: value }))} owner />
          <div><button className="btn primary" disabled={busy || String(gameDraft.title).trim().length < 2}>Cadastrar jogo</button></div>
        </form>}</NewRecord>}</div>
      {!locked && <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void run(async () => {
          await post(`/owner/consoles/${current.id}/games`, { game_id: win.game_id, starts_at: fromLocalInput(win.starts_at), ends_at: fromLocalInput(win.ends_at) });
          setWin({ game_id: '', starts_at: '', ends_at: '' }); await games.reload();
        }, current.approved_at ? 'Período enviado para a validação da equipe.' : 'Período adicionado.');
      }}>
        <div className="grid3">
          <Field label="Jogo"><select required value={win.game_id} onChange={(e) => setWin({ ...win, game_id: e.target.value })}>
            <option value="">Selecione</option>
            {games.data.drafts.length > 0 && <optgroup label="Meus jogos (em revisão)">{games.data.drafts.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</optgroup>}
            <optgroup label="Catálogo">{games.data.games.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</optgroup>
          </select></Field>
          <DateTimePick label="Disponível de" value={win.starts_at} min={today} onChange={(v) => setWin({ ...win, starts_at: v })} />
          <DateTimePick label="Até" value={win.ends_at} min={win.starts_at.slice(0, 10) || today} onChange={(v) => setWin({ ...win, ends_at: v })} />
        </div>
        <div><button className="btn" disabled={busy || win.starts_at.length < 16 || win.ends_at.length < 16 || win.ends_at <= win.starts_at}>Adicionar período do jogo</button></div>
      </form>}
      <DataTable rows={games.data.assignments} empty="Nenhum período cadastrado."
        cols={[['Jogo', (a) => a.title], ['De', (a) => dateTime(a.starts_at)], ['Até', (a) => dateTime(a.ends_at)],
          ['', (a) => !locked && <button className="btn sm danger" onClick={() => deletion.remove(`/owner/consoles/${current.id}/games/${a.id}`, `Excluir o período de ${a.title}?`,
            (request) => run(async () => { await request(); await games.reload(); }, 'Período excluído.'), 'Não é possível excluir um período com reservas.')}>Excluir</button>]]} />
      {games.data.drafts.length > 0 && <><h3 style={{ margin: '6px 0 0' }}>Meus jogos em revisão</h3>
        <DataTable rows={games.data.drafts} cols={[['Jogo', (g) => g.title],
          ['', (g) => !locked && <button className="btn sm danger" onClick={() => deletion.remove(`/owner/consoles/${current.id}/game-drafts/${g.id}`, `Excluir o jogo ${g.title}?`,
            (request) => run(async () => { await request(); await games.reload(); }, 'Jogo excluído.'), 'Os períodos deste jogo também são removidos.')}>Excluir jogo</button>]]} /></>}
    </div>}
    {current && <div className="card stack"><h2 style={{ margin: 0 }}>Preço</h2>
      {!rate.loading && !rate.error && <Price key={current.id} consoleId={current.id} value={rate.data} locked={locked} approved={!!current.approved_at} onSaved={rate.reload} />}
    </div>}
  </section>;
}
