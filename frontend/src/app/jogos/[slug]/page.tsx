'use client';
import Link from 'next/link';
import DateFilter from '@/components/DateFilter';
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
import { useApi, useServerClock } from '@/lib/hooks';
import { dateTime, minutesLabel, moneyWithCents, time } from '@/lib/format';
import type { GameCard as G, QueueItem, Reservation } from '@/lib/types';
import { useFeatures } from '@/lib/features';

type ConsoleAvail = { console_id: string; console_name: string; messages: string[]; queue_size: number; playing_now: string | null;
  current_window: { starts_at: string; ends_at: string; remaining_minutes: number } | null; next_window: { starts_at: string } | null;
  scheduled_windows?: { starts_at: string; ends_at: string }[];
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
  const [minutes, setMinutes] = useState('');
  const [selectedMode, setMode] = useState<'queue' | 'scheduled' | null>(null);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const startLocal = startDate && startTime ? `${startDate}T${startTime}` : '';
  const endLocal = endDate && endTime ? `${endDate}T${endTime}` : '';
  const [coupon, setCoupon] = useState('');
  const features = useFeatures();
  const queueEnabled = features?.queue_mode_enabled !== false;
  const scheduledEnabled = features?.scheduled_mode_enabled !== false;
  const mode = (selectedMode === 'queue' && queueEnabled) || (selectedMode === 'scheduled' && scheduledEnabled)
    ? selectedMode : null;
  const [showPolicy, setShowPolicy] = useState(false);
  const [quoteResult, setQuote] = useState<{ key: string; value: Quote } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [fav, setFav] = useState(false);
  const [failedArt, setFailedArt] = useState<string[]>([]);
  useEffect(() => { if (g) setFav(g.is_favorite); }, [g]);
  const now = useServerClock(g?.availability.server_time);
  const currentMinute = Math.ceil(now() / 60000) * 60000;
  const windows = g?.availability.consoles.flatMap((console) => (console.scheduled_windows ?? []).map((window) => ({
    start: Math.max(currentMinute, Date.parse(window.starts_at)), end: Date.parse(window.ends_at),
  }))).filter(({ start, end }) => end - start >= 60000) ?? [];
  const localInput = (timestamp: number) => new Date(timestamp - 3 * 3600000).toISOString().slice(0, 16);
  const startAt = startLocal ? Date.parse(startLocal + ':00-03:00') : NaN;
  const assignmentEnd = windows.reduce((limit, window) => startAt >= window.start && startAt + 60000 <= window.end
    ? Math.max(limit, window.end) : limit, 0);
  const startParameter = startLocal + ':00-03:00';
  const limitQuery = new URLSearchParams({ mode: 'scheduled', minutes: '1', start_at: startParameter, duration_limit: 'true' });
  const limit = useApi<{ start_at: string; max_minutes: number }>(
    mode === 'scheduled' && assignmentEnd ? `/catalog/games/${slug}/quote?${limitQuery}` : null, 10000);
  const limitReady = limit.data?.start_at === startParameter;
  const latestEnd = assignmentEnd && limitReady && limit.data!.max_minutes
    ? Math.min(assignmentEnd, startAt + limit.data!.max_minutes * 60000) : 0;
  const startWindows = windows.filter(({ start, end }) => localInput(start).slice(0, 10) <= startDate
    && localInput(end - 60000).slice(0, 10) >= startDate);
  const firstTime = startWindows.map(({ start }) => localInput(start)).sort()[0];
  const lastTime = startWindows.map(({ end }) => localInput(end - 60000)).sort().at(-1);
  const earliestEndInput = latestEnd ? localInput(startAt + 60000) : '';
  const latestEndInput = latestEnd ? localInput(latestEnd) : '';
  const scheduledValid = !!latestEnd && endLocal >= earliestEndInput && endLocal <= latestEndInput;
  const scheduledMinutes = startLocal && endLocal
    ? (Date.parse(endLocal + ':00-03:00') - Date.parse(startLocal + ':00-03:00')) / 60000 : 0;
  const maximum = Math.max(0, ...(g?.availability.consoles.map((c) => c.queue_max_minutes || 0) ?? []));
  const packageMinutes = [...new Set(g?.availability.consoles.flatMap((c) => c.packages.filter((p) => p.fits).map((p) => p.minutes)) ?? [])].sort((a, b) => a - b);
  const byMinute = Boolean(g?.rate_cents_per_minute && maximum);
  const enteredMinutes = Number(minutes);
  const queueMinutesValid = Number.isSafeInteger(enteredMinutes) && enteredMinutes > 0
    && (byMinute ? enteredMinutes <= maximum : packageMinutes.includes(enteredMinutes));
  const selectedMinutes = mode === 'queue' ? (queueMinutesValid ? enteredMinutes : 0) : mode === 'scheduled' && scheduledValid ? scheduledMinutes : 0;
  const quoteKey = mode && Number.isSafeInteger(selectedMinutes) && selectedMinutes > 0
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
    if (!mode || !quote?.available) return;
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
  const artwork = [g.cover_url, g.banner_url].find((url) => url && !failedArt.includes(url));
  const banner = g.banner_url && !failedArt.includes(g.banner_url) ? g.banner_url : null;
  return (
    <div className="stack">
      {g.is_demo && <Alert kind="warn">Jogo de demonstração: console e pagamento <b>simulados</b>. Exploração comercial ainda não autorizada.</Alert>}
      <div className="game-top">
      <section className={`game-hero${banner ? ' has-banner' : ''}`}
        style={banner ? { '--game-banner': `url(${JSON.stringify(banner)})` } as React.CSSProperties : undefined}>
        {artwork ? <img src={artwork} alt={`Capa de ${g.title}`} onError={() => setFailedArt((urls) => [...urls, artwork])} />
          : <div className="game-art-placeholder" aria-hidden><Gamepad2 size={36} /></div>}
        <div className="stack">
          <div className="spread"><h1 style={{ margin: 0, fontSize: 32 }}>{g.title}</h1>
            <button className="btn" onClick={toggleFav} aria-pressed={fav}><Heart size={16} fill={fav ? '#c13eff' : 'none'} />{fav ? 'Favorito' : 'Favoritar'}</button></div>
          <div className="row">
            {g.platforms.map((p) => <span key={p.code} className="pill"><Gamepad2 size={13} />{p.name}</span>)}
            {g.genres.map((x) => <span key={x} className="pill purple">{x}</span>)}
            {g.age_rating && <span className="pill amber">Classificação {g.age_rating}</span>}
            <span className={`pill ${g.status === 'available' ? 'green' : g.status === 'unavailable' ? 'red' : 'cyan'}`}>{g.status_label}</span>
          </div>
          {g.description && <p style={{ margin: 0, color: '#ddd7ee' }}>{g.description}</p>}
          {g.requirements && <p className="small muted" style={{ margin: 0 }}>Requisitos de conexão: {g.requirements}</p>}
        </div>
      </section>
      <section className="card game-availability" aria-labelledby="t-disp">
        <h2 id="t-disp"><CalendarClock size={18} aria-hidden /> Disponibilidade e fila</h2>
        <p className="small muted">{g.availability.notice}</p>
        {g.availability.consoles.map((c) => (
          <div key={c.console_id} className="card game-availability-console">
            <div className="spread"><h3 style={{ margin: 0 }}><Gamepad2 size={16} aria-hidden /> {c.console_name}</h3>
              <span className="pill"><ListOrdered size={13} />{c.queue_size} na fila</span></div>
            {c.messages.length > 0 && <ul className="game-availability-notes small">
              {c.messages.map((m) => <li key={m}>{m.startsWith('Atenção') ? <b><AlertTriangle size={12} /> {m}</b> : m}</li>)}
            </ul>}
            {c.queue.length > 0 && <details className="game-queue-details"><summary>Ver fila</summary>
              <QueueList items={c.queue} maxVisible={5} />
            </details>}
          </div>
        ))}
      </section>
      </div>

      <div className="grid2">
        <section className="card" id="reservar" aria-labelledby="t-reservar">
          <h2 id="t-reservar">Escolha seu tempo</h2>
          {g.availability.consoles.length === 0 && <Alert kind="warn">Nenhum console disponível para este jogo no momento.</Alert>}
          {!queueEnabled && !scheduledEnabled && <Alert kind="warn">Compras temporariamente indisponíveis.</Alert>}
          <div className="booking-options" role="radiogroup" aria-label="Tipo de reserva">
            {queueEnabled && <div className="booking-option">
              <label className="check"><input type="radio" name="booking-mode" checked={mode === 'queue'} onChange={() => setMode('queue')} /><span><b>Informar minutos</b><small>Início estimado pela fila</small></span></label>
              <fieldset className="stack booking-fields" disabled={mode !== 'queue'} aria-label="Informar minutos">
                <Field label="Quantidade de minutos"
                  hint={byMinute ? `De 1 a ${maximum.toLocaleString('pt-BR')} minutos.` : undefined}
                  error={mode === 'queue' && minutes && !queueMinutesValid ? 'Informe uma quantidade inteira de minutos disponível.' : undefined}>
                  {byMinute ? <input type="number" inputMode="numeric" min={1} max={maximum} step={1} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
                    : <select disabled={!packageMinutes.length} value={minutes} onChange={(e) => setMinutes(e.target.value)}>
                      <option value="">Escolha uma duração</option>
                      {packageMinutes.map((value) => <option key={value} value={value}>{minutesLabel(value)}</option>)}
                    </select>}
                </Field>
                {mode === 'queue' && !byMinute && !packageMinutes.length && <p className="small muted">Nenhuma duração disponível para entrar na fila.</p>}
              </fieldset>
            </div>}
            {scheduledEnabled && <div className="booking-option">
              <label className="check"><input type="radio" name="booking-mode" checked={mode === 'scheduled'} onChange={() => setMode('scheduled')} /><span><b>Digitar início e fim</b><small>Horário de Brasília</small></span></label>
              <fieldset key={mode === 'scheduled' ? 'scheduled-active' : 'scheduled-inactive'} className="stack booking-fields" disabled={mode !== 'scheduled'} aria-label="Digitar início e fim">
                <div className="booking-dates">
                  <DateFilter label="Data inicial" min={localInput(currentMinute).slice(0, 10)}
                    isDateDisabled={(day) => !windows.some(({ start, end }) => localInput(start).slice(0, 10) <= day
                      && localInput(end - 60000).slice(0, 10) >= day)}
                    value={startDate} onChange={(date) => { setStartDate(date); setEndDate(''); setEndTime(''); }} />
                  <label className="field">Hora inicial<input type="time" step={60} disabled={!startDate} min={firstTime?.startsWith(startDate) ? firstTime.slice(11) : undefined}
                    max={lastTime?.startsWith(startDate) ? lastTime.slice(11) : undefined} value={startTime}
                    onChange={(e) => { setStartTime(e.target.value); setEndDate(''); setEndTime(''); }} /></label>
                  <DateFilter label="Data final" min={earliestEndInput.slice(0, 10)} max={latestEndInput.slice(0, 10)}
                    disabled={!latestEnd} value={endDate} onChange={setEndDate} />
                  <label className="field">Hora final<input type="time" step={60} disabled={!latestEnd || !endDate}
                    min={endDate && earliestEndInput.startsWith(endDate) ? earliestEndInput.slice(11) : undefined}
                    max={endDate && latestEndInput.startsWith(endDate) ? latestEndInput.slice(11) : undefined} value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
                </div>
                {mode === 'scheduled' && startLocal && (!assignmentEnd || (limitReady && !latestEnd)) && <p className="small" role="status" style={{ color: '#ffb366' }}>
                  {firstTime?.startsWith(startDate) && startTime < firstTime.slice(11)
                    ? `Nesse dia o início precisa ser a partir de ${firstTime.slice(11)} (horário de Brasília).`
                    : lastTime?.startsWith(startDate) && startTime > lastTime.slice(11)
                      ? `Nesse dia o último início possível é ${lastTime.slice(11)}.`
                      : 'Esse horário não está livre no console: escolha outro início.'}</p>}
                {mode === 'scheduled' && assignmentEnd > 0 && !limitReady && <p className="small muted" role="status">
                  {limit.error ? 'Não foi possível consultar a disponibilidade.' : 'Consultando o horário disponível…'}
                </p>}
                {mode === 'scheduled' && latestEnd > 0 && endLocal && !scheduledValid && <p className="small muted">Escolha um fim após o início e até {dateTime(new Date(latestEnd).toISOString())}.</p>}
              </fieldset>
            </div>}
          </div>
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

    </div>
  );
}
