'use client';
import { useEffect, useRef } from 'react';
import { QUEUE_STATUS, time } from '@/lib/format';
import type { QueueItem } from '@/lib/types';

/** Fila do console. maxVisible: quantas linhas aparecem sem rolar (o resto fica numa barra de rolagem). */
export default function QueueList({ items, maxVisible }: { items: QueueItem[]; maxVisible?: number }) {
  const box = useRef<HTMLOListElement>(null);
  const scroll = !!maxVisible && items.length > maxVisible;
  const mePos = items.find((q) => q.is_me)?.position;
  // Se o jogador estiver depois das primeiras linhas, rola a lista até ele (sem mexer na rolagem da página).
  useEffect(() => {
    if (!scroll || !box.current) return;
    const me = box.current.querySelector<HTMLLIElement>('.queue-row.me');
    if (me) box.current.scrollTop = me.offsetTop - box.current.offsetTop - box.current.clientHeight / 2 + me.clientHeight / 2;
  }, [scroll, mePos]);
  if (!items.length) return <p className="muted small">Fila vazia.</p>;
  return (
    <ol ref={box} className={`queue-list${scroll ? ' scroll' : ''}`} aria-label="Fila do console" tabIndex={scroll ? 0 : undefined}
      style={{ listStyle: 'none', padding: 0, margin: 0, ...(scroll ? { ['--rows' as string]: maxVisible } : {}) }}>
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
