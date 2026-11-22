'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { AlertTriangle, CalendarClock, Clock3, Gamepad2, Heart, ListOrdered, Radio } from 'lucide-react';
import PublicStream from '@/components/PublicStream';
import QueueList from '@/components/QueueList';
import { Alert, ErrorBox, Field, Skeleton } from '@/components/ui';
import { ApiError, del, get, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime, minutesLabel, money, time } from '@/lib/format';
import type { GameCard as G, QueueItem, Reservation } from '@/lib/types';
import { useFeatures } from '@/lib/features';

type ConsoleAvail = { console_id: string; console_name: string; messages: string[]; queue_size: number; playing_now: string | null;
  current_window: { starts_at: string; ends_at: string; remaining_minutes: number } | null; next_window: { starts_at: string } | null;
  last_free_minutes?: number; packages: { minutes: number; price_cents: number; fits: boolean; estimated_start_at: string | null; estimated_end_at: string | null }[];
  queue: QueueItem[] };
type Detail = G & { description: string; age_rating: string | null; requirements: string; min_minutes: number; max_minutes: number;
  packages: { minutes: number; price_cents: number; promotion: boolean }[]; availability: { server_time: string; notice: string; consoles: ConsoleAvail[] };
  public_stream: { provider: 'twitch' | 'kick' | 'external'; channel_name: string | null; external_url: string | null; status: string } | null;
  is_favorite: boolean; commercially_licensed: boolean; cancellation_policy: { title: string; body: string; version: string } | null };
type Quote = { available: boolean; message?: string; console_name?: string; starts_at?: string; ends_at?: string; price_cents?: number; estimate_notice?: string };

