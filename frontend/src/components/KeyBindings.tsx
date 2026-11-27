'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { RotateCcw, Save } from 'lucide-react';
import { toast } from '@/components/Toaster';
import { ApiError } from '@/lib/api';
import { useFeatures } from '@/lib/features';
import { ACTIONS, type Action, type Bindings, DEFAULT_KEYS, RESERVED, codeLabel, useBindings } from '@/lib/keymap';

/** Legenda das teclas do jogador (sala de espera e painel "Ver comandos" do jogo). */
export function KeyLegend({ bindings, compact = false }: { bindings: Bindings; compact?: boolean }) {
  const k = bindings.keys;
  const rows: [string[], string][] = [
    [[k.ls_up, k.ls_left, k.ls_down, k.ls_right].map(codeLabel), 'Analógico esquerdo (andar)'],
    [bindings.mouse_look ? ['Mouse'] : [k.rs_up, k.rs_left, k.rs_down, k.rs_right].map(codeLabel), 'Analógico direito (câmera)'],
    ...ACTIONS.filter((a) => !a.id.startsWith('ls_') && !a.id.startsWith('rs_') && !a.id.startsWith('dpad_'))
      .map((a) => [[codeLabel(k[a.id])], `${a.sym} ${a.label.split(' (')[0]}`] as [string[], string]),
    [[k.dpad_up, k.dpad_left, k.dpad_down, k.dpad_right].map(codeLabel), 'Direcional'],
  ];
  if (bindings.mouse_look) rows.splice(2, 0, [[codeLabel(k.rs_up), codeLabel(k.rs_left), codeLabel(k.rs_down), codeLabel(k.rs_right)], 'Câmera pelo teclado (alternativa)']);
  return (
    <div className={`keymap${compact ? ' compact' : ''}`}>
      {rows.map(([keys, action]) => <div key={action}><span className="row" style={{ gap: 4, flexWrap: 'wrap' }}>{keys.map((x, i) => <kbd key={i}>{x}</kbd>)}</span><span>{action}</span></div>)}
    </div>
  );
}

