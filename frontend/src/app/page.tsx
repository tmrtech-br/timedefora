'use client';
import Link from 'next/link';
import { ArrowRight, ChevronRight, CircleChevronRight, Clock3, CreditCard, Gamepad2, Layers3, ListOrdered, Play, Radio, UserRound, ChevronsRight } from 'lucide-react';
import GameCard from '@/components/GameCard';
import { ErrorBox, Skeleton } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { minutesLabel, moneyShort } from '@/lib/format';
import type { GameCard as G } from '@/lib/types';

type Home = {
  demo_mode: boolean; sales_paused: boolean;
  featured: (G & { highlight_label: string; description: string; packages: { minutes: number; price_cents: number }[];
    console: { name: string; available: boolean; status_label: string } | null }) | null;
  featured_games: G[];
  live_queue: { game_title: string; game_slug: string; cover_url: string | null; console_name: string; playing: string | null;
    next: string | null; my_position: number | null; estimated_wait_minutes: number | null; size: number } | null;
};

function Title({ text }: { text: string }) {
  const parts = text.trim().split(' ');
  if (parts.length < 2) return <h1>{text}</h1>;
  const last = parts.pop();
  return <h1>{parts.join(' ')} <em>{last}</em></h1>;
}

export default function HomePage() {
  const { data, error, reload } = useApi<Home>('/catalog/home', 15000);
  const f = data?.featured;
  return (
    <>
      <ErrorBox error={error} onRetry={reload} />
      {data?.sales_paused && <div className="notice-bar">Vendas temporariamente pausadas pela operação.</div>}
      {!data ? <Skeleton h={298} /> : !f ? (
        <section className="hero"><div className="hero-copy" style={{ paddingTop: 60 }}><h2>Nenhum jogo publicado ainda</h2>
          <p>Assim que a equipe publicar jogos e consoles, eles aparecerão aqui.</p></div></section>
      ) : (
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-sky" aria-hidden />
          <div className="hero-art" style={{ backgroundImage: `url(${f.banner_url || f.cover_url || ''})` }} role="img" aria-label={`Arte de ${f.title}`} />
          <div className="hero-copy" id="hero-title">
            <span className="hot"><span aria-hidden>🔥</span>{f.highlight_label}</span>
            <Title text={f.title} />
            <h2>{f.short_description || 'Jogue sem console'}</h2>
            <h3>Alugue seu tempo e jogue direto no navegador.</h3>
            <p>{f.description}</p>
            <div className="hero-actions">
              <Link className="btn-primary" href={`/jogos/${f.slug}#reservar`}><Play size={19} aria-hidden />Jogar agora</Link>
              <Link className="btn-ghost" href={`/jogos/${f.slug}#ao-vivo`}><Radio size={19} aria-hidden />Assistir ao vivo</Link>
            </div>
          </div>
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
          {data.demo_mode && <span className="demo-tag">Dados de demonstração · consoles e pagamentos simulados</span>}
        </section>
      )}

      <div className="section-title">
        <h2><Gamepad2 aria-hidden />Jogos em destaque</h2>
        <Link className="link-purple" href="/jogos">Ver catálogo completo <ArrowRight size={16} aria-hidden /></Link>
      </div>
      <div className="games-grid">
        {!data ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={182} />) : data.featured_games.map((g) => <GameCard key={g.id} g={g} />)}
      </div>

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
          ) : <p className="muted" style={{ marginTop: 14 }}>{data ? 'Nenhuma fila ativa no momento.' : 'Carregando…'}</p>}
        </section>
        <section className="panel how-panel" aria-labelledby="como-funciona-home" id="como-funciona">
          <div className="panel-title"><h2 id="como-funciona-home"><Layers3 aria-hidden />Como funciona</h2></div>
          <div className="steps">
            <div className="step"><Gamepad2 aria-hidden /><b>1. Escolha o jogo</b><small>Navegue pelo catálogo e selecione o seu favorito.</small></div>
            <ChevronRight className="step-arrow" aria-hidden />
            <div className="step"><CreditCard aria-hidden /><b>2. Compre o tempo</b><small>Alugue por minutos, de forma rápida e segura.</small></div>
            <ChevronRight className="step-arrow" aria-hidden />
            <div className="step"><CircleChevronRight aria-hidden /><b>3. Jogue no navegador</b><small>Conecte-se na nuvem e jogue na hora, sem console.</small></div>
          </div>
        </section>
      </div>
    </>
  );
}
