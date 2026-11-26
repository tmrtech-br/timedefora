'use client';

import KeyBindingsEditor from '@/components/KeyBindings';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import type { Features } from '@/lib/features';
import { useApi } from '@/lib/hooks';

function Controles() {
  const { data, error, reload } = useApi<Features>('/features', 60000);
  return (
    <>
      <PageHeader title="Controles do teclado e mouse" subtitle="Personalize as teclas e a sensibilidade do mouse para suas partidas." />
      <ErrorBox error={error} onRetry={reload} />
      {data ? (
        data.controls_menu_enabled ? <KeyBindingsEditor /> : <Empty>A personalização de teclado e mouse está desativada.</Empty>
      ) : !error && <Skeleton h={160} />}
    </>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Controles />
    </RequireAuth>
  );
}
