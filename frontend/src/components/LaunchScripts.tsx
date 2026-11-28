'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Camera, FlaskConical, Plus, Save, Trash2, Wand2, X } from 'lucide-react';
import { Alert, ErrorBox, Field, Loading, ModalShell, StatusPill } from '@/components/ui';
import { del, get, post, put } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { useAction } from '@/components/admin/common';

type RefImage = { png: string; width: number };
type GameScript = { game_id: string; title: string; slug: string; steps: string[]; images: Record<string, RefImage>; updated_at: string | null;
  title_id: string | null; title_name: string | null; settle_seconds: number | null; evidence_png: string | null; detected_at: string | null };
type ScriptList = { console: { id: string; name: string; platform_code: string }; games: GameScript[]; agent_ready: boolean; buttons: string[] };
type AgentResult = { ok: boolean; message: string; state: string | null; data: Record<string, unknown> };

const BUTTON_LABEL: Record<string, string> = {
  cross: '✕ (X)', circle: '○ (Bola)', square: '□ (Quadrado)', triangle: '△ (Triângulo)', ps: 'PS', options: 'Options', share: 'Share',
  touchpad: 'Touchpad', l1: 'L1', r1: 'R1', l2: 'L2', r2: 'R2', l3: 'L3', r3: 'R3',
  dpad_up: '↑ Cima', dpad_down: '↓ Baixo', dpad_left: '← Esquerda', dpad_right: '→ Direita',
};
const BUTTONS = Object.keys(BUTTON_LABEL);

/** Um passo do roteiro em campos editáveis (o servidor e o agente usam o texto "tipo:valor:…"). */
type Kind = 'boot' | 'wait_app' | 'press' | 'wait' | 'hold' | 'wait_text' | 'wait_image' | 'press_until_text' | 'press_until_image' | 'press_if_text' | 'press_if_image';
type Step = { kind: Kind; button: string; seconds: string; max: string; target: string };
const KINDS: { kind: Kind; label: string; help: string }[] = [
  { kind: 'wait_app', label: 'Confirmar jogo aberto pelo sistema (rede local)', help: 'O console informa o jogo aberto: código CUSA ou nome. Mais confiável que imagem; se não confirmar no prazo, a preparação falha.' },
  { kind: 'press', label: 'Apertar botão', help: 'Um toque no botão.' },
  { kind: 'wait', label: 'Esperar', help: 'Pausa fixa, em segundos.' },
  { kind: 'hold', label: 'Segurar botão', help: 'Mantém o botão apertado pelos segundos informados.' },
  { kind: 'press_if_image', label: 'Apertar se o elemento aparecer', help: 'Ex.: tela "Seja bem-vindo" ou seleção de usuário: só aperta se o recorte estiver na tela.' },
  { kind: 'press_until_image', label: 'Apertar até o elemento aparecer', help: 'Navega (ex.: → Direita) até o ícone do jogo, selecionado, aparecer na tela.' },
  { kind: 'wait_image', label: 'Esperar o elemento aparecer', help: 'Confirma que está no jogo certo (logo ou menu do jogo). Se não aparecer no prazo, a preparação falha.' },
  { kind: 'press_if_text', label: 'Apertar se o texto aparecer (OCR)', help: 'Leitura de texto: menos confiável que o elemento; use só como apoio.' },
  { kind: 'press_until_text', label: 'Apertar até o texto aparecer (OCR)', help: 'Leitura de texto: menos confiável que o elemento; use só como apoio.' },
  { kind: 'wait_text', label: 'Esperar o texto aparecer (OCR)', help: 'Leitura de texto: menos confiável que o elemento; use só como apoio.' },
];
/** Recortes que o modelo PS4 usa (o proprietário captura cada um na tela do console). */
const TEMPLATE_IMAGES: [string, string][] = [
  ['boas-vindas', 'tela "Seja bem-vindo" / seleção de usuário (ex.: o seu avatar)'],
  ['icone-jogo', 'ícone do jogo selecionado na tela inicial, incluindo o nome que só aparece quando ele está selecionado'],
  ['jogo-aberto', 'logo ou menu do jogo já aberto'],
];

