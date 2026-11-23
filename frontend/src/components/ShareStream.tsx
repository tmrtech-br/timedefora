'use client';
import { useEffect, useState } from 'react';
import { Check, Link2, Share2 } from 'lucide-react';
import { toast } from '@/components/Toaster';

/** Botões para compartilhar a transmissão ao vivo (link da página do jogo, âncora #ao-vivo). */
export default function ShareStream({ title, live }: { title: string; live: boolean }) {
  const [url, setUrl] = useState('');
  const [canNative, setCanNative] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setUrl(`${window.location.origin}${window.location.pathname}#ao-vivo`);
    setCanNative(typeof navigator.share === 'function');
  }, []);
  if (!url) return null;

  const text = live ? `Estou assistindo ${title} ao vivo na LocaPlay!` : `Assista ${title} ao vivo na LocaPlay`;
  const u = encodeURIComponent(url), t = encodeURIComponent(text);
  const links = [
    { name: 'WhatsApp', cls: 'wa', href: `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}` },
    { name: 'Telegram', cls: 'tg', href: `https://t.me/share/url?url=${u}&text=${t}` },
    { name: 'X', cls: 'x', href: `https://twitter.com/intent/tweet?url=${u}&text=${t}` },
    { name: 'Facebook', cls: 'fb', href: `https://www.facebook.com/sharer/sharer.php?u=${u}` },
  ];

  async function copy() {
    try { await navigator.clipboard.writeText(url); setCopied(true); toast('ok', 'Link da transmissão copiado.'); setTimeout(() => setCopied(false), 2500); }
    catch { toast('error', 'Não foi possível copiar o link.'); }
  }

  return (
    <div className="share-bar" role="group" aria-label="Compartilhar transmissão">
      <span className="share-label"><Share2 size={15} aria-hidden />Compartilhar</span>
      {canNative && (
        <button type="button" className="share-btn native" onClick={() => navigator.share({ title: `${title} ao vivo — LocaPlay`, text, url }).catch(() => {})}>
          <Share2 size={15} aria-hidden />Enviar</button>)}
      {links.map((l) => (
        <a key={l.name} className={`share-btn ${l.cls}`} href={l.href} target="_blank" rel="noopener noreferrer" aria-label={`Compartilhar no ${l.name}`}>{l.name}</a>))}
      <button type="button" className="share-btn" onClick={copy}>{copied ? <Check size={15} aria-hidden /> : <Link2 size={15} aria-hidden />}{copied ? 'Copiado' : 'Copiar link'}</button>
    </div>
  );
}
