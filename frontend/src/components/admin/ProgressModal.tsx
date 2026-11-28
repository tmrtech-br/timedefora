'use client';

import { Alert, ModalShell } from '@/components/ui';

export const CONSOLE_TESTS: [string, string][] = [
  ['discover', 'Descobrir console'], ['pair', 'Parear'], ['psn_auth', 'Testar autenticação PSN'],
  ['connection', 'Testar conexão'], ['video_audio', 'Testar imagem e áudio'],
  ['controls', 'Testar controles'], ['heartbeat', 'Verificar heartbeat'], ['latency', 'Medir latência'],
];

export function ProgressModal({ tests, status, error, onCancel, guidance }: {
  tests: { id: string; label: string; state: string }[];
  status: string; error?: string; onCancel?: () => void; guidance?: React.ReactNode;
}) {
  const complete = tests.filter((test) => !['Na fila', 'Em execução'].includes(test.state)).length;
  return <ModalShell title="Diagnóstico do console" closeLabel="Cancelar" showCloseButton={!!onCancel} onClose={() => onCancel?.()}>
    <div className="stack">
      <p role="status">{status}</p>
      {guidance}
      {error && <Alert kind="error">{error}</Alert>}
      <progress className="admin-diagnostic-progress" aria-label="Progresso do diagnóstico" value={complete} max={Math.max(1, tests.length)} />
      <ul className="stack">{tests.map((test) => <li className="spread" key={test.id}>
        <span>{test.label}</span><span className="pill">{test.state}</span>
      </li>)}</ul>
    </div>
  </ModalShell>;
}
