'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

export default function LimitedScroll({ children, label, limit = 5 }: { children: ReactNode[]; label: string; limit?: number }) {
  const firstGroup = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number>();
  const hasMore = children.length > limit;

  useEffect(() => {
    const group = firstGroup.current;
    if (!group || !hasMore) return;
    const measure = () => setHeight(group.getBoundingClientRect().height);
    const observer = new ResizeObserver(measure);
    observer.observe(group);
    measure();
    return () => observer.disconnect();
  }, [hasMore]);

  return (
    <div className="stack limited-scroll" data-scrollable={hasMore} style={{ maxHeight: hasMore ? height : undefined }}
      role="region" aria-label={label} tabIndex={hasMore ? 0 : undefined}>
      <div className="stack" ref={firstGroup}>{children.slice(0, limit)}</div>
      {hasMore && <div className="stack">{children.slice(limit)}</div>}
    </div>
  );
}
