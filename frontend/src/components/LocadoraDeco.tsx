// Decoração da barra lateral: prateleiras de cartuchos (SVG próprio) + letreiro neon original
// (public/assets/letreiro-locadora.png, recortado da arte antiga, sem o traço). Gerada de forma determinística para o SSR bater com o cliente.

const PALETTE = ['#6b3fa8', '#2f5fa3', '#9a2f74', '#2f7d68', '#a8742c', '#3d3f9a', '#b0405a'];
const BOARDS = [110, 200, 290, 380, 470, 524];

type Cart = { x: number; w: number; h: number; c: string };

function buildShelves() {
  let seed = 7;
  const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  return BOARDS.map((y) => {
    const items: Cart[] = [];
    let x = -4;
    while (x < 234) {
      const w = 22 + Math.floor(rnd() * 5);
      items.push({ x, w, h: 56 + Math.floor(rnd() * 9), c: PALETTE[Math.floor(rnd() * PALETTE.length)] });
      x += w + 2 + Math.floor(rnd() * 2);
    }
    return { y, items };
  });
}

const SHELVES = buildShelves();

function Cartridge({ x, y, w, h, c }: Cart & { y: number }) {
  const top = y - h;
  return (
    <g>
      {/* corpo com "ombros" recortados embaixo, como cartucho */}
      <path d={`M${x} ${top + 3}a3 3 0 0 1 3-3h${w - 6}a3 3 0 0 1 3 3V${y - 8}h-2V${y}H${x + 2}V${y - 8}H${x}Z`} fill="#2a2147" stroke="#3b3166" strokeWidth=".8" />
      <path d={`M${x + 3} ${top + 4}h${w - 6}M${x + 3} ${top + 7}h${w - 6}M${x + 3} ${top + 10}h${w - 6}`} stroke="#151027" strokeWidth="1.3" />
      <rect x={x + 3} y={top + 14} width={w - 6} height={h * 0.5} rx="1.5" fill={c} opacity=".9" />
      <rect x={x + 3} y={top + 14} width={w - 6} height="3" fill="#fff" opacity=".3" />
      <rect x={x + 5} y={top + 20} width={w - 10} height={h * 0.18} rx="1" fill="#0f0b1e" opacity=".35" />
    </g>
  );
}

export default function LocadoraDeco() {
  return (
    <svg viewBox="0 0 230 524" preserveAspectRatio="xMidYMax slice" aria-hidden>
      <defs>
        <radialGradient id="ld-room" cx="50%" cy="62%" r="75%">
          <stop offset="0" stopColor="#2a1348" /><stop offset=".6" stopColor="#140b2a" /><stop offset="1" stopColor="#0b0918" />
        </radialGradient>
        <linearGradient id="ld-shade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0b0918" stopOpacity=".55" /><stop offset=".5" stopColor="#0b0918" stopOpacity=".15" /><stop offset="1" stopColor="#0b0918" stopOpacity=".6" />
        </linearGradient>
        <filter id="ld-glow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="2.6" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <rect width="230" height="524" fill="url(#ld-room)" />

      {/* prateleiras com cartuchos */}
      <g opacity=".6">
        {SHELVES.map((s) => (
          <g key={s.y}>
            {s.items.map((it) => <Cartridge key={it.x} {...it} y={s.y} />)}
            <rect x="0" y={s.y} width="230" height="7" fill="#231936" />
            <path d={`M0 ${s.y + .5}h230`} stroke="#4a3a75" strokeWidth="1" />
          </g>
        ))}
      </g>
      <rect width="230" height="524" fill="url(#ld-shade)" />

      {/* tubo de luz neon */}
      <path d="M62 84h106" stroke="#ff5fd8" strokeWidth="3" strokeLinecap="round" filter="url(#ld-glow)" opacity=".8" />

      {/* letreiro neon original (recorte com fundo transparente) sobre placa escura */}
      <rect x="40" y="275" width="154" height="98" rx="10" fill="#10081f" fillOpacity=".88" />
      <image href="/assets/letreiro-locadora.png" x="34" y="267" width="164" height="154" />

    </svg>
  );
}
