'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, CalendarClock, Check, CircleDollarSign, ClipboardCheck, FlaskConical, Gamepad2, Headphones, LockKeyhole, Radio, ScanSearch, UserRoundCheck } from 'lucide-react';
import { ErrorBox, Field, Loading } from '@/components/ui';
import { toast } from '@/components/Toaster';
import { get, patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';
import { useAction } from '@/components/admin/common';
import OwnerReviewPanel from '@/components/OwnerReviewPanel';
import LaunchScripts from '@/components/LaunchScripts';
import OwnerConnection from './OwnerConnection';
import OwnerPsn from './OwnerPsn';
import OwnerGames, { OwnerPrice, type GameWindow } from './OwnerGames';
import OwnerHours from './OwnerHours';
import { DraftFieldsContext, useDraftValue, type RegistrationDraft } from './registrationDraft';
import type { OwnerConsole, PsnAccount } from './shared';

const STEPS = [
  { title: 'Dados do console', icon: Gamepad2 },
  { title: 'Conexão e transmissão', icon: Radio },
  { title: 'Configurações de uso', icon: UserRoundCheck },
  { title: 'Jogos vinculados', icon: Gamepad2 },
  { title: 'Preço', icon: CircleDollarSign },
  { title: 'Disponibilidade', icon: CalendarClock },
  { title: 'Revisão', icon: ClipboardCheck },
  { title: 'Teste', icon: FlaskConical },
  { title: 'Detectar jogo', icon: ScanSearch },
];
const [DATA, CONNECTION, USE, GAMES, PRICE, AVAILABILITY, REVIEW, TEST, DETECT] = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;
export const EMPTY_CONSOLE = { code: '', name: '', platform_code: 'PS4', model: '', serial_number: '', location: '', description: '' };
type ConsoleFields = typeof EMPTY_CONSOLE;
type Review = { status: string; missing: string[]; tests_validated?: boolean; setup: { connection: boolean; psn: boolean; games: boolean; price: boolean; availability: boolean } };

export function RegistrationSummary({ console: c, accounts }: { console: OwnerConsole; accounts: PsnAccount[] | null }) {
  const base = `/owner/consoles/${c.id}`;
  type Settings = { method?: string; network_route?: string; resolution?: string; fps?: number; bitrate_kbps?: number; console_identifier?: string };
  const connection = useApi<{ current: Settings | null; pending: Settings | null }>(base + '/connection-settings');
  const games = useApi<{ assignments: GameWindow[] }>(base + '/games');
  const hours = useApi<{ hours: { weekday: number; opens_at: string; closes_at: string }[]; pending: { weekday: number; opens_at: string; closes_at: string }[] | null }>(base + '/hours');
  const rate = useApi<{ rate_cents: number; rate_unit: string; min_minutes: number; max_minutes: number }>(base + '/availability');
  const reviewed = c.pending?.rate ?? rate.data;
  const settings = connection.data?.pending ?? connection.data?.current;
  const times = hours.data?.pending ?? hours.data?.hours;
  const account = accounts?.find((item) => item.id === (c.owner_requested_psn_account_id ?? c.psn_account_id));
  const days = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
  return <div className="owner-registration-summary">
    <section><h3>Dados do console</h3><p><strong>{c.name}</strong> · {c.platform_code} · {c.code}</p>
      {[c.model, c.serial_number, c.location].filter(Boolean).length > 0 && <p>{[c.model, c.serial_number, c.location].filter(Boolean).join(' · ')}</p>}
      {c.description && <p>{c.description}</p>}</section>
    <section><h3>Conexão e uso</h3>
      <p>{settings && settings.method !== 'unconfigured' ? [
        settings.network_route === 'internet_psn' ? 'Remote Play (PSN)' : settings.method,
        settings.console_identifier, settings.resolution, settings.fps && `${settings.fps} fps`, settings.bitrate_kbps && `${settings.bitrate_kbps} kbps`,
      ].filter(Boolean).join(' · ') : 'Conexão não configurada'}</p>
      {['PS4', 'PS5'].includes(c.platform_code) && <p>{account ? `${account.label} · ${account.status === 'linked' ? 'PSN conectada' : 'Login PSN pendente'}` : 'Conta PSN não vinculada'}</p>}</section>
    <section><h3>Jogos e preço</h3>
      {games.data?.assignments?.length ? <ul>{games.data.assignments.map((item) => <li key={item.id}>{item.title} · {dateTime(item.starts_at)} – {dateTime(item.ends_at)}</li>)}</ul> : <p>Nenhum período vinculado.</p>}
      {reviewed && <p>{money(reviewed.rate_cents)} por {reviewed.rate_unit === 'hour' ? 'hora' : 'minuto'} · {reviewed.min_minutes}–{reviewed.max_minutes} min</p>}</section>
    <section><h3>Disponibilidade</h3>
      {times?.length ? <ul>{times.map((item) => <li key={`${item.weekday}-${item.opens_at}`}>{days[item.weekday]} · {item.opens_at}–{item.closes_at}</li>)}</ul> : <p>Vale o período de cada jogo.</p>}</section>
  </div>;
}

function ConsoleForm({ console: c, onSave }: { console?: OwnerConsole; onSave: (data: ConsoleFields) => Promise<void> }) {
  const [form, setForm] = useDraftValue<ConsoleFields>('console', c ? {
    code: c.code, name: c.name, platform_code: c.platform_code, model: c.model ?? '', serial_number: c.serial_number ?? '',
    location: c.location ?? '', description: c.description ?? '',
  } : EMPTY_CONSOLE);
  const { busy, run, msg } = useAction();
  const locked = c?.review_status === 'submitted';
  return <form className="card stack" id="owner-console-form" onSubmit={(event) => {
    event.preventDefault();
    if (!locked) void run(() => onSave(form));
  }}>
    {msg}
    <fieldset className="grid2 owner-registration-fields" disabled={locked || busy}>
      <Field label="Código do console" hint={c ? undefined : 'Use de 3 a 30 letras, números ou hífens.'}>
        <input required pattern="[A-Z0-9\x2D]{3,30}" maxLength={30} value={form.code} readOnly={!!c}
          onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, '') })} />
      </Field>
      <Field label="Nome"><input required minLength={2} maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Plataforma"><select value={form.platform_code} disabled={c?.is_published} onChange={(e) => setForm({ ...form, platform_code: e.target.value })}>
        {c && !['PS4', 'PS5'].includes(c.platform_code) && <option>{c.platform_code}</option>}
        <option value="PS4">PlayStation 4 (PS4)</option><option value="PS5">PlayStation 5 (PS5)</option>
      </select></Field>
      <Field label="Modelo"><input maxLength={120} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
      <Field label="Série / identificador"><input maxLength={120} value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} /></Field>
      <Field label="Localização"><input maxLength={120} value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></Field>
    </fieldset>
    <Field label="Descrição / observações"><textarea disabled={locked || busy} maxLength={500} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
    {locked && <p className="small muted">Cancele o envio na aba Revisão para editar os dados.</p>}
    {c && form.platform_code !== c.platform_code && <p className="small muted">A troca de plataforma exige configurar e testar a conexão novamente.</p>}
    <div><button className="btn primary" disabled={locked || busy}>Salvar e continuar <ArrowRight size={16} aria-hidden /></button></div>
  </form>;
}