function parse(raw: string): Step {
  const parts = raw.split(':');
  const base: Step = { kind: 'press', button: 'cross', seconds: '2', max: '15', target: '' };
  const head = parts[0];
  if (head === 'boot') return { ...base, kind: 'boot', target: parts.slice(1).join(':') };
  if (head === 'wait_app') return { ...base, kind: 'wait_app', seconds: parts[1] ?? '90', target: parts.slice(2).join(':') };
  if (head === 'wait') return { ...base, kind: 'wait', seconds: parts[1] ?? '2' };
  if (head === 'hold') return { ...base, kind: 'hold', button: parts[1] ?? 'cross', seconds: parts[2] ?? '1' };
  if (head === 'wait_text' || head === 'wait_image') return { ...base, kind: head, seconds: parts[1] ?? '30', target: parts.slice(2).join(':') };
  if (head === 'press_until_text' || head === 'press_until_image')
    return { ...base, kind: head, button: parts[1] ?? 'dpad_right', max: parts[2] ?? '15', target: parts.slice(3).join(':') };
  if (head === 'press_if_text' || head === 'press_if_image') return { ...base, kind: head, button: parts[1] ?? 'cross', target: parts.slice(2).join(':') };
  return { ...base, button: head };
}

function format(s: Step): string {
  switch (s.kind) {
    case 'boot': return `boot:${s.target.trim().toUpperCase()}`;
    case 'wait_app': return `wait_app:${s.seconds}:${s.target}`;
    case 'press': return s.button;
    case 'wait': return `wait:${s.seconds}`;
    case 'hold': return `hold:${s.button}:${s.seconds}`;
    case 'wait_text': case 'wait_image': return `${s.kind}:${s.seconds}:${s.target}`;
    case 'press_until_text': case 'press_until_image': return `${s.kind}:${s.button}:${s.max}:${s.target}`;
    default: return `${s.kind}:${s.button}:${s.target}`;
  }
}

/** Modelo para PS4 por elementos: passa da tela de boas-vindas/usuário, vai ao início, navega até o ícone do jogo e confirma. */
function ps4Template(): string[] {
  return ['ps', 'wait:4', 'press_if_image:cross:boas-vindas', 'wait:5', 'ps', 'wait:3',
    'press_until_image:dpad_right:20:icone-jogo', 'cross', 'wait_image:90:jogo-aberto'];
}

type Shot = { png: string; width: number; height: number; text: string[]; ocr_error: string | null;
  running_app?: { title_id: string; name: string } | null };

