'use client';

import { createContext, useContext, useId, useState, type HTMLAttributes, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

const AccordionContext = createContext<{ open: string | null; toggle: (id: string) => void; show: (id: string) => void } | null>(null);

export function CardAccordion({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  return <AccordionContext.Provider value={{ open, show: setOpen, toggle: (id) => setOpen((current) => current === id ? null : id) }}>
    {children}
  </AccordionContext.Provider>;
}

export function CollapsibleCard({ title, children, className = 'card stack', ...props }: HTMLAttributes<HTMLElement> & {
  title: string; children: ReactNode;
}) {
  const group = useContext(AccordionContext);
  const id = useId();
  const [standalone, setStandalone] = useState(false);
  const cardId = props.id ?? id;
  const expanded = group ? group.open === cardId : standalone;
  return <section {...props} className={className}>
    <h2 style={{ margin: 0 }}><button className="btn accordion-trigger" type="button" aria-expanded={expanded}
      aria-controls={id} onClick={() => group ? group.toggle(cardId) : setStandalone(!standalone)}>
      {title}{expanded ? <ChevronDown aria-hidden size={16} /> : <ChevronRight aria-hidden size={16} />}
    </button></h2>
    <div id={id} className="accordion-body stack" hidden={!expanded}>{children}</div>
  </section>;
}

export function AccordionLink({ target, children }: { target: string; children: ReactNode }) {
  const group = useContext(AccordionContext);
  return <a href={`#${target}`} onClick={() => group?.show(target)}>{children}</a>;
}