export default function GamePage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const { me } = useAuth();
  const { data: g, error, reload } = useApi<Detail>(`/catalog/games/${slug}`, 10000);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [mode, setMode] = useState<'queue' | 'scheduled'>('queue');
  const [startLocal, setStartLocal] = useState('');
  const [coupon, setCoupon] = useState('');
  const features = useFeatures();
  useEffect(() => {
    if (!features) return;
    if (mode === 'queue' && !features.queue_mode_enabled && features.scheduled_mode_enabled) setMode('scheduled');
    if (mode === 'scheduled' && !features.scheduled_mode_enabled && features.queue_mode_enabled) setMode('queue');
  }, [features, mode]);
  const [accept, setAccept] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [fav, setFav] = useState(false);
  useEffect(() => { if (g) setFav(g.is_favorite); }, [g]);
  useEffect(() => {
    if (!minutes || !g) { setQuote(null); return; }
    if (mode === 'scheduled' && !startLocal) { setQuote(null); return; }
    const p = new URLSearchParams({ minutes: String(minutes), mode });
    if (mode === 'scheduled') p.set('start_at', new Date(startLocal + ':00-03:00').toISOString());
    get<Quote>(`/catalog/games/${slug}/quote?${p}`).then(setQuote).catch(() => setQuote(null));
  }, [minutes, mode, startLocal, slug, g]);

  async function reserve() {
    if (!me) return router.push(`/entrar?proximo=/jogos/${slug}`);
    if (!me.email_verified) return router.push('/verificar-email');
    setBusy(true); setErr('');
    try {
      const body: Record<string, unknown> = { game_id: g!.id, minutes, mode, accept_policy: accept, coupon_code: coupon || null };
      if (mode === 'scheduled') body.start_at = new Date(startLocal + ':00-03:00').toISOString();
      const r = await post<Reservation>('/reservations', body);
      router.push(`/checkout/${r.id}`);
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Erro ao reservar.'); reload(); }
    finally { setBusy(false); }
  }
  async function toggleFav() {
    if (!me) return router.push(`/entrar?proximo=/jogos/${slug}`);
    await (fav ? del(`/me/favorites/${g!.id}`) : put(`/me/favorites/${g!.id}`));
    setFav(!fav);
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!g) return <Skeleton h={420} />;
  const fitsAny = (m: number) => g.availability.consoles.some((c) => c.packages.find((p) => p.minutes === m)?.fits);
  return (
    <div className="stack">
      {g.is_demo && <Alert kind="warn">Jogo de demonstração: console e pagamento <b>simulados</b>. Exploração comercial ainda não autorizada.</Alert>}
      <section className="game-hero">
        <img src={g.cover_url || ''} alt={`Capa de ${g.title}`} />
        <div className="stack">
          <div className="spread"><h1 style={{ margin: 0, fontSize: 32 }}>{g.title}</h1>
            <button className="btn" onClick={toggleFav} aria-pressed={fav}><Heart size={16} fill={fav ? '#c13eff' : 'none'} />{fav ? 'Favorito' : 'Favoritar'}</button></div>
          <div className="row">
            {g.platforms.map((p) => <span key={p.code} className="pill"><Gamepad2 size={13} />{p.name}</span>)}
            {g.genres.map((x) => <span key={x} className="pill purple">{x}</span>)}
            {g.age_rating && <span className="pill amber">Classificação {g.age_rating}</span>}
            <span className={`pill ${g.status === 'available' ? 'green' : g.status === 'unavailable' ? 'red' : 'cyan'}`}>{g.status_label}</span>
          </div>
          <p style={{ margin: 0, color: '#ddd7ee' }}>{g.description}</p>
          {g.requirements && <p className="small muted" style={{ margin: 0 }}>Requisitos de conexão: {g.requirements}</p>}
          <p className="small muted" style={{ margin: 0 }}>Recomendado: conexão estável de 15 Mbps+, navegador atualizado no PC/notebook, teclado e mouse ou controle USB/Bluetooth.</p>
        </div>
      </section>

      <div className="grid2">
        <section className="card" id="reservar" aria-labelledby="t-reservar">
          <h2 id="t-reservar">Escolha seu tempo</h2>
          {g.availability.consoles.length === 0 && <Alert kind="warn">Nenhum console disponível para este jogo no momento.</Alert>}
          <div className="pkg-grid" role="radiogroup" aria-label="Pacotes de tempo">
            {g.packages.map((p) => (
              <button key={p.minutes} role="radio" aria-checked={minutes === p.minutes} className={`pkg ${minutes === p.minutes ? 'on' : ''}`}
                onClick={() => setMinutes(p.minutes)} disabled={mode === 'queue' && !fitsAny(p.minutes)}>
                <span className="row"><Clock3 size={16} aria-hidden /><b>{minutesLabel(p.minutes)}</b></span>
                <span className="price">{money(p.price_cents)}</span>
                {mode === 'queue' && !fitsAny(p.minutes) && <span className="small dim">Não cabe na janela livre</span>}
                {p.promotion && <span className="pill amber">Promoção</span>}
              </button>
            ))}
          </div>
          <div className="row" style={{ margin: '14px 0' }} role="radiogroup" aria-label="Tipo de reserva">
            {features?.queue_mode_enabled !== false && <label className="check"><input type="radio" checked={mode === 'queue'} onChange={() => setMode('queue')} /><span><b>Entrar na fila</b> — início estimado, pode antecipar</span></label>}
            {features?.scheduled_mode_enabled !== false && <label className="check"><input type="radio" checked={mode === 'scheduled'} onChange={() => setMode('scheduled')} /><span><b>Horário fixo</b></span></label>}
            {features && !features.queue_mode_enabled && !features.scheduled_mode_enabled && <Alert kind="warn">Compras temporariamente indisponíveis.</Alert>}
          </div>
          {mode === 'scheduled' && <Field label="Data e hora de início (horário de Fortaleza)"><input type="datetime-local" step={60} value={startLocal} onChange={(e) => setStartLocal(e.target.value)} /></Field>}
          {quote && (quote.available ? (
            <Alert kind="info"><span>{mode === 'queue' ? 'Início estimado' : 'Horário'}: <b>{dateTime(quote.starts_at)}</b> até <b>{time(quote.ends_at)}</b> no {quote.console_name} · {money(quote.price_cents)}.<br />
              <span className="small">{quote.estimate_notice} Seu tempo conta a partir do início reservado.</span></span></Alert>
          ) : <Alert kind="warn">{quote.message}</Alert>)}
          <div className="stack" style={{ marginTop: 12 }}>
            {features?.coupons_enabled !== false && <Field label="Cupom (opcional)"><input value={coupon} onChange={(e) => setCoupon(e.target.value.toUpperCase())} maxLength={30} /></Field>}
            {g.cancellation_policy && (
              <details className="small"><summary>{g.cancellation_policy.title} (v{g.cancellation_policy.version})</summary>
                <p style={{ whiteSpace: 'pre-line' }} className="muted">{g.cancellation_policy.body}</p></details>
            )}
            <label className="check"><input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
              <span>Li e aceito a política de agendamento, ausência, atraso, cancelamento e reembolso.</span></label>
            {err && <Alert kind="error">{err}</Alert>}
            <button className="btn primary block" disabled={!minutes || !accept || busy || (quote !== null && !quote.available)} onClick={reserve}>
              {busy ? 'Reservando…' : me ? 'Reservar e ir para o pagamento' : 'Entrar para reservar'}
            </button>
            <p className="small dim">A reserva fica provisória por alguns minutos até o pagamento ser confirmado pelo servidor.</p>
          </div>
        </section>

        <section className="card" id="ao-vivo" aria-labelledby="t-live">
          <h2 id="t-live"><Radio size={18} aria-hidden /> Assistir ao vivo</h2>
          <PublicStream channel={g.public_stream} />
          <p className="small dim">Somente espectadores — este player não envia comandos ao console.</p>
        </section>
      </div>

      <section className="card" aria-labelledby="t-disp">
        <h2 id="t-disp"><CalendarClock size={18} aria-hidden /> Disponibilidade e fila</h2>
        <p className="small muted">{g.availability.notice}</p>
        {g.availability.consoles.map((c) => (
          <div key={c.console_id} className="card" style={{ marginTop: 12, background: 'rgba(255,255,255,.02)' }}>
            <div className="spread"><h3 style={{ margin: 0 }}><Gamepad2 size={16} aria-hidden /> {c.console_name}</h3>
              <span className="pill"><ListOrdered size={13} />{c.queue_size} na fila</span></div>
            <ul className="small" style={{ paddingLeft: 18 }}>
              {c.messages.map((m) => <li key={m}>{m.startsWith('Atenção') ? <b><AlertTriangle size={12} /> {m}</b> : m}</li>)}
              {c.packages.map((p) => <li key={p.minutes}>{minutesLabel(p.minutes)}: {p.fits ? `início estimado ${dateTime(p.estimated_start_at)}, término máximo ${time(p.estimated_end_at)}` : 'indisponível nas janelas atuais'}</li>)}
            </ul>
            <QueueList items={c.queue} />
          </div>
        ))}
      </section>
    </div>
  );
}
