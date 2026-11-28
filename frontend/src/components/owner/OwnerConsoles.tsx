'use client';
import { useEffect, useState } from 'react';
import { Alert, Field, Modal, StatusPill } from '@/components/ui';
import { get, patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { DataTable, NewRecord, useAction, useDelete } from '@/components/admin/common';
import OwnerReviewPanel from '@/components/OwnerReviewPanel';
import { REVIEW_LABEL, type OwnerConsole } from './shared';
import OwnerConnection from './OwnerConnection';

const EMPTY = { code: '', name: '', platform_code: 'PS5', model: '', serial_number: '', location: '', description: '' };
type Agent = { id: string; name: string; location: string; status: string };

/** Valida o código do console enquanto o proprietário digita (formato e se já existe). */
function useCodeCheck(code: string) {
  const [state, setState] = useState<{ ok: boolean; message: string } | null>(null);
  useEffect(() => {
    if (!code) { setState(null); return; }
    let active = true;
    const t = setTimeout(() => {
      get<{ valid: boolean; available: boolean; message: string }>(`/owner/consoles/code-check?code=${encodeURIComponent(code)}`)
        .then((r) => { if (active) setState({ ok: r.valid && r.available, message: r.message }); }).catch(() => {});
    }, 350);
    return () => { active = false; clearTimeout(t); };
  }, [code]);
  return state;
}

export default function OwnerConsoles({ consoles, reload, selected, setSelected }: {
  consoles: OwnerConsole[] | null; reload: () => void; selected: string; setSelected: (id: string) => void;
}) {
  const agents = useApi<Agent[]>('/owner/agents').data ?? [];
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<OwnerConsole | null>(null);
  const [edit, setEdit] = useState({ name: '', platform_code: '', model: '', location: '', description: '' });
  const { run, msg, busy } = useAction();
  const deletion = useDelete();
  const check = useCodeCheck(form.code);
  const current = consoles?.find((c) => c.id === selected);
  const agentName = (id: string | null) => agents.find((a) => a.id === id)?.name ?? (id ? 'Agente da equipe' : '—');

  return <section className="stack" id="cadastro">
    {msg}{deletion.dialog}
    <div className="card stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Meus consoles</h2>
        <NewRecord title="Cadastrar console">{(close) => <form className="stack" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const c = await post<OwnerConsole>('/owner/consoles', { ...form, serial_number: form.serial_number || null });
            setForm(EMPTY); reload(); setSelected(c.id); close();
          }, 'Console cadastrado. Configure a conexão, a conta PSN, os jogos, o preço e os horários e envie para análise.');
        }}>
          <div className="grid2">
            <Field label="Código" hint={check?.ok ? `✓ ${check.message}` : 'Ex.: PS5-JOAO-01'} error={check && !check.ok ? check.message : undefined}>
              <input required maxLength={30} value={form.code} aria-invalid={check ? !check.ok : undefined}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, '') })} /></Field>
            <Field label="Nome"><input required minLength={2} maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Plataforma"><select value={form.platform_code} onChange={(e) => setForm({ ...form, platform_code: e.target.value })}>
              {['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Modelo"><input maxLength={120} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
            <Field label="Série / identificador"><input maxLength={120} value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} /></Field>
            <Field label="Localização"><input maxLength={120} value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></Field>
          </div>
          <Field label="Descrição / observações"><textarea maxLength={500} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <div><button className="btn primary" disabled={busy || !check?.ok}>Cadastrar console</button></div>
        </form>}</NewRecord></div>
      <DataTable rows={consoles} empty="Nenhum console cadastrado."
        cols={[['Console', (c) => <span><b>{c.name}</b><br /><small className="muted">{c.code} · {c.platform_code}</small></span>],
          ['Agente', (c) => (c.agent_id ? agentName(c.agent_id) : <span className="muted">Definido pela equipe na aprovação</span>)],
          ['Status do cadastro', (c) => <StatusPill status={c.review_status ?? 'draft'} map={REVIEW_LABEL} />],
          ['No ar', (c) => (c.is_published ? 'Sim' : 'Não')],
          ['', (c) => <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
            <button className={`btn sm${selected === c.id ? ' primary' : ''}`} onClick={() => setSelected(c.id)}>{selected === c.id ? 'Selecionado' : 'Selecionar'}</button>
            <button className="btn sm" onClick={() => { setEditing(c); setEdit({ name: c.name, platform_code: c.platform_code, model: c.model ?? '', location: c.location ?? '', description: c.description ?? '' }); }}>Editar</button>
            <button className="btn sm danger" onClick={() => deletion.remove(`/owner/consoles/${c.id}`, `Excluir o console ${c.name}?`,
              (request) => run(async () => { await request(); if (selected === c.id) setSelected(''); reload(); }, 'Console excluído.'),
              'O console sai do ar e do seu portal. Não é possível excluir com reservas futuras.')}>Excluir</button>
          </div>]]} />
    </div>
    {current && <OwnerConnection key={`conn-${current.id}-${current.platform_code}`} console={current} onSaved={reload} />}
    {current && <OwnerReviewPanel key={`review-${current.id}-${current.platform_code}`} consoleId={current.id} onChange={reload} />}
    {editing && <Modal title={`Editar ${editing.name}`} onClose={() => setEditing(null)}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void run(async () => {
          const { platform_code, ...metadata } = edit;
          await patch(`/owner/consoles/${editing.id}`, platform_code === editing.platform_code ? metadata : { ...metadata, platform_code });
          setEditing(null); reload();
        }, editing.approved_at ? 'Alterações salvas. Envie para análise para a equipe validar.' : 'Console atualizado.');
      }}>
        <Field label="Nome"><input required minLength={2} maxLength={60} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
        <Field label="Plataforma" hint={editing.is_published ? 'Tire o console do ar antes de trocar a plataforma.' : undefined}>
          <select value={edit.platform_code} disabled={editing.is_published || editing.review_status === 'submitted'} onChange={(e) => setEdit({ ...edit, platform_code: e.target.value })}>
            {!['PS4', 'PS5'].includes(editing.platform_code) && <option>{editing.platform_code}</option>}
            <option value="PS4">PlayStation 4 (PS4)</option>
            <option value="PS5">PlayStation 5 (PS5)</option>
          </select>
        </Field>
        {edit.platform_code !== editing.platform_code && <p className="small muted">A troca limpa a configuração de conexão e exige um novo diagnóstico. O aluguel pela internet via PSN está disponível para PS4.</p>}
        <Field label="Modelo"><input maxLength={120} value={edit.model} onChange={(e) => setEdit({ ...edit, model: e.target.value })} /></Field>
        <Field label="Localização"><input maxLength={120} value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></Field>
        <Field label="Descrição / observações"><textarea maxLength={500} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
        <div><button className="btn primary" disabled={busy}>Salvar</button></div>
      </form>
    </Modal>}
  </section>;
}
