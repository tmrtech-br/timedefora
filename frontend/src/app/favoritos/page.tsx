'use client';
import Link from 'next/link';
import GameCard from '@/components/GameCard';
import RequireAuth from '@/components/RequireAuth';
import { Empty, PageHeader, Skeleton } from '@/components/ui';
import { del } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import type { GameCard as G } from '@/lib/types';

function Favoritos() {
  const games = useApi<G[]>('/catalog/games');
  const favs = useApi<string[]>('/me/favorites');
  if (!games.data || !favs.data) return <Skeleton h={200} />;
  const list = games.data.filter((g) => favs.data!.includes(g.id));
  return (
    <>
      <PageHeader title="Favoritos" subtitle="Jogos marcados para acesso rápido." />
      {!list.length ? <Empty>Nenhum favorito. Toque no coração de um jogo no <Link className="link-purple" href="/jogos">catálogo</Link>.</Empty> : (
        <div className="games-grid" style={{ marginLeft: 0 }}>{list.map((g) => <GameCard key={g.id} g={g} favorite onFavorite={async (id) => { await del(`/me/favorites/${id}`); favs.reload(); }} />)}</div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Favoritos /></RequireAuth>; }