function SnapshotCropper({ shot, onCancel, onSave, onUseText }: {
  shot: Shot;
  onCancel: () => void; onSave: (name: string, image: RefImage) => void; onUseText: (text: string) => void;
}) {
  const img = useRef<HTMLImageElement>(null);
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [name, setName] = useState('');
  const point = (e: React.PointerEvent) => {
    const r = img.current!.getBoundingClientRect();
    return { x: Math.max(0, Math.min(r.width, e.clientX - r.left)), y: Math.max(0, Math.min(r.height, e.clientY - r.top)) };
  };
  function crop() {
    const el = img.current;
    if (!el || !box || box.w < 6 || box.h < 6) return;
    const k = el.naturalWidth / el.getBoundingClientRect().width;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(box.w * k); canvas.height = Math.round(box.h * k);
    canvas.getContext('2d')!.drawImage(el, box.x * k, box.y * k, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
    onSave(name, { png: canvas.toDataURL('image/png').split(',')[1], width: el.naturalWidth });
  }
  return <div className="card stack launch-snapshot">
    <div className="spread"><strong>Tela atual do console</strong><button className="btn sm" onClick={onCancel}><X size={15} aria-hidden /> Fechar</button></div>
    <p className="small muted" style={{ margin: 0 }}>Arraste sobre a imagem para recortar um elemento que identifica a tela (logo do jogo, menu, ícone).
      Prefira algo que não muda entre uma abertura e outra.</p>
    <div className="launch-snapshot-frame"
      onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture?.(e.pointerId); start.current = point(e); setBox(null); }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const p = point(e), s = start.current;
        setBox({ x: Math.min(s.x, p.x), y: Math.min(s.y, p.y), w: Math.abs(p.x - s.x), h: Math.abs(p.y - s.y) });
      }}
      onPointerUp={() => { start.current = null; }}>
      <img ref={img} src={`data:image/png;base64,${shot.png}`} alt="Tela atual do console" draggable={false} />
      {box && <span className="launch-snapshot-box" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} />}
    </div>
    <div className="row">
      <Field label="Nome do recorte"><input value={name} maxLength={40} placeholder="ex.: menu-jogo"
        onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-'))} /></Field>
      <button className="btn primary" disabled={!box || box.w < 6 || box.h < 6 || !/^[a-z0-9][a-z0-9_-]*$/.test(name)} onClick={crop}>Salvar recorte</button>
    </div>
    {shot.running_app !== undefined && <div className="small">
      <strong>Jogo aberto segundo o console: </strong>{shot.running_app === null ? 'não informado (console fora da rede local do agente)'
        : shot.running_app.title_id ? `${shot.running_app.name} (${shot.running_app.title_id})` : 'nenhum (tela inicial)'}</div>}
    <div className="stack small">
      <strong>Textos lidos na tela (OCR, apoio)</strong>
      {shot.ocr_error ? <Alert kind="warn">{shot.ocr_error}</Alert> : shot.text.length === 0 ? <span className="muted">Nenhum texto reconhecido.</span>
        : <div className="row launch-ocr">{shot.text.map((t, i) => <button key={`${t}-${i}`} className="btn sm" title="Adicionar passo que espera este texto"
          onClick={() => onUseText(t)}>{t}</button>)}</div>}
    </div>
  </div>;
}

