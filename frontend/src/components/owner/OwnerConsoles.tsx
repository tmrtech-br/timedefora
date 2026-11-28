'use client';

import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { Modal, StatusPill } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { OwnerConsoleHistory } from '@/components/OwnerReviewPanel';
import { DataTable, useAction, useDelete } from '@/components/admin/common';
import OwnerRegistration, { RegistrationSummary } from './OwnerRegistration';
import { readRegistrationDrafts, type RegistrationDraft, type RegistrationDrafts } from './registrationDraft';
import type { OwnerConsole, PsnAccount } from './shared';

const LABELS = { published: 'Publicado', draft: 'Em rascunho', submitted: 'Aguardando aprovação', inactive: 'Inativo', rejected: 'Reprovado' };
function registrationStatus(console: OwnerConsole): keyof typeof LABELS {
  if (console.review_status === 'rejected') return 'rejected';
  if (console.review_status === 'submitted') return 'submitted';
  if (console.is_published) return 'published';
  return console.approved_at || console.status === 'disabled' ? 'inactive' : 'draft';
}

export default function OwnerConsoles({ consoles, accounts, reload, reloadAccounts, ownerId, onSupport }: {
  consoles: OwnerConsole[] | null; accounts: PsnAccount[] | null; reload: () => Promise<void>; reloadAccounts: () => Promise<void>;
  ownerId: string; onSupport: () => void;
}) {
  const storageKey = `lp-owner-registration:${ownerId}`;
  const [drafts, setDrafts] = useState<RegistrationDrafts>(() => readRegistrationDrafts(storageKey));
  const [open, setOpen] = useState<{ id: string; step?: number }>();
  const [view, setView] = useState<OwnerConsole>();
  const [reason, setReason] = useState<OwnerConsole>();
  const [discard, setDiscard] = useState<string>();
  const { run, msg } = useAction();
  const deletion = useDelete();
  useEffect(() => { setDrafts(readRegistrationDrafts(storageKey)); }, [storageKey]);

  function write(next: RegistrationDrafts) {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
      setDrafts(next);
      return true;
    } catch {
      toast('error', 'Não foi possível salvar o rascunho neste navegador.');
      return false;
    }
  }
  function save(id: string, draft: RegistrationDraft, migrateFrom?: string) {
    const next = { ...readRegistrationDrafts(storageKey), [id]: draft };
    if (migrateFrom && migrateFrom !== id) delete next[migrateFrom];
    return write(next);
  }
  function removeDraft(id: string) {
    const next = readRegistrationDrafts(storageKey);
    delete next[id];
    return write(next);
  }

  if (open) return <OwnerRegistration
    key={open.id} initial={consoles?.find((item) => item.id === open.id)} records={consoles} accounts={accounts}
    draft={drafts[open.id]} draftKey={open.id} startAt={open.step} reload={reload} reloadAccounts={reloadAccounts}
    onSave={save} onClose={() => { setOpen(undefined); void reload(); }} onSupport={onSupport} />;

  const localDrafts = Object.entries(drafts).filter(([key]) => key.startsWith('draft-'));
  return <section className="card stack owner-registration-grid" aria-labelledby="owner-registrations-title">
    <div className="spread">
      <h2 id="owner-registrations-title">Meus cadastros</h2>
      <button className="btn primary" onClick={() => setOpen({ id: `draft-${crypto.randomUUID()}` })}><Plus size={17} aria-hidden /> Novo cadastro</button>
    </div>
    {msg}{deletion.dialog}
    {localDrafts.map(([key, draft]) => {
      const unsaved = draft.fields.console as { name?: string; code?: string; platform_code?: string } | undefined;
      return <div className="spread owner-local-draft" key={key}>
      <div><strong>{unsaved?.name || 'Novo console'}</strong><div className="small muted">{[unsaved?.code, unsaved?.platform_code].filter(Boolean).join(' · ') || 'Rascunho neste navegador'}</div></div>
      <div className="row"><StatusPill status="draft" map={LABELS} />
        <button className="btn sm" onClick={() => setOpen({ id: key })}>Continuar cadastro</button>
        <button className="btn sm danger" onClick={() => setDiscard(key)}>Excluir</button></div>
    </div>; })}
    <DataTable rows={consoles} empty={localDrafts.length ? 'Nenhum outro console cadastrado.' : 'Nenhum console cadastrado.'} cols={[
      ['Console', (item) => <span><strong>{item.name}</strong><br /><small className="muted">{item.code}</small></span>],
      ['Plataforma', (item) => item.platform_code],
      ['Status', (item) => <StatusPill status={registrationStatus(item)} map={LABELS} />],
      ['Ações', (item) => <div className="row">
        <button className="btn sm" onClick={() => setView(item)}>Ver</button>
        {item.review_status !== 'submitted' && <button className="btn sm" onClick={() => setOpen({ id: item.id, step: 0 })}>Editar</button>}
        {registrationStatus(item) !== 'published' && <button className="btn sm" onClick={() => setOpen({ id: item.id })}>Continuar cadastro</button>}
        {item.review_status === 'rejected' && <button className="btn sm" onClick={() => setReason(item)}>Ver motivo</button>}
        <button className="btn sm danger" onClick={() => deletion.remove(`/owner/consoles/${item.id}`, `Excluir o console ${item.name}?`,
          (request) => run(async () => { await request(); removeDraft(item.id); await reload(); }, 'Console excluído.'),
          'O console sai do ar e do portal. A exclusão só é possível sem reservas futuras.')}>Excluir</button>
      </div>],
    ]} />
    {view && <Modal title={view.name} onClose={() => setView(undefined)} allowEscape>
      <div className="stack"><div><StatusPill status={registrationStatus(view)} map={LABELS} /></div>
        <RegistrationSummary console={view} accounts={accounts} />
        <OwnerConsoleHistory consoleId={view.id} />
        {view.is_published && <div><button className="btn" onClick={() => { setView(undefined); setOpen({ id: view.id, step: 6 }); }}>Ver testes e publicação</button></div>}
      </div>
    </Modal>}
    {reason && <Modal title="Motivo da reprovação" onClose={() => setReason(undefined)} allowEscape>
      <p style={{ whiteSpace: 'pre-wrap' }}>{reason.review_notes || 'A equipe não registrou observações.'}</p>
      <button className="btn primary" onClick={() => { setOpen({ id: reason.id, step: 0 }); setReason(undefined); }}>Corrigir cadastro</button>
    </Modal>}
    {discard && <Modal title="Excluir o rascunho?" onClose={() => setDiscard(undefined)} allowEscape>
      <p>Os dados preenchidos neste navegador serão apagados.</p>
      <button className="btn danger" onClick={() => { if (removeDraft(discard)) setDiscard(undefined); }}>Excluir rascunho</button>
    </Modal>}
  </section>;
}
