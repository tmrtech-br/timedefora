'use client';
import Link from 'next/link';
import { Clock3 } from 'lucide-react';
import { Empty, PageHeader, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { minutesLabel, money } from '@/lib/format';
import type { GameCard as G } from '@/lib/types';

type D = { title: string; slug: string; packages: { minutes: number; price_cents: number; promotion: boolean }[] };

export default function Planos() {
  const home = useApi<{ featured: (G & { packages: { minutes: number; price_cents: number }[] }) | null }>('/catalog/home');
  const games = useApi<G[]>('/catalog/games?sort=title');
  return (
    <div className="stack">
      <PageHeader title="Planos e preços" subtitle="Preços definidos pelo servidor; podem variar por jogo, console, horário e promoções." />
      {!home.data ? <Skeleton h={120} /> : home.data.featured?.packages.length ? (
        <div className="pkg-grid">{home.data.featured.packages.map((p) => (
          <div key={p.minutes} className="pkg"><span className="row"><Clock3 size={16} /><b>{minutesLabel(p.minutes)}</b></span><span className="price">a partir de {money(p.price_cents)}</span></div>))}</div>
      ) : <Empty>Nenhum pacote publicado.</Empty>}
      <section className="card"><h2>Preço inicial por jogo</h2>
        {games.data?.map((g) => <div key={g.id} className="spread" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
          <Link className="link-purple" href={`/jogos/${g.slug}`}>{g.title}</Link><span>{g.starting_price_cents != null ? `a partir de ${money(g.starting_price_cents)}` : 'sem pacotes'}</span></div>)}
      </section>
      <p className="small dim">Cupons de desconto podem ser aplicados na reserva. Pagamento por Pix ou cartão via Mercado Pago.</p>
    </div>
  );
}