function Editor({ base, game, buttons, onSaved, onClose }: {
  base: string; game: GameScript; buttons: string[]; onSaved: () => Promise<void>; onClose: () => void;
}) {
  const [steps, setSteps] = useState<Step[]>(() => game.steps.map(parse));
  const [images, setImages] = useState<Record<string, RefImage>>(game.images);
  const [raw, setRaw] = useState<string | null>(null);
  const [shot, setShot] = useState<Shot>();

  const [test, setTest] = useState<AgentResult>();
  const { busy, msg, run } = useAction();
  const list = raw !== null ? raw.split('\n').map((l) => l.trim()).filter(Boolean) : steps.map(format);
  const knownButtons = buttons.length ? buttons : BUTTONS;
  const polling = test?.state === 'connecting';
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => {
      get<AgentResult>(`${base}/launch-test`).then(setTest).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [polling, base]);

  const update = (i: number, patch: Partial<Step>) => setSteps((all) => all.map((s, j) => j === i ? { ...s, ...patch } : s));
  const move = (i: number, d: number) => setSteps((all) => {
    const next = [...all]; const [item] = next.splice(i, 1); next.splice(i + d, 0, item); return next;
  });
  const applyRaw = () => { if (raw !== null) { setSteps(list.map(parse)); setRaw(null); } };
  const body = () => ({ steps: list, images });

  return <div className="card stack launch-editor">
    <div className="spread"><h3 style={{ margin: 0 }}>Roteiro avançado de “{game.title}”</h3>
      <button className="btn sm" onClick={onClose}><X size={15} aria-hidden /> Fechar</button></div>
    {msg}
    <p className="small muted" style={{ margin: 0 }}>Só para jogos com abertura especial. Com o jogo reconhecido, o sistema abre e confirma o jogo
      sozinho e este roteiro não é usado. Sem o jogo reconhecido, o agente executa estes passos em ordem; use os de <b>elemento</b>
      (recortes da tela) para conferir onde está.</p>
    <div className="row">
      <button className="btn sm" onClick={() => { setRaw(null); setSteps(ps4Template().map(parse)); }}><Wand2 size={15} aria-hidden /> Usar modelo por elementos</button>
      <button className="btn sm" onClick={() => raw === null ? setRaw(steps.map(format).join('\n')) : applyRaw()}>
        {raw === null ? 'Editar como texto' : 'Voltar aos campos'}</button>
    </div>
    {(() => {
      const needed = TEMPLATE_IMAGES.filter(([n]) => list.some((s) => s.endsWith(`:${n}`)) && !images[n]);
      return needed.length > 0 && <Alert kind="warn"><div>Capture estes elementos na tela do console (botão “Capturar tela do console”) com o nome indicado:
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{needed.map(([n, d]) => <li key={n}><b>{n}</b> — {d}</li>)}</ul></div></Alert>;
    })()}
    {raw !== null ? <Field label="Passos (um por linha)" hint="Formatos: cross · wait:3 · hold:ps:2 · wait_text:30:Texto · press_until_text:dpad_right:20:Nome do jogo · press_if_text:cross:Seja bem-vindo · wait_image:60:recorte">
      <textarea rows={Math.max(8, list.length + 2)} value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} />
    </Field> : <ol className="launch-steps">
      {steps.map((s, i) => {
        const info = KINDS.find((k) => k.kind === s.kind)!;
        const usesButton = !['wait', 'wait_text', 'wait_image', 'boot', 'wait_app'].includes(s.kind);
        const isImage = s.kind.endsWith('_image');
        const isText = s.kind.endsWith('_text');
        return <li key={i} className="launch-step">
          <div className="launch-step-fields">
            <select aria-label={`Tipo do passo ${i + 1}`} value={s.kind} onChange={(e) => update(i, { kind: e.target.value as Kind })}>
              {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
            {s.kind === 'boot' && <input aria-label="Código do jogo" placeholder="CUSA05904" value={s.target} maxLength={9}
              onChange={(e) => update(i, { target: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '') })} />}
            {s.kind === 'wait_app' && <input aria-label="Código ou nome do jogo" placeholder="CUSA05904 ou nome do jogo" value={s.target} maxLength={80}
              onChange={(e) => update(i, { target: e.target.value })} />}
            {usesButton && <select aria-label="Botão" value={s.button} onChange={(e) => update(i, { button: e.target.value })}>
              {knownButtons.map((b) => <option key={b} value={b}>{BUTTON_LABEL[b] ?? b}</option>)}</select>}
            {['wait', 'hold', 'wait_text', 'wait_image', 'wait_app'].includes(s.kind) && <label className="launch-inline">
              <input type="number" min={0.5} max={180} step={0.5} value={s.seconds} onChange={(e) => update(i, { seconds: e.target.value })} /> s</label>}
            {s.kind.startsWith('press_until') && <label className="launch-inline">até
              <input type="number" min={1} max={60} value={s.max} onChange={(e) => update(i, { max: e.target.value })} /> toques</label>}
            {isText && <input aria-label="Texto na tela" placeholder="Texto que aparece na tela" value={s.target} maxLength={80}
              onChange={(e) => update(i, { target: e.target.value.replace(/\n/g, ' ') })} />}
            {isImage && <select aria-label="Imagem de referência" value={s.target} onChange={(e) => update(i, { target: e.target.value })}>
              <option value="">Escolha o recorte</option>
              {Object.keys(images).map((n) => <option key={n} value={n}>{n}</option>)}</select>}
          </div>
          <div className="row launch-step-actions">
            <button className="btn sm" aria-label="Subir passo" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} aria-hidden /></button>
            <button className="btn sm" aria-label="Descer passo" disabled={i === steps.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} aria-hidden /></button>
            <button className="btn sm danger" aria-label="Remover passo" onClick={() => setSteps((all) => all.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden /></button>
          </div>
          <small className="muted">{info.help}</small>
        </li>;
      })}
      <li><button className="btn sm" onClick={() => setSteps((all) => [...all, parse('cross')])}><Plus size={15} aria-hidden /> Adicionar passo</button></li>
    </ol>}

    <div className="stack">
      <div className="spread"><strong>Elementos da tela (recortes)</strong>
        <button className="btn sm" disabled={busy} onClick={() => void run(async () => {
          const r = await post<AgentResult>(`${base}/screen`);
          if (!r.ok) throw new Error(r.message);
          setShot(r.data as Shot);

        })}><Camera size={15} aria-hidden /> Capturar tela do console</button></div>
      {Object.keys(images).length === 0 ? <p className="small muted" style={{ margin: 0 }}>Nenhuma. Abra o jogo no console, capture a tela e recorte um elemento do jogo para confirmar que ele abriu.</p>
        : <div className="launch-images">{Object.entries(images).map(([n, im]) => <figure key={n}>
          <img src={`data:image/png;base64,${im.png}`} alt={`Recorte ${n}`} />
          <figcaption>{n} <button className="btn sm danger" aria-label={`Remover ${n}`} onClick={() => setImages((all) => {
            const next = { ...all }; delete next[n]; return next;
          })}><Trash2 size={13} aria-hidden /></button></figcaption></figure>)}</div>}
      {shot && <SnapshotCropper shot={shot} onCancel={() => setShot(undefined)}
        onUseText={(t) => { applyRaw(); setSteps((all) => [...all, { ...parse('cross'), kind: 'wait_text', seconds: '30', target: t }]); }}
        onSave={(n, im) => { setImages((all) => ({ ...all, [n]: im })); setShot(undefined); }} />}
    </div>

    {test && <Alert kind={test.ok ? 'ok' : polling ? 'info' : 'error'}>{test.message}</Alert>}
    <div className="row">
      <button className="btn primary" disabled={busy} onClick={() => void run(async () => {
        await put(`${base}/launch-scripts/${game.game_id}`, body()); await onSaved();
      }, 'Roteiro salvo. Ele será usado nas próximas preparações deste console.')}><Save size={16} aria-hidden /> Salvar roteiro</button>
      <button className="btn" disabled={busy || polling || list.length === 0} onClick={() => void run(async () => {
        setTest(await post<AgentResult>(`${base}/launch-scripts/${game.game_id}/test`, body()));
      })}><FlaskConical size={16} aria-hidden /> {polling ? 'Testando…' : 'Testar no console'}</button>
      {game.steps.length > 0 && <button className="btn danger" disabled={busy} onClick={() => void run(async () => {
        await del(`${base}/launch-scripts/${game.game_id}`); await onSaved(); onClose();
      }, 'Roteiro excluído.')}>Excluir roteiro</button>}
    </div>
  </div>;
}

