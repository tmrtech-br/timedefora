'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import GameCard from '@/components/GameCard';
import { Empty, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import { del, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import type { GameCard as G } from '@/lib/types';

type Filters = { platforms: { code: string; name: string; family: string }[]; genres: string[]; statuses: Record<string, string> };

function Catalog() {
  const sp = useSearchParams();
  const router = useRouter();
  const { me } = useAuth();
  const [q, setQ] = useState(sp.get('q') || '');
  const [platform, setPlatform] = useState(sp.get('plataforma') || '');
  const [genre, setGenre] = useState(sp.get('genero') || '');
  const [availability, setAvailability] = useState(sp.get('disponibilidade') || '');
  const [maxPrice, setMaxPrice] = useState(sp.get('preco') || '');
  const [sort, setSort] = useState(sp.get('ordem') || 'popularity');
  const [debounced, setDebounced] = useState(q);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 300); return () => clearTimeout(t); }, [q]);
  const qs = useMemo(() => {
    const p = new URLSearchParams();
    if (debounced) p.set('q', debounced); if (platform) p.set('platform', platform); if (genre) p.set('genre', genre);
    if (availability) p.set('availability', availability); if (maxPrice) p.set('max_price_cents', String(Number(maxPrice) * 100)); p.set('sort', sort);
    return p.toString();
  }, [debounced, platform, genre, availability, maxPrice, sort]);
  useEffect(() => {
    const p = new URLSearchParams();
    if (debounced) p.set('q', debounced); if (platform) p.set('plataforma', platform); if (genre) p.set('genero', genre);
    if (availability) p.set('disponibilidade', availability); if (maxPrice) p.set('preco', maxPrice); if (sort !== 'popularity') p.set('ordem', sort);
    router.replace(`/jogos${p.toString() ? '?' + p : ''}`, { scroll: false });
  }, [debounced, platform, genre, availability, maxPrice, sort, router]);
  const { data, error, loading, reload } = useApi<G[]>(`/catalog/games?${qs}`, 20000);
  const filters = useApi<Filters>('/catalog/filters').data;
  const favs = useApi<string[]>(me ? '/me/favorites' : null);
  async function toggleFav(id: string) {
    if (!me) return router.push('/entrar?proximo=/jogos');
    const on = favs.data?.includes(id);
    await (on ? del(`/me/favorites/${id}`) : put(`/me/favorites/${id}`));
    favs.setData(on ? (favs.data || []).filter((x) => x !== id) : [...(favs.data || []), id]);
  }
  return (
    <>
      <PageHeader title="Catálogo de jogos" subtitle="Disponibilidade, filas e estimativas calculadas em tempo real pelo servidor." />
      <div className="row" style={{ marginBottom: 16 }}>
        <label className="field" style={{ flex: '1 1 260px' }}><span className="sr-only">Buscar</span>
          <div style={{ position: 'relative' }}><Search size={17} style={{ position: 'absolute', left: 12, top: 12 }} aria-hidden />
            <input style={{ paddingLeft: 38, width: '100%' }} placeholder="Buscar jogos ou gêneros…" value={q} onChange={(e) => setQ(e.target.value)} /></div></label>
        <label className="field"><span className="sr-only">Console</span><select value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value="">Todos os consoles</option><option value="playstation">PlayStation</option><option value="xbox">Xbox</option><option value="nintendo">Nintendo</option></select></label>
        <label className="field"><span className="sr-only">Gênero</span><select value={genre} onChange={(e) => setGenre(e.target.value)}>
          <option value="">Todos os gêneros</option>{filters?.genres.map((g) => <option key={g}>{g}</option>)}</select></label>
        <label className="field"><span className="sr-only">Disponibilidade</span><select value={availability} onChange={(e) => setAvailability(e.target.value)}>
          <option value="">Qualquer disponibilidade</option>{filters && Object.entries(filters.statuses).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field"><span className="sr-only">Preço máximo</span><select value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)}>
          <option value="">Qualquer preço</option><option value="30">Até R$ 30</option><option value="50">Até R$ 50</option><option value="100">Até R$ 100</option></select></label>
        <label className="field"><span className="sr-only">Ordenar</span><select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="popularity">Mais populares</option><option value="price">Menor preço</option><option value="title">Nome</option><option value="release">Lançamentos</option></select></label>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <div className="games-grid" style={{ marginLeft: 0 }}>{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={182} />)}</div>
        : data && data.length ? (
          <div className="games-grid" style={{ marginLeft: 0 }}>
            {data.map((g) => <div key={g.id}><GameCard g={g} favorite={favs.data?.includes(g.id)} onFavorite={toggleFav} />
              <div className="small muted" style={{ padding: '4px 2px' }}>{g.status_label}{g.starting_price_cents != null && ` · a partir de R$ ${(g.starting_price_cents / 100).toLocaleString('pt-BR')}`}</div></div>)}
          </div>
        ) : <Empty>Nenhum jogo encontrado para estes filtros.</Empty>}
    </>
  );
}
export default function Page() { return <Suspense><Catalog /></Suspense>; }
