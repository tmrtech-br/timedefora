'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { AlertTriangle, CalendarClock, Gamepad2, Heart, ListOrdered, Radio } from 'lucide-react';
import PolicyConsent from '@/components/PolicyConsent';
import PublicStream from '@/components/PublicStream';
import QueueList from '@/components/QueueList';
import ShareStream from '@/components/ShareStream';
import { Alert, ErrorBox, Field, Skeleton } from '@/components/ui';
import { ApiError, del, get, post, put } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useApi } from '@/lib/hooks';
import { dateTime, minutesLabel, moneyWithCents, time } from '@/lib/format';
import type { GameCard as G, QueueItem, Reservation } from '@/lib/types';
import { useFeatures } from '@/lib/features';

type ConsoleAvail = { console_id: string; console_name: string; messages: string[]; queue_size: number; playing_now: string | null;
  current_window: { starts_at: string; ends_at: string; remaining_minutes: number } | null; next_window: { starts_at: string } | null;
  last_free_minutes?: number; queue_max_minutes?: number; packages: { minutes: number; price_cents: number; fits: boolean; estimated_start_at: string | null; estimated_end_at: string | null }[];
  queue: QueueItem[] };
type Detail = G & { rate_cents_per_minute: number; description: string; age_rating: string | null; requirements: string; min_minutes: number; max_minutes: number;
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
  const [endLocal, setEndLocal] = useState('');
  const [startLocal, setStartLocal] = useState('');
  const [coupon, setCoupon] = useState('');
  const features = useFeatures();
  useEffect(() => {
    if (!features) return;
    if (mode === 'queue' && !features.queue_mode_enabled && features.scheduled_mode_enabled) setMode('scheduled');
    if (mode === 'scheduled' && !features.scheduled_mode_enabled && features.queue_mode_enabled) setMode('queue');
  }, [features, mode]);
  const [showPolicy, setShowPolicy] = useState(false);
  const [quoteResult, setQuote] = useState<{ key: string; value: Quote } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [fav, setFav] = useState(false);
  useEffect(() => { if (g) setFav(g.is_favorite); }, [g]);
  const scheduledMinutes = startLocal && endLocal
    ? (Date.parse(endLocal + ':00-03:00') - Date.parse(startLocal + ':00-03:00')) / 60000 : 0;
  const maximum = Math.max(0, ...(g?.availability.consoles.map((c) => c.queue_max_minutes || 0) ?? []));
  const packageMinutes = [...new Set(g?.availability.consoles.flatMap((c) => c.packages.filter((p) => p.fits).map((p) => p.minutes)) ?? [])].sort((a, b) => a - b);
  const byMinute = Boolean(g?.rate_cents_per_minute && maximum);
  const sliderMax = byMinute ? maximum : packageMinutes.length;
  const sliderValue = Math.min(minutes ?? 1, sliderMax);
  const selectedMinutes = mode === 'queue' ? (byMinute ? sliderValue : packageMinutes[sliderValue - 1] ?? 0) : scheduledMinutes;
  const quoteKey = Number.isSafeInteger(selectedMinutes) && selectedMinutes > 0
    ? new URLSearchParams({ minutes: String(selectedMinutes), mode, ...(mode === 'scheduled' ? { start_at: startLocal + ':00-03:00' } : {}) }).toString() : '';
  useEffect(() => {
    if (!quoteKey) return;
    let active = true;
    const timer = window.setTimeout(() => {
      get<Quote>(`/catalog/games/${slug}/quote?${quoteKey}`).then((value) => {
        if (active) setQuote({ key: quoteKey, value });
      }).catch(() => {
        if (active) setQuote({ key: quoteKey, value: { available: false, message: 'Não foi possível calcular a cotação.' } });
      });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [quoteKey, slug]);
  const quote = quoteResult?.key === quoteKey ? quoteResult?.value : undefined;


  async function reserve() {
    if (!me) return router.push(`/entrar?proximo=/jogos/${slug}`);
    if (!me.email_verified) return router.push('/verificar-email');
    setBusy(true); setErr('');
    try {
      const body: Record<string, unknown> = { game_id: g!.id, minutes: selectedMinutes, mode, accept_policy: true, coupon_code: coupon || null };
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
  const total = quote?.available ? quote.price_cents : byMinute && selectedMinutes > 0
    ? g.rate_cents_per_minute * selectedMinutes : undefined;
  const previousStart = quote?.starts_at ?? (mode === 'queue' && quoteResult?.key.includes('mode=queue') ? quoteResult.value.starts_at : undefined);
  const previewEnd = previousStart && selectedMinutes > 0
    ? new Date(Date.parse(previousStart) + selectedMinutes * 60000).toISOString() : undefined;
  const rate = total !== undefined && selectedMinutes > 0 ? total / selectedMinutes : undefined;
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
          <div className="row" style={{ margin: '14px 0' }} role="radiogroup" aria-label="Tipo de reserva">
            {features?.queue_mode_enabled !== false && <label className="check"><input type="radio" checked={mode === 'queue'} onChange={() => setMode('queue')} /><span><b>Selecionar minutos</b> · início estimado pela fila</span></label>}
            {features?.scheduled_mode_enabled !== false && <label className="check"><input type="radio" checked={mode === 'scheduled'} onChange={() => setMode('scheduled')} /><span><b>Digitar início e fim</b></span></label>}
            {features && !features.queue_mode_enabled && !features.scheduled_mode_enabled && <Alert kind="warn">Compras temporariamente indisponíveis.</Alert>}
          </div>
          {mode === 'scheduled' ? <div className="grid2">
            <Field label="Início (Fortaleza)"><input type="datetime-local" step={60} value={startLocal} onChange={(e) => setStartLocal(e.target.value)} /></Field>
            <Field label="Fim (Fortaleza)"><input type="datetime-local" step={60} min={startLocal || undefined} value={endLocal} onChange={(e) => setEndLocal(e.target.value)} /></Field>
          </div> : <div className="stack">
            <label htmlFor="booking-minutes">Duração da reserva</label>
            <input id="booking-minutes" type="range" min={1} max={Math.max(1, sliderMax)} disabled={sliderMax < 2}
              value={sliderValue || 1} onChange={(e) => setMinutes(Number(e.target.value))}
              aria-valuetext={`${selectedMinutes.toLocaleString('pt-BR')} minutos`} style={{ width: '100%', accentColor: 'var(--purple)' }} />
            <div className="spread small muted"><span>{byMinute ? '1 minuto' : minutesLabel(packageMinutes[0])}</span>
              <span>{sliderMax ? `${(byMinute ? maximum : packageMinutes.at(-1))?.toLocaleString('pt-BR')} minutos disponíveis` : 'Nenhuma duração disponível'}</span>
            </div>
          </div>}
          {selectedMinutes > 0 && <div className="card checkout-total" aria-live="polite">
            <div className="spread"><b>{selectedMinutes.toLocaleString('pt-BR')} {selectedMinutes === 1 ? 'minuto' : 'minutos'}</b><strong>{total !== undefined ? moneyWithCents(total) : '—'}</strong></div>
            {rate !== undefined && <span className="small muted">{moneyWithCents(rate)} por minuto</span>}
            {previousStart && previewEnd && (quote?.available || !quote) && <dl className="kv small">
              <dt>{!quote ? 'Início previsto na prévia' : mode === 'queue' ? 'Início estimado' : 'Início'}</dt>
              <dd>{dateTime(previousStart)}</dd>
              <dt>Término</dt><dd>{dateTime(quote?.ends_at ?? previewEnd)}</dd>
              {quote?.console_name && <><dt>Console</dt><dd>{quote.console_name}</dd></>}
            </dl>}
            {quote?.available && <p className="small muted">{quote.estimate_notice}</p>}
          </div>}
          {quote && !quote.available && <p role="status" className="small muted">{quote.message}</p>}
          <div className="stack" style={{ marginTop: 12 }}>
            {features?.coupons_enabled !== false && <Field label="Cupom (opcional)"><input value={coupon} onChange={(e) => setCoupon(e.target.value.toUpperCase())} maxLength={30} /></Field>}
            {err && <Alert kind="error">{err}</Alert>}
            <button className="btn primary block" disabled={busy || !quote?.available} onClick={() => {
              if (!me) return router.push(`/entrar?proximo=/jogos/${slug}%23reservar`);
              if (!me.email_verified) return router.push('/verificar-email');
              if (g.cancellation_policy) setShowPolicy(true);
              else setErr('A política de agendamento está indisponível.');
            }}>
              {busy ? 'Reservando…' : me ? 'Reservar e ir para o pagamento' : 'Entrar para reservar'}
            </button>
            <p className="small dim">A reserva fica provisória por alguns minutos até o pagamento ser confirmado pelo servidor.</p>
            {showPolicy && g.cancellation_policy && <PolicyConsent key={g.cancellation_policy.version}
              policy={g.cancellation_policy} action="Reservar e ir para o pagamento" onClose={() => setShowPolicy(false)}
              onConfirm={() => { setShowPolicy(false); void reserve(); }} />}
          </div>
        </section>

        <section className="card" id="ao-vivo" aria-labelledby="t-live">
          <h2 id="t-live"><Radio size={18} aria-hidden /> Assistir ao vivo</h2>
          <PublicStream channel={g.public_stream} />
          {g.public_stream && <ShareStream title={g.title} live={g.public_stream.status === 'live'} />}
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
              {!byMinute && c.packages.map((p) => <li key={p.minutes}>{minutesLabel(p.minutes)}: {p.fits ? `início estimado ${dateTime(p.estimated_start_at)}, término máximo ${time(p.estimated_end_at)}` : 'indisponível nas janelas atuais'}</li>)}
            </ul>
            <QueueList items={c.queue} />
          </div>
        ))}
      </section>
    </div>
  );
}
