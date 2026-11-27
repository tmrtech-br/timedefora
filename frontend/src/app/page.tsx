'use client';
import Link from 'next/link';
import { ArrowRight, Clock3, Gamepad2, ListOrdered, Monitor, Ticket, Play, Radio, UserRound, ChevronsRight } from 'lucide-react';
import GameCard from '@/components/GameCard';
import { Alert, Empty, ErrorBox, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { minutesLabel, moneyShort } from '@/lib/format';
import type { GameCard as G } from '@/lib/types';
import { useFeatures } from '@/lib/features';

type Home = {
  demo_mode: boolean; sales_paused: boolean;
  featured: (G & { packages: { minutes: number; price_cents: number }[];
    console: { name: string; available: boolean; status_label: string } | null }) | null;
  featured_games: G[];
  live_queue: { game_title: string; game_slug: string; cover_url: string | null; console_name: string; playing: string | null;
    next: string | null; my_position: number | null; estimated_wait_minutes: number | null; size: number } | null;
};

export default function HomePage() {
  const { data, error, reload } = useApi<Home>('/catalog/home', 15000);
  const features = useFeatures();
  const f = data?.featured;
  return (
    <>
      <ErrorBox error={error} onRetry={reload} />
      {data?.sales_paused && <Alert kind="warn">Vendas temporariamente pausadas pela operação.</Alert>}
      {!data && !error && <div className="home-loading" role="status"><span className="sr-only">Carregando a página inicial</span><Skeleton h={410} /></div>}
      {data && (
        <section className="hero" aria-labelledby="hero-title">
          <div
            className="hero-art"
            aria-hidden="true"
            style={f?.banner_url ? { backgroundImage: `url(${JSON.stringify(f.banner_url)}), url("/assets/locaplay-studio.webp")` } : undefined}
          />
          <div className="hero-copy">
            <h1 id="hero-title">timede<span className="hero-title-accent">fora</span></h1>
            <p className="hero-lead">Sua locadora de games na nuvem.</p>
            {f ? <>
              <p className="hero-feature"><strong>{f.title}</strong>{f.short_description && <span>{f.short_description}</span>}</p>
              <div className="hero-actions">
                <Link className="btn-primary" href={`/jogos/${f.slug}#reservar`}><Play size={18} aria-hidden />Jogar agora</Link>
                {features?.public_streams_enabled !== false && <Link className="btn-ghost" href={`/jogos/${f.slug}#ao-vivo`}><Radio size={18} aria-hidden />Assistir ao vivo</Link>}
              </div>
            </> : <p>Nenhum jogo publicado ainda.</p>}
          </div>
          {f && (
            <aside className="hero-panel" aria-label="Pacotes e disponibilidade">
              {f.packages.slice(0, 3).map((p) => (
                <div className="price-line" key={p.minutes}><Clock3 aria-hidden /><span>{p.minutes} min — {moneyShort(p.price_cents)}</span></div>
              ))}
              {!f.packages.length && <div className="muted-line">Pacotes ainda não configurados</div>}
              <hr />
              <div className="muted-line"><ListOrdered aria-hidden />Fila: <span className="hl">{f.queue_size} {f.queue_size === 1 ? 'jogador' : 'jogadores'}</span></div>
              <div className="muted-line"><Clock3 aria-hidden />Tempo estimado: <strong>{f.estimated_wait_minutes == null ? 'indisponível' : `~ ${minutesLabel(f.estimated_wait_minutes)}`}</strong></div>
              {f.console ? (
                <div className={`console-ok ${f.console.available ? '' : 'off'}`}><Gamepad2 size={22} aria-hidden />{f.console.name} {f.console.status_label}<span className="dot" aria-hidden /></div>
              ) : <div className="console-ok off"><Gamepad2 size={22} aria-hidden />Nenhum console disponível<span className="dot" aria-hidden /></div>}
            </aside>
          )}
          {data.demo_mode && <span className="demo-tag">Dados de demonstração · consoles e pagamentos simulados</span>}
        </section>
      )}

      <div className="section-title">
        <h2>Jogos em destaque</h2>
        <Link className="link-purple" href="/jogos">Ver catálogo completo <ArrowRight size={16} aria-hidden /></Link>
      </div>
      <div className="games-grid">
        {!data && !error ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={182} />) : (data?.featured_games || []).map((g) => <GameCard key={g.id} g={g} />)}
      </div>

      {data && !data.featured_games.length && <div className="home-empty"><Empty>Nenhum jogo em destaque no momento.</Empty></div>}
      <div className="lower-grid">
        <section className="panel live-panel" aria-labelledby="fila-ao-vivo">
          <div className="panel-title">
            <h2 id="fila-ao-vivo"><Radio aria-hidden />Fila ao vivo</h2>
            {data?.live_queue && <span className="game-tag">{data.live_queue.game_title}</span>}
          </div>
          {data?.live_queue ? (
            <div className="live-body">
              {data.live_queue.cover_url ? <img src={data.live_queue.cover_url} alt="" /> : <span className="live-thumb" />}
              <div className="live-users">
                <div><Gamepad2 aria-hidden />Jogando agora: <b>{data.live_queue.playing || 'ninguém'}</b></div>
                <div><ChevronsRight aria-hidden />Próximo: <b>{data.live_queue.next || '—'}</b></div>
                <div><UserRound aria-hidden />Sua posição: <b>{data.live_queue.my_position ? `${data.live_queue.my_position}º` : '—'}</b></div>
              </div>
              <div className="live-eta">
                <span><Clock3 size={17} aria-hidden />Tempo estimado:</span>
                <strong>{data.live_queue.estimated_wait_minutes == null ? '—' : `~ ${String(data.live_queue.estimated_wait_minutes).padStart(2, '0')} min`}</strong>
              </div>
            </div>
          ) : <p className="muted" style={{ marginTop: 14 }}>{data ? 'Nenhuma fila ativa no momento.' : error ? 'Não foi possível consultar a fila.' : 'Carregando…'}</p>}
        </section>
        <section className="panel how-panel" aria-labelledby="como-funciona-home" id="como-funciona">
          <div className="panel-title"><h2 id="como-funciona-home">Como funciona</h2></div>
          <div className="steps">
            <div className="step"><Gamepad2 aria-hidden /><b>1. Escolha o jogo</b><small>Navegue pelo catálogo e selecione o seu favorito.</small></div>
            <div className="step"><Ticket aria-hidden /><b>2. Compre o tempo</b><small>Alugue por minutos, de forma rápida e segura.</small></div>
            <div className="step"><Monitor aria-hidden /><b>3. Jogue no navegador</b><small>Conecte-se na nuvem e jogue na hora, sem console.</small></div>
          </div>
        </section>
      </div>
    </>
  );
}
