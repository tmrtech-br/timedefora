'use client';

import { useEffect, useState } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Alert } from '@/components/ui';
import { get, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';

type Terms = { id: string; version: string; body: string; accepted_at: string | null };
type Console = { id: string; name: string; is_published: boolean };
type Account = { id: string; label: string; online_id: string | null };

function OwnerPortal() {
  const { me } = useAuth();
  const isOwner = me?.roles.includes('owner') === true;
  const [terms, setTerms] = useState<Terms>();
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [inventory, setInventory] = useState<{ consoles: Console[]; accounts: Account[] }>();

  useEffect(() => {
    if (!isOwner) return;
    let active = true;
    get<Terms>('/owner/terms').then((value) => {
      if (active) setTerms(value);
    }).catch((cause: Error) => {
      if (active) setError(cause.message);
    });
    return () => { active = false; };
  }, [isOwner]);

  useEffect(() => {
    if (!terms?.accepted_at) return;
    let active = true;
    Promise.all([get<Console[]>('/owner/consoles'), get<Account[]>('/owner/psn-accounts')])
      .then(([consoles, accounts]) => {
        if (active) setInventory({ consoles, accounts });
      }).catch((cause: Error) => {
        if (active) setError(cause.message);
      });
    return () => { active = false; };
  }, [terms]);

  async function accept() {
    if (!terms || !accepted || busy) return;
    setBusy(true);
    setError('');
    try {
      await post('/owner/enrollment', { policy_version_id: terms.id, accepted: true });
      setTerms(await get<Terms>('/owner/terms'));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Erro ao registrar o aceite.');
    } finally {
      setBusy(false);
    }
  }

  if (!isOwner) return <Alert kind="error">Disponível para contas de proprietário.</Alert>;
  return (
    <section aria-labelledby="owner-title">
      <h1 id="owner-title">Portal do proprietário</h1>
      {error && <Alert kind="error">{error}</Alert>}
      {!terms && !error && <p role="status">Carregando termos…</p>}
      {terms && !terms.accepted_at && (
        <form className="card" onSubmit={(event) => { event.preventDefault(); void accept(); }}>
          <h2>Termos do proprietário</h2>
          <p>Versão {terms.version}</p>
          <p style={{ whiteSpace: 'pre-line' }}>{terms.body.trim()}</p>
          <p><label><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /> Li e aceito os termos do proprietário.</label></p>
          <button type="submit" className="btn" disabled={!accepted || busy}>{busy ? 'Salvando…' : 'Confirmar aceite'}</button>
        </form>
      )}
      {terms?.accepted_at && !inventory && !error && <p role="status">Carregando inventário…</p>}
      {inventory && (
        <div className="admin-grid">
          <nav className="admin-nav" aria-label="Inventário do proprietário">
            <a href="#contas-psn">Contas PSN</a>
            <a href="#consoles">Consoles</a>
          </nav>
          <div>
            <section className="card" id="contas-psn">
              <h2>Contas PSN</h2>
              {inventory.accounts.length ? <ul>{inventory.accounts.map((account) => <li key={account.id}>{account.label}{account.online_id && ` · ${account.online_id}`}</li>)}</ul> : <p>Nenhuma conta vinculada.</p>}
            </section>
            <section className="card" id="consoles">
              <h2>Consoles</h2>
              {inventory.consoles.length ? <ul>{inventory.consoles.map((console) => <li key={console.id}>{console.name} · {console.is_published ? 'Publicado' : 'Aguardando publicação'}</li>)}</ul> : <p>Nenhum console vinculado.</p>}
            </section>
          </div>
        </div>
      )}
    </section>
  );
}

export default function OwnerPage() {
  return <RequireAuth><OwnerPortal /></RequireAuth>;
}
