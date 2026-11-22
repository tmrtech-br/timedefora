'use client';
import { useState } from 'react';
import { Loader2, Wifi } from 'lucide-react';

type Result = { rttMs: number; jitterMs: number; mbps: number };

/** Mede latência (média de 6 pings) e download (arquivo de 1–2 MB) até o servidor LocaPlay. */
async function measure(): Promise<Result> {
  const rtts: number[] = [];
  for (let i = 0; i < 6; i++) {
    const t = performance.now();
    await fetch(`/api/net/ping?t=${Date.now()}-${i}`, { cache: 'no-store' });
    rtts.push(performance.now() - t);
  }
  rtts.shift(); // descarta o primeiro (abertura de conexão)
  const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length;
  const jitter = rtts.slice(1).reduce((a, v, i) => a + Math.abs(v - rtts[i]), 0) / Math.max(1, rtts.length - 1);
  let kb = 1024, mbps = 0;
  for (let round = 0; round < 2; round++) {
    const t = performance.now();
    const res = await fetch(`/api/net/download?kb=${kb}&t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('download');
    const bytes = (await res.arrayBuffer()).byteLength;
    const secs = (performance.now() - t) / 1000;
    mbps = (bytes * 8) / secs / 1e6;
    if (secs > 0.6) break; // amostra suficiente
    kb = 4096;              // conexão rápida: mede de novo com arquivo maior
  }
  return { rttMs: Math.round(avg), jitterMs: Math.round(jitter), mbps: Math.round(mbps * 10) / 10 };
}

function verdict(r: Result): { tone: string; text: string } {
  if (r.mbps >= 15 && r.rttMs <= 60) return { tone: 'green', text: 'Ótima para jogar' };
  if (r.mbps >= 8 && r.rttMs <= 100) return { tone: 'amber', text: 'Boa — pode haver pequenas oscilações' };
  return { tone: 'red', text: 'Fraca — use cabo ou aproxime-se do roteador' };
}

export default function NetworkTest() {
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<Result | null>(null);
  const [err, setErr] = useState('');
  async function run() {
    setBusy(true); setErr('');
    try { setR(await measure()); } catch { setErr('Não foi possível testar agora. Tente novamente.'); } finally { setBusy(false); }
  }
  const v = r && verdict(r);
  const local = typeof window !== 'undefined' && /^(localhost|127\.|\[::1\]|192\.168\.|10\.)/.test(window.location.hostname);
  return (
    <div>
      <button className="btn sm" onClick={run} disabled={busy}>{busy ? <Loader2 className="spin" size={15} aria-hidden /> : <Wifi size={15} aria-hidden />}{busy ? 'Testando…' : 'Testar conexão'}</button>
      <div className="small" aria-live="polite">
        {r && v && <><span className={`pill ${v.tone}`}>{v.text}</span><div style={{ marginTop: 4 }}>Download <b>{r.mbps} Mbps</b> · Latência <b>{r.rttMs} ms</b> · Variação <b>{r.jitterMs} ms</b></div>
          <div className="dim">Medido até o servidor LocaPlay. Recomendado: 15 Mbps e até 60 ms.</div>
          {local && <div className="err" style={{ marginTop: 4 }}>Servidor rodando neste computador (ambiente de desenvolvimento): os números medem a própria máquina, não a sua internet. Só valem com o site publicado.</div>}</>}
        {err && <span className="err">{err}</span>}
        {!r && !err && !busy && <span className="dim">Mede velocidade e latência reais até o servidor.</span>}
      </div>
    </div>
  );
}