/** Abertura automática de um jogo: reconhecer o código do jogo no console, confirmar e testar. */
type Seen = { title_id: string; title_name: string };
type JobData = { title_id?: string; title_name?: string; path?: string; tile?: number; seen?: Seen[]; screenshot?: string; step?: string };
const PATH_LABEL: Record<string, string> = { 'perfil+menu': 'tela de boas-vindas → perfil → menu → jogo', menu: 'menu do console → jogo',
  'já aberto': 'o jogo já estava aberto', 'outro jogo fechado': 'outro jogo estava aberto: fechou e abriu o certo' };

/** Acompanhamento do Reconhecer/Testar: passos ao vivo (como o diagnóstico) e resumo no fim. */
function OpeningProgress({ kind, title, result, log, started, busy, onConfirm, onClose }: {
  kind: 'detect' | 'test'; title: string; result: AgentResult; log: { at: string; text: string }[]; started: number; busy: boolean;
  onConfirm: (g: Seen) => void; onClose: () => void;
}) {
  const running = result.state === 'connecting';
  const d = result.data as JobData;
  const seconds = Math.round((Date.now() - started) / 1000);
  const others = (d.seen ?? []).filter((g) => g.title_id !== d.title_id);
  return <ModalShell title={kind === 'detect' ? `Reconhecer jogo — ${title}` : `Testar abertura — ${title}`}
    closeLabel={running ? 'Fechar (continua no console)' : 'Fechar'} onClose={onClose}>
    <div className="stack">
      {running && <p role="status" className="small"><b>Em andamento.</b> Não mexa no console nem no controle até terminar.</p>}
      <ol className="launch-log">{log.map((l, i) => <li key={i} className={i === log.length - 1 && running ? 'current' : undefined}>
        <span className="muted">{l.at}</span> {l.text}</li>)}</ol>
      {!running && <div className="stack">
        <Alert kind={result.ok ? 'ok' : 'error'}>{result.ok ? 'Concluído.' : 'Não concluído.'} {result.message}</Alert>
        <div className="card stack small"><strong>Resumo</strong>
          <span>Tempo total: {seconds} s</span>
          {d.path && <span>Caminho: {PATH_LABEL[d.path] ?? d.path}{d.tile ? ` (ícone ${d.tile} do menu)` : ''}</span>}
          {d.title_id && <span>Jogo confirmado pelo console: <b>{d.title_name || d.title_id}</b> ({d.title_id})</span>}
          {(d.seen?.length ?? 0) > 0 && <span>Jogos abertos no caminho: {d.seen!.map((g) => `${g.title_name || g.title_id} (${g.title_id})`).join(', ')}</span>}
        </div>
        {d.screenshot && <figure className="launch-evidence"><img src={`data:image/png;base64,${d.screenshot}`} alt="Tela do console com o jogo aberto" />
          <figcaption className="small muted">Print do console — vai junto com o jogo reconhecido para a equipe conferir.</figcaption></figure>}
        {kind === 'detect' && d.title_id && result.ok && <div className="row">
          <span>É este o jogo “{title}”?</span>
          <button className="btn primary sm" disabled={busy} onClick={() => onConfirm({ title_id: d.title_id!, title_name: d.title_name ?? '' })}>Sim, salvar</button>
        </div>}
        {kind === 'detect' && others.length > 0 && <div className="stack small">
          <span className="muted">Outros jogos abertos{result.ok ? '' : ' (nenhum com o nome cadastrado)'} — escolha se um deles é “{title}”:</span>
          {others.map((g) => <div className="row" key={g.title_id}><span>{g.title_name || g.title_id} ({g.title_id})</span>
            <button className="btn sm" disabled={busy} onClick={() => onConfirm(g)}>É este</button></div>)}
        </div>}
      </div>}
    </div>
  </ModalShell>;
}

