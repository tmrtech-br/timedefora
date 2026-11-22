'use client';
import { Alert, ErrorBox, PageHeader, Skeleton } from './ui';
import { useApi } from '@/lib/hooks';
import { dateTime } from '@/lib/format';

export default function PolicyPage({ kind }: { kind: 'terms' | 'privacy' | 'cancellation' }) {
  const { data, error } = useApi<{ title: string; body: string; version: string; published_at: string; requires_legal_review: boolean }>(`/policies/${kind}`);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Skeleton h={300} />;
  return (
    <div className="stack" style={{ maxWidth: 860 }}>
      <PageHeader title={data.title} subtitle={`Versão ${data.version} · publicada em ${dateTime(data.published_at)}`} />
      {data.requires_legal_review && <Alert kind="warn">Documento em rascunho: precisa de revisão jurídica antes da operação comercial.</Alert>}
      <article className="card" style={{ whiteSpace: 'pre-line', lineHeight: 1.6 }}>{data.body}</article>
    </div>
  );
}
