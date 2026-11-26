'use client';

import { useEffect, useState } from 'react';
import RequireAuth from '@/components/RequireAuth';
import OwnerInventory from '@/components/OwnerInventory';
import { Alert } from '@/components/ui';
import { get, post } from '@/lib/api';
import { useAuth } from '@/lib/auth';

type Terms = { id: string; version: string; body: string; accepted_at: string | null };

function OwnerPortal() {
  const { me } = useAuth();
  const isOwner = me?.roles.includes('owner') === true;
  const [terms, setTerms] = useState<Terms>();
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

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
      {terms?.accepted_at && <OwnerInventory />}
    </section>
  );
}

export default function OwnerPage() {
  return <RequireAuth><OwnerPortal /></RequireAuth>;
}
