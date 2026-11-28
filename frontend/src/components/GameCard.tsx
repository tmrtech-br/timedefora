'use client';
import Link from 'next/link';
import { Gamepad2, Heart, ListOrdered } from 'lucide-react';
import type { GameCard as G } from '@/lib/types';
import { rememberGamePreview } from '@/lib/gamePreview';

export function platformLabel(g: G) {
  return g.platforms.map((p) => (p.code === 'SWITCH' ? 'Nintendo Switch' : p.code === 'XBOX_SERIES' ? 'Xbox Series' : p.code)).join(' · ') || '—';
}

export default function GameCard({ g, favorite, onFavorite }: { g: G; favorite?: boolean; onFavorite?: (id: string) => void }) {
  return (
    <article className="game-card">
      <div className="game-art" style={g.cover_url ? { backgroundImage: `url(${g.cover_url})` } : undefined}>
        {!g.cover_url && <span className="ph"><Gamepad2 size={34} aria-hidden /></span>}
        {onFavorite && (
          <button className="fav-btn" onClick={() => onFavorite(g.id)} aria-pressed={!!favorite} aria-label={favorite ? `Remover ${g.title} dos favoritos` : `Favoritar ${g.title}`}>
            <Heart size={15} fill={favorite ? '#c13eff' : 'none'} color={favorite ? '#c13eff' : '#fff'} />
          </button>
        )}
      </div>
      <div className="game-info">
        <strong title={g.title}>{g.title}</strong>
        <div className="game-meta">
          <span><Gamepad2 aria-hidden />{platformLabel(g)}</span>
          <span title={g.status_label}><ListOrdered aria-hidden />Fila: {g.queue_size}</span>
        </div>
        <Link className="btn-card" href={`/jogos/${g.slug}`} onClick={() => rememberGamePreview(g)} aria-label={`Ver detalhes de ${g.title}`}>Ver detalhes</Link>
      </div>
    </article>
  );
}
