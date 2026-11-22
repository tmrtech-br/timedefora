'use client';
import { Radio } from 'lucide-react';

type Ch = { provider: 'twitch' | 'kick' | 'external'; channel_name: string | null; external_url: string | null; status: string } | null;

/** Player de ESPECTADOR (sem controles). Separado do stream privado interativo. */
export default function PublicStream({ channel }: { channel: Ch }) {
  if (!channel) {
    return <div className="player"><div className="sim-screen"><Radio size={40} aria-hidden /><p>Transmissão pública não configurada para este jogo.</p></div></div>;
  }
  if (channel.status !== 'live') {
    return <div className="player"><div className="sim-screen"><Radio size={40} aria-hidden /><p><b>Offline</b> — não há transmissão ao vivo agora.</p>
      {channel.provider !== 'external' && <p className="small">Canal: {channel.provider === 'twitch' ? 'Twitch' : 'Kick'} / {channel.channel_name}</p>}</div></div>;
  }
  if (channel.provider === 'external') {
    return <div className="player"><div className="sim-screen"><Radio size={40} aria-hidden /><p>Transmissão em plataforma externa autorizada.</p>
      <a className="btn cyan" href={channel.external_url || '#'} target="_blank" rel="noopener noreferrer">Assistir ao vivo</a></div></div>;
  }
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  const src = channel.provider === 'twitch'
    ? `https://player.twitch.tv/?channel=${encodeURIComponent(channel.channel_name || '')}&parent=${host}&muted=true`
    : `https://player.kick.com/${encodeURIComponent(channel.channel_name || '')}?muted=true`;
  return <div className="player"><iframe src={src} title="Transmissão pública ao vivo (somente espectador)" allow="fullscreen" sandbox="allow-scripts allow-same-origin allow-popups" /></div>;
}