function availableStep(review?: Review | null) {
  if (!review) return DATA;
  if (['approved', 'submitted', 'rejected'].includes(review.status)) return REVIEW;
  const setup = review.setup;
  if (!setup?.connection) return CONNECTION;
  if (!setup.psn) return USE;
  if (!setup.games) return GAMES;
  if (!setup.price) return PRICE;
  return setup.availability ? REVIEW : AVAILABILITY;
}

export default function OwnerRegistration({ initial, records, accounts, draft, draftKey, startAt, reload, reloadAccounts, onSave, onClose, onSupport }: {
  initial?: OwnerConsole; records: OwnerConsole[] | null; accounts: PsnAccount[] | null; draft?: RegistrationDraft;
  draftKey: string; startAt?: number; reload: () => Promise<void>; reloadAccounts: () => Promise<void>;
  onSave: (id: string, draft: RegistrationDraft, migrateFrom?: string) => boolean; onClose: () => void; onSupport: () => void;
}) {
  const [created, setCreated] = useState<OwnerConsole>();
  const id = initial?.id ?? created?.id;
  const current = records?.find((item) => item.id === id) ?? created ?? initial;
  const path = id ? `/owner/consoles/${id}` : null;
  const review = useApi<Review>(path && path + '/review', 8000);
  const fields = useRef({ ...draft?.fields }).current;
  const [step, setStep] = useState<number>();
  const [visited, setVisited] = useState(draft?.furthest ?? 0);
  const [advancing, setAdvancing] = useState(false);
  const tabsRef = useRef<HTMLElement>(null);
  const allowedFromServer = availableStep(review.data);
  const canTest = review.data?.status === 'approved';
  const max = Math.min(REVIEW, Math.max(visited, allowedFromServer));
  const defaultStep = review.data?.status === 'submitted' || review.data?.status === 'rejected' ? REVIEW
    : canTest && (draft?.step ?? REVIEW) >= REVIEW ? TEST : draft?.step ?? allowedFromServer;
  const index = Math.min(step ?? startAt ?? defaultStep, canTest ? DETECT : max);
  const config = STEPS[index];
  const EditorIcon = config.icon;
  const pending = current?.review_status === 'submitted';
  useEffect(() => {
    if (step == null && (!id || review.data)) setStep(index);
  }, [step, id, review.data, index]);
  useEffect(() => {
    const tabs = tabsRef.current;
    const selected = tabs?.querySelector('[aria-current="step"]');
    if (!tabs || !selected) return;
    const viewport = tabs.getBoundingClientRect();
    const item = selected.getBoundingClientRect();
    if (item.left < viewport.left) tabs.scrollLeft += item.left - viewport.left;
    if (item.right > viewport.right) tabs.scrollLeft += item.right - viewport.right;
  }, [index]);

  function persist(next = index, furthest = max, consoleId = id ?? draftKey, migrateFrom?: string) {
    return onSave(consoleId, { version: 2, step: next, furthest, fields: { ...fields } }, migrateFrom);
  }
  function move(next: number, furthest = max) {
    setStep(next);
    setVisited(furthest);
    persist(next, furthest);
  }
  function advance() { move(index + 1, Math.max(max, index + 1)); void refresh(); }
  function saveDraft() {
    if (persist()) toast('ok', 'Rascunho salvo neste navegador.');
  }
  async function refresh() { await Promise.all([review.reload(), reload(), reloadAccounts()]); }
  async function saveConsole(data: ConsoleFields) {
    if (id) {
      const { code, platform_code, ...details } = data;
      const changed = Object.fromEntries(Object.entries(details).filter(([key, value]) => value !== (current?.[key as keyof OwnerConsole] ?? '')));
      if (platform_code !== current?.platform_code) changed.platform_code = platform_code;
      if (Object.keys(changed).length) await patch(path!, changed);
      if (platform_code !== current?.platform_code) {
        delete fields.connection;
        move(1, 1);
      } else advance();
      await refresh();
    } else {
      const result = await post<OwnerConsole>('/owner/consoles', { ...data, serial_number: data.serial_number || null });
      setCreated({ ...data, ...result });
      setStep(1); setVisited(1);
      persist(1, 1, result.id, draftKey);
      await reload();
    }
  }
  async function validateAndAdvance() {
    if (!id || advancing) return;
    setAdvancing(true);
    try {
      const state = await get<Review>(`${path}/review`);
      const ready = index === USE ? state.setup?.psn : index === GAMES ? state.setup?.games : state.setup?.price;
      if (ready) advance();
      else toast('error', index === USE ? 'Vincule a conta PSN e conclua o login Sony para continuar.'
        : index === GAMES ? 'Vincule pelo menos um jogo a um período para continuar.' : 'Salve o preço antes de continuar.');
    } catch (error) {
      toast('error', error instanceof Error ? error.message : 'Não foi possível conferir a etapa.');
    } finally { setAdvancing(false); }
  }

  const shownSteps = canTest ? STEPS : STEPS.slice(0, TEST);   // Teste e Detectar jogo só depois da aprovação
  function navigation(vertical: boolean) {
    return <nav ref={vertical ? undefined : tabsRef} className={vertical ? 'owner-wizard-rail' : 'owner-wizard-tabs'} aria-label={vertical ? 'Etapas do cadastro' : 'Progresso do cadastro'}>
      {shownSteps.map(({ title }, position) => {
        const allowed = position <= max || (position >= TEST && canTest);
        const done = (position < max || position === REVIEW && (pending || canTest) || position === TEST && !!review.data?.tests_validated)
          && position !== index;
        return <button key={title} type="button" disabled={!allowed} aria-current={position === index ? 'step' : undefined}
          className={done ? 'done' : undefined} onClick={() => move(position)}>
          <span className="owner-wizard-number">{done ? <Check size={17} aria-hidden /> : !allowed ? <LockKeyhole size={16} aria-hidden /> : position + 1}</span>
          {title}
        </button>;
      })}
    </nav>;
  }
  const picker = { consoles: current ? [current] : [], selected: id ?? '', setSelected: () => {} };
  return <DraftFieldsContext.Provider value={fields}>
    <section className="owner-wizard stack" aria-labelledby="owner-wizard-title">
      <div className="spread">
        <button className="owner-wizard-back" onClick={onClose}><ArrowLeft size={16} aria-hidden /> Cadastros</button>
        <button className="btn" onClick={onSupport}><Headphones size={18} aria-hidden /> Suporte</button>
      </div>
      <header className="owner-wizard-heading"><span><Gamepad2 size={29} aria-hidden /></span><div>
        <h2 id="owner-wizard-title">Cadastro de console</h2><p>{current?.name ?? 'Novo cadastro'}</p>
      </div></header>
      {navigation(false)}
      <progress className="owner-wizard-progress" value={index + 1} max={shownSteps.length} aria-label="Etapa do cadastro" />
      <div className="owner-wizard-surface">
        {navigation(true)}
        <div className="owner-wizard-content stack">
          <header className="owner-wizard-step-heading"><EditorIcon size={28} aria-hidden /><h3>{index + 1}. {config.title}</h3></header>
          {review.error && <ErrorBox error={review.error} onRetry={review.reload} />}
          {id && review.loading && step == null ? <Loading /> : <>
            {index === DATA && <ConsoleForm console={current} onSave={saveConsole} />}
            {current && index === CONNECTION && <OwnerConnection console={current} wizard onSaved={advance} />}
            {current && index === USE && (['PS4', 'PS5'].includes(current.platform_code)
              ? <OwnerPsn {...picker} wizard accounts={accounts} reloadAccounts={refresh} reloadConsoles={refresh} onSaveDraft={saveDraft} />
              : <p className="small muted">Esta plataforma não usa conta PSN.</p>)}
            {current && index === GAMES && <OwnerGames {...picker} wizard onReviewChange={refresh} onSaveDraft={saveDraft} />}
            {current && index === PRICE && <OwnerPrice console={current} onReviewChange={refresh} />}
            {current && index === AVAILABILITY && <OwnerHours {...picker} wizard onReviewChange={refresh} onAdvance={advance} />}
            {current && index === REVIEW && <><RegistrationSummary console={current} accounts={accounts} />
              <OwnerReviewPanel consoleId={current.id} phase="review" onChange={refresh} /></>}
            {current && index === TEST && canTest && <OwnerReviewPanel consoleId={current.id} phase="test" onChange={refresh} />}
            {current && index === DETECT && canTest && <>
              <p className="small muted" style={{ margin: 0 }}>Reconheça cada jogo vinculado: o sistema abre o jogo no seu console, confirma o código pelo próprio
                console e tira um print que vai para a equipe conferir. A publicação só é liberada com todos os jogos reconhecidos.</p>
              <LaunchScripts base={`/owner/consoles/${current.id}`} />
              <OwnerReviewPanel consoleId={current.id} phase="publish" onChange={refresh}
                onPublished={() => { toast('ok', 'Console publicado para aluguel.'); onClose(); }} /></>}
          </>}
          <footer className="spread owner-wizard-footer">
            <button type="button" className="btn" onClick={() => index > 0 ? move(index - 1) : onClose()}><ArrowLeft size={16} aria-hidden /> Voltar</button>
            <div className="row">
              <button type="button" className="btn" onClick={saveDraft}>Salvar rascunho</button>
              {(index === USE || index === GAMES || index === PRICE) && <button type="button" className="btn primary" disabled={advancing} onClick={() => void validateAndAdvance()}>Avançar <ArrowRight size={16} aria-hidden /></button>}
              {((index === CONNECTION || index === AVAILABILITY) && pending && max > index || (index === REVIEW || index === TEST) && canTest) &&
                <button type="button" className="btn primary" onClick={() => move(index + 1)}>Avançar <ArrowRight size={16} aria-hidden /></button>}
            </div>
          </footer>
        </div>
      </div>
    </section>
  </DraftFieldsContext.Provider>;
}
