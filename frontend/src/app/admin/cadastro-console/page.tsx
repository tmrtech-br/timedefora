'use client';

import { useState } from 'react';
import { Alert, Field, PageHeader } from '@/components/ui';
import { post, put } from '@/lib/api';
import { dateTime } from '@/lib/format';
import { useApi } from '@/lib/hooks';
import { ConsoleEditor, type AdminConsole } from '@/components/admin/Consoles';
import PsnAccounts from '@/components/admin/PsnAccounts';
import { DataTable, fromLocalInput, useAction } from '@/components/admin/common';

const EMPTY_CONSOLE = { code: '', name: '', platform_code: 'PS5' };
const EMPTY_WINDOW = { game_id: '', starts_at: '', ends_at: '' };
type Game = { id: string; title: string; platform_codes: string[] };
type Window = { id: string; game_title: string; starts_at: string; ends_at: string };
type Agent = { id: string; name: string; is_simulated: boolean };

export default function ConsoleOnboarding() {
  const [selected, setSelected] = useState('');
  const [draft, setDraft] = useState(EMPTY_CONSOLE);
  const [window, setWindow] = useState(EMPTY_WINDOW);
  const [psnRevision, setPsnRevision] = useState(0);
  const [now] = useState(() => new Date().toISOString());
  const list = useApi<AdminConsole[]>('/admin/consoles');
  const consoleData = useApi<AdminConsole>(selected ? `/admin/consoles/${selected}` : null);
  const games = useApi<Game[]>(selected ? '/admin/games' : null);
  const assignments = useApi<Window[]>(selected ? `/admin/assignments?console_id=${selected}&date_from=${now}` : null);
  const agents = useApi<Agent[]>('/admin/agents');
  const { busy, msg, run } = useAction();
  const current = consoleData.data?.id === selected ? consoleData.data : null;
  const error = list.error ?? consoleData.error ?? games.error ?? assignments.error;
  const refresh = () => { void consoleData.reload(); void list.reload(); };

  return (
    <div className="stack">
      <PageHeader title="Cadastro de console" subtitle="Configure, vincule jogos, teste e publique no mesmo painel." />
      {msg}
      {error && <Alert kind="error">{error.message}</Alert>}
      <section className="card stack"><h2>Rascunho do console</h2>
        <Field label="Retomar cadastro"><select value={selected} onChange={(event) => {
          setSelected(event.target.value);
          setWindow(EMPTY_WINDOW);
          assignments.setData(null);
        }}>
          <option value="">Novo cadastro</option>
          {list.data?.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name}</option>)}
        </select></Field>
        {!selected && <form className="stack" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const created = await post<AdminConsole>('/admin/consoles', draft);
            setSelected(created.id);
            setDraft(EMPTY_CONSOLE);
            await list.reload();
          }, 'Rascunho criado.');
        }}>
          <div className="grid3">
            <Field label="Código" required><input required value={draft.code} maxLength={30}
              onChange={(event) => setDraft({ ...draft, code: event.target.value.toUpperCase() })} /></Field>
            <Field label="Nome" required><input required value={draft.name} maxLength={60}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
            <Field label="Plataforma"><select value={draft.platform_code}
              onChange={(event) => setDraft({ ...draft, platform_code: event.target.value })}>
              {['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((platform) => <option key={platform}>{platform}</option>)}
            </select></Field>
          </div>
          <div><button className="btn primary" disabled={busy}>Criar rascunho</button></div>
        </form>}
      </section>
      {current && <>
        {current.owner_user_id && !current.is_published && <section className="card stack"><h2>Agente autorizado para o proprietário</h2>
          
          <Field label="Agente"><select disabled={busy} value={current.owner_onboarding_agent_id ?? ''} onChange={(event) => {
            const agent_id = event.target.value;
            if (!agent_id) return;
            void run(async () => {
              await put(`/admin/console-onboardings/${current.id}/owner-agent`, { agent_id });
              refresh();
            }, 'Agente autorizado.');
          }}>
            <option value="">Selecione</option>
            {agents.data?.filter((agent) => !agent.is_simulated).map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select></Field>
        </section>}
        {['PS4', 'PS5'].includes(current.platform_code) && <section className="card stack"><h2>Gerenciar contas PSN</h2>
          <PsnAccounts key={current.id} initialPlatform={current.platform_code} onAccountsChanged={() => setPsnRevision((value) => value + 1)} />
        </section>}
        <ConsoleEditor key={`${current.id}:${psnRevision}`} c={current} onChange={refresh} onboarding />
        <section className="card stack"><h2>Vínculos e calendário</h2>
          
          <form className="stack" onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await post('/admin/assignments', { console_id: current.id, game_id: window.game_id,
                starts_at: fromLocalInput(window.starts_at), ends_at: fromLocalInput(window.ends_at) });
              setWindow(EMPTY_WINDOW);
              await assignments.reload();
              refresh();
            }, 'Janela de jogo salva.');
          }}>
            <div className="grid3">
              <Field label="Jogo" required><select required value={window.game_id} onChange={(event) => setWindow({ ...window, game_id: event.target.value })}>
                <option value="">Selecione</option>
                {games.data?.filter((game) => game.platform_codes.includes(current.platform_code))
                  .map((game) => <option key={game.id} value={game.id}>{game.title}</option>)}
              </select></Field>
              <Field label="Início" required><input type="datetime-local" required value={window.starts_at}
                onChange={(event) => setWindow({ ...window, starts_at: event.target.value })} /></Field>
              <Field label="Fim" required><input type="datetime-local" required min={window.starts_at || undefined} value={window.ends_at}
                onChange={(event) => setWindow({ ...window, ends_at: event.target.value })} /></Field>
            </div>
            <div><button className="btn" disabled={busy}>Vincular jogo à janela</button></div>
          </form>
          <DataTable rows={assignments.data} error={assignments.error?.message} empty="Nenhum vínculo na agenda."
            cols={[[ 'Jogo', (item) => item.game_title ], ['Início', (item) => dateTime(item.starts_at)], ['Fim', (item) => dateTime(item.ends_at)]]} />
        </section>
        <section className="card stack"><h2>Publicação</h2>
          
          {current.is_published ? <p>Console publicado.</p> : <div>
            <button className="btn primary" disabled={busy} onClick={() => run(async () => {
              await post(`/admin/console-onboardings/${current.id}/publish`);
              refresh();
            }, 'Console publicado.')}>Publicar console</button>
          </div>}
        </section>
      </>}
    </div>
  );
}