function GameOpening({ base, game, agentReady, onSaved, onAdvanced }: {
  base: string; game: GameScript; agentReady: boolean; onSaved: () => Promise<void>; onAdvanced: () => void;
}) {
  const [job, setJob] = useState<{ kind: 'detect' | 'test'; result: AgentResult; started: number; log: { at: string; text: string }[] }>();
  const [code, setCode] = useState(game.title_id ?? '');
  const [open, setOpen] = useState(false);
  const { busy, msg, run } = useAction();
  const running = job?.result.state === 'connecting';
  const track = (r: AgentResult) => setJob((j) => {
    if (!j) return j;
    const text = (r.state === 'connecting' ? String((r.data as JobData).step || r.message).replace(/^"[^"]*":\s*/, '') : r.message).trim();
    const last = j.log[j.log.length - 1]?.text;
    const at = new Date().toLocaleTimeString('pt-BR', { timeZone: 'America/Fortaleza' });
    return { ...j, result: r, log: text && text !== last ? [...j.log, { at, text }] : j.log };
  });
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { get<AgentResult>(`${base}/launch-test`).then(track).catch(() => undefined); }, 2000);
    return () => window.clearInterval(timer);
  }, [running, base]);
  const start = (kind: 'detect' | 'test') => run(async () => {
    setOpen(true);
    setJob({ kind, result: { ok: false, message: 'Iniciando…', state: 'connecting', data: {} }, started: Date.now(), log: [] });
    const r = await post<AgentResult>(`${base}/launch-scripts/${game.game_id}/${kind}`, kind === 'test' ? {} : undefined);
    track(r);
  });
  const saveTitle = (g: Seen, fromDetection: boolean) => run(async () => {
    await put(`${base}/launch-scripts/${game.game_id}/title`, { title_id: g.title_id, title_name: g.title_name, from_detection: fromDetection });
    setJob(undefined); await onSaved();
  }, 'Jogo reconhecido. As próximas preparações abrem e confirmam este jogo automaticamente.');

  return <div className="card stack launch-opening">
    <div className="spread"><strong>{game.title}</strong>
      {game.title_id ? <StatusPill status="ok" map={{ ok: `Reconhecido · ${game.title_id}` }} tone="green" />
        : game.steps.length ? <StatusPill status="s" map={{ s: `Roteiro · ${game.steps.length} passos` }} tone="amber" />
        : <StatusPill status="missing" map={{ missing: 'Não reconhecido' }} tone="red" />}</div>
    {msg}
    {game.title_id ? <p className="small muted" style={{ margin: 0 }}>O sistema abre <b>{game.title_name || game.title_id}</b> pelo menu do console
      e só libera o jogador depois que o próprio console confirmar o código {game.title_id}.
      {game.detected_at && <> Reconhecido em {new Date(game.detected_at).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' })}.</>}</p>
      : <p className="small muted" style={{ margin: 0 }}>Antes de reconhecer: <b>abra este jogo uma vez no console</b> (ele passa a ser o primeiro do menu)
        e deixe o perfil com o status <b>Online</b> (Perfil &gt; Definir status online). O sistema abre os últimos jogos do menu, um por vez,
        até achar o que tem o nome deste jogo, e tira um print para a equipe conferir.</p>}
    {game.evidence_png && <details className="small"><summary>Print do reconhecimento</summary>
      <img className="launch-evidence-thumb" src={`data:image/png;base64,${game.evidence_png}`} alt={`Print do reconhecimento de ${game.title}`} /></details>}
    {job && !running && !job.result.ok && <Alert kind="error">{job.result.message}</Alert>}
    <div className="row">
      <button className="btn primary sm" disabled={busy || running || !agentReady} onClick={() => void start('detect')}>
        {running && job?.kind === 'detect' ? 'Reconhecendo…' : game.title_id ? 'Reconhecer de novo' : 'Reconhecer jogo'}</button>
      {(game.title_id || game.steps.length > 0) && <button className="btn sm" disabled={busy || running || !agentReady} onClick={() => void start('test')}>
        {running && job?.kind === 'test' ? 'Testando…' : 'Testar abertura'}</button>}
      {job && <button className="btn sm" onClick={() => setOpen(true)}>{running ? 'Ver andamento' : 'Ver resumo'}</button>}
      <button className="btn sm" onClick={onAdvanced}>Roteiro avançado</button>
    </div>
    <details className="small"><summary>Informar o código manualmente</summary>
      <div className="row" style={{ marginTop: 6 }}>
        <Field label="Código do jogo (CUSA/PPSA)"><input value={code} maxLength={12} placeholder="CUSA05904"
          onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ''))} /></Field>
        <button className="btn sm" disabled={busy || !/^[A-Z]{4}\d{5}(_\d{2})?$/.test(code)}
          onClick={() => void saveTitle({ title_id: code, title_name: game.title_name ?? '' }, false)}>Salvar código</button>
      </div></details>
    {job && open && <OpeningProgress kind={job.kind} title={game.title} result={job.result} log={job.log} started={job.started} busy={busy}
      onConfirm={(g) => void saveTitle(g, true)} onClose={() => setOpen(false)} />}
  </div>;
}

/** Abertura dos jogos de um console (proprietário: base /owner/consoles/ID; equipe: /admin/consoles/ID). */
export default function LaunchScripts({ base }: { base: string }) {
  const data = useApi<ScriptList>(`${base}/launch-scripts`);
  const [editing, setEditing] = useState<string>();
  const d = data.data;
  const game = d?.games.find((g) => g.game_id === editing);
  if (data.loading && !d) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} onRetry={data.reload} />;
  if (!d) return null;
  return <div className="stack">
    {!d.agent_ready && <Alert kind="info">Reconhecer e testar ficam disponíveis depois que o console for aprovado e a conexão for aplicada a um agente.</Alert>}
    {game ? <Editor key={game.game_id} base={base} game={game} buttons={d.buttons} onSaved={data.reload} onClose={() => setEditing(undefined)} />
      : d.games.length === 0 ? <p className="muted">Nenhum jogo vinculado a este console. Vincule os jogos no cadastro do console.</p>
      : d.games.map((g) => <GameOpening key={g.game_id} base={base} game={g} agentReady={d.agent_ready} onSaved={data.reload}
        onAdvanced={() => setEditing(g.game_id)} />)}
  </div>;
}
