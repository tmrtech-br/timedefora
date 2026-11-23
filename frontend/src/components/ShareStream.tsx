'use client';
import { useEffect, useState } from 'react';
import { Check, Link2, Share2 } from 'lucide-react';
import { toast } from '@/components/Toaster';

/* Ícones próprios (traço simples, 24×24) para cada rede. */
const Icon = {
  whatsapp: (
    <svg viewBox="0 0 24 24" aria-hidden><path d="M12 3a9 9 0 0 0-7.7 13.6L3 21l4.5-1.2A9 9 0 1 0 12 3Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M9.2 7.6c-.5 0-1.2.6-1.2 1.6 0 2.9 3.3 6.4 6.6 6.4 1 0 1.6-.8 1.6-1.3l-.1-.5-1.9-.9-.9.9c-1.2-.4-2.6-1.7-3-3l.9-.9-.8-2c-.1-.2-.3-.3-.6-.3Z" fill="currentColor" /></svg>),
  telegram: (
    <svg viewBox="0 0 24 24" aria-hidden><path d="M21 4.5 3.5 11.3c-.7.3-.7 1 0 1.2l4.4 1.4 1.7 5.2c.2.6.9.7 1.3.3l2.5-2.3 4.4 3.2c.5.4 1.2.1 1.3-.5L21.9 5.4c.2-.7-.4-1.1-.9-.9Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="m8 13.8 9.5-6.3-6.8 7.3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>),
  x: (
    <svg viewBox="0 0 24 24" aria-hidden><path d="M4.5 4h4.2L19.5 20h-4.2Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M19.2 4 13.3 10.6M10.7 13.4 4.8 20" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>),
  facebook: (
    <svg viewBox="0 0 24 24" aria-hidden><path d="M13.6 21v-7.6h2.7l.4-3.2h-3.1V8.3c0-.9.3-1.6 1.6-1.6h1.7V3.9a21 21 0 0 0-2.5-.1c-2.5 0-4.2 1.5-4.2 4.3v2.1H7.4v3.2h2.8V21Z" fill="currentColor" /></svg>),
};

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
    { name: 'WhatsApp', cls: 'wa', icon: Icon.whatsapp, href: `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}` },
    { name: 'Telegram', cls: 'tg', icon: Icon.telegram, href: `https://t.me/share/url?url=${u}&text=${t}` },
    { name: 'X', cls: 'x', icon: Icon.x, href: `https://twitter.com/intent/tweet?url=${u}&text=${t}` },
    { name: 'Facebook', cls: 'fb', icon: Icon.facebook, href: `https://www.facebook.com/sharer/sharer.php?u=${u}` },
  ];

  async function copy() {
    try { await navigator.clipboard.writeText(url); setCopied(true); toast('ok', 'Link da transmissão copiado.'); setTimeout(() => setCopied(false), 2500); }
    catch { toast('error', 'Não foi possível copiar o link.'); }
  }

  return (
    <div className="share-bar" role="group" aria-label="Compartilhar transmissão">
      <span className="share-label">Compartilhar</span>
      {canNative && (
        <button type="button" className="share-ico native" title="Enviar…" aria-label="Compartilhar pelo celular"
          onClick={() => navigator.share({ title: `${title} ao vivo — LocaPlay`, text, url }).catch(() => {})}><Share2 aria-hidden /></button>)}
      {links.map((l) => (
        <a key={l.name} className={`share-ico ${l.cls}`} href={l.href} target="_blank" rel="noopener noreferrer" title={l.name} aria-label={`Compartilhar no ${l.name}`}>{l.icon}</a>))}
      <button type="button" className={`share-ico link ${copied ? 'done' : ''}`} title={copied ? 'Copiado!' : 'Copiar link'} aria-label="Copiar link da transmissão" onClick={copy}>
        {copied ? <Check aria-hidden /> : <Link2 aria-hidden />}</button>
    </div>
  );
}
