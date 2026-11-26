'use client';

import { ModalShell } from '@/components/ui';

export function ProgressModal({ tests, status, error, onCancel }: {
  tests: { id: string; label: string; state: string }[];
  status: string; error?: string; onCancel: () => void;
}) {
  const complete = tests.filter((test) => !['Na fila', 'Em execução'].includes(test.state)).length;
  return <ModalShell title="Diagnóstico do console" closeLabel="Cancelar" onClose={onCancel}>
    <div className="stack">
      <p role="status">{status}</p>
      {error && <p role="alert">{error}</p>}
      <progress aria-label="Progresso do diagnóstico" value={complete} max={Math.max(1, tests.length)} />
      <ul className="stack">{tests.map((test) => <li className="spread" key={test.id}>
        <span>{test.label}</span><span className="pill">{test.state}</span>
      </li>)}</ul>
    </div>
  </ModalShell>;
}
