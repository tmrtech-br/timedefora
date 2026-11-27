'use client';

import { useEffect, useId, useRef, useState } from 'react';

export default function PolicyConsent({ policy, action, onClose, onConfirm }: {
  policy: { title: string; body: string }; action: string; onClose: () => void; onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const document = useRef<HTMLDivElement>(null);
  const title = useId();
  const [read, setRead] = useState(false);
  const [accepted, setAccepted] = useState(false);
  function checkEnd() {
    const area = document.current;
    if (area && area.scrollTop + area.clientHeight >= area.scrollHeight - 2) setRead(true);
  }

  useEffect(() => {
    dialog.current?.showModal();
    const observer = new ResizeObserver(checkEnd);
    if (document.current) observer.observe(document.current);
    return () => observer.disconnect();
  }, []);

  return <dialog className="card policy-dialog" ref={dialog} aria-labelledby={title} onCancel={(e) => { e.preventDefault(); onClose(); }}>
    <div className="spread"><h2 id={title}>{policy.title}</h2><button className="btn" type="button" onClick={onClose}>Fechar</button></div>
    <div className="policy-document" ref={document} onScroll={checkEnd} tabIndex={0} role="region" aria-labelledby={title}>{policy.body}</div>
    {!read && <p className="small muted">Role até o fim do documento para liberar o aceite.</p>}
    <label className="check"><input type="checkbox" disabled={!read} checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
      <span>Li e aceito a política de agendamento, ausência, atraso, cancelamento e reembolso.</span>
    </label>
    <button type="button" className="btn primary" disabled={!accepted} onClick={onConfirm}>{action}</button>
  </dialog>;
}
