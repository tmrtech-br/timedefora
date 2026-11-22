import { QUEUE_STATUS, time } from '@/lib/format';
import type { QueueItem } from '@/lib/types';

export default function QueueList({ items }: { items: QueueItem[] }) {
  if (!items.length) return <p className="muted small">Fila vazia.</p>;
  return (
    <ol className="queue-list" aria-label="Fila do console" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {items.map((q) => (
        <li key={q.position} className={`queue-row ${q.is_me ? 'me' : ''}`}>
          <span className="num">{q.position}</span>
          <span><b>{q.username}</b> {q.is_me && <span className="pill purple">você</span>}</span>
          <span className="muted small">{QUEUE_STATUS[q.status] || q.status}</span>
          <span className="small">{time(q.estimated_start_at)}–{time(q.estimated_end_at)}</span>
        </li>
      ))}
    </ol>
  );
}