/** Editor do mapeamento: clique na ação e pressione a tecla ou o botão do mouse. */
export default function KeyBindingsEditor() {
  const { bindings, loaded, save, reset } = useBindings();
  const [keys, setKeys] = useState<Record<Action, string>>(DEFAULT_KEYS);
  const [look, setLook] = useState(true);
  const [sens, setSens] = useState(1);
  const [listening, setListening] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (loaded) { setKeys(bindings.keys); setLook(bindings.mouse_look); setSens(bindings.mouse_sensitivity); } }, [loaded, bindings]);
  const dirty = useMemo(() => JSON.stringify([keys, look, sens]) !== JSON.stringify([bindings.keys, bindings.mouse_look, bindings.mouse_sensitivity]), [keys, look, sens, bindings]);

  useEffect(() => {
    if (!listening) return;
    const assign = (code: string) => {
      if (RESERVED.has(code)) { toast('error', `${codeLabel(code)} é usada pelo navegador e não pode ser escolhida.`); return; }
      setKeys((prev) => {
        const next = { ...prev };
        const other = (Object.keys(next) as Action[]).find((a) => a !== listening && next[a] === code);
        if (other) {                                   // tecla já usada: troca as duas de lugar
          next[other] = prev[listening];
          toast('ok', `${codeLabel(code)} estava em "${ACTIONS.find((a) => a.id === other)?.label}"; as teclas foram trocadas.`);
        }
        next[listening] = code;
        return next;
      });
      setListening(null);
    };
    const onKey = (e: KeyboardEvent) => { e.preventDefault(); e.stopPropagation(); if (e.code === 'Escape') { setListening(null); return; } assign(e.code); };
    const onMouse = (e: MouseEvent) => { if ((e.target as HTMLElement)?.closest('.kb-cancel')) return; e.preventDefault(); assign(`Mouse${e.button}`); };
    const noMenu = (e: MouseEvent) => e.preventDefault();
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('mousedown', onMouse, true);
    window.addEventListener('contextmenu', noMenu, true);
    return () => { window.removeEventListener('keydown', onKey, true); window.removeEventListener('mousedown', onMouse, true); window.removeEventListener('contextmenu', noMenu, true); };
  }, [listening]);

  async function doSave() {
    setBusy(true);
    try { await save({ keys, mouse_look: look, mouse_sensitivity: sens }); toast('ok', 'Controles salvos no seu perfil.'); }
    catch (e) { toast('error', e instanceof ApiError ? e.message : 'Não foi possível salvar.'); }
    setBusy(false);
  }
  async function doReset() {
    setBusy(true);
    try { await reset(); toast('ok', 'Controles voltaram ao padrão do site.'); } catch { toast('error', 'Não foi possível restaurar.'); }
    setBusy(false);
  }

  const groups = Array.from(new Set(ACTIONS.map((a) => a.group)));
  return (
    <section className="card stack" id="controles">
      <div className="spread"><h2 style={{ margin: 0 }}>Mapeamento dos controles</h2>
        {bindings.custom ? <span className="pill purple">personalizado</span> : <span className="pill">padrão do site</span>}</div>
      <p className="small muted" style={{ margin: 0 }}>Clique numa ação e pressione a tecla (ou o botão do mouse) que quer usar. Se a tecla já estiver em outra ação, as duas trocam de lugar.
        Vale para todas as suas sessões. Quem joga com controle USB/Bluetooth não precisa mudar nada aqui.</p>
      {!loaded ? <div className="skeleton" style={{ height: 160 }} /> : (
        <div className="kb-groups">
          {groups.map((g) => (
            <div key={g} className="kb-group"><h3>{g}</h3>
              {ACTIONS.filter((a) => a.group === g).map((a) => (
                <div key={a.id} className="kb-row">
                  <span><b className="kb-sym" data-action={a.id} aria-hidden>{a.sym}</b> {a.label}</span>
                  <button type="button" className={`btn sm kb-key${listening === a.id ? ' listening' : ''}${keys[a.id] !== DEFAULT_KEYS[a.id] ? ' changed' : ''}`}
                    onClick={() => setListening(listening === a.id ? null : a.id)} aria-label={`${a.label}: ${codeLabel(keys[a.id])}. Clique para trocar.`}>
                    {listening === a.id ? 'Pressione…' : codeLabel(keys[a.id])}</button>
                </div>))}
            </div>))}
          <div className="kb-group"><h3>Mouse</h3>
            <label className="check"><input type="checkbox" checked={look} onChange={(e) => setLook(e.target.checked)} />Mover o mouse controla a câmera (analógico direito)</label>
            <label className="small" style={{ display: 'grid', gap: 4 }}>Sensibilidade: <b>{sens.toFixed(1)}×</b>
              <input type="range" min={0.1} max={3} step={0.1} value={sens} disabled={!look} onChange={(e) => setSens(Number(e.target.value))} /></label>
            <p className="small dim" style={{ margin: 0 }}>Na partida, clique na imagem do jogo para o mouse “prender” na tela; Esc solta.</p>
          </div>
        </div>)}
      {listening && <p className="small" role="status">Pressione a nova tecla para <b>{ACTIONS.find((a) => a.id === listening)?.label}</b>… <button type="button" className="btn sm kb-cancel" onClick={() => setListening(null)}>Cancelar</button></p>}
      <div className="row">
        <button className="btn primary" disabled={busy || !dirty} onClick={doSave}><Save size={16} aria-hidden />Salvar controles</button>
        <button className="btn" disabled={busy || !bindings.custom} onClick={doReset}><RotateCcw size={16} aria-hidden />Voltar ao padrão</button>
      </div>
    </section>
  );
}

export function CustomizeLink() {
  const features = useFeatures();
  return features?.controls_menu_enabled ? <Link className="link-purple small" href="/controles">Personalizar teclas</Link> : null;
}
