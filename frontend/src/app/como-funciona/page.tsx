import Link from 'next/link';
import { CreditCard, Gamepad2, Hourglass, Search, ShieldCheck, TimerReset, Users, Wrench } from 'lucide-react';
import { PageHeader } from '@/components/ui';

export const metadata = { title: 'Como funciona' };

const STEPS = [
  { icon: Search, color: 'purple', title: 'Escolha o jogo', tag: 'Catálogo',
    text: 'Veja no catálogo os jogos, consoles, janelas de disponibilidade, fila atual e transmissão ao vivo.' },
  { icon: CreditCard, color: 'pink', title: 'Compre o tempo', tag: 'Pix ou cartão',
    text: 'Escolha um pacote (ex.: 10 ou 30 minutos). Entre na fila (início estimado) ou reserve um horário fixo. A reserva fica provisória até o pagamento ser confirmado pelo servidor.' },
  { icon: Hourglass, color: 'cyan', title: 'Aguarde sua vez', tag: 'Tempo real',
    text: 'Acompanhe sua posição em tempo real. Avisamos no site e por e-mail cerca de 5 minutos antes e quando o console estiver pronto.' },
  { icon: Gamepad2, color: 'green', title: 'Jogue no navegador', tag: 'Controle exclusivo',
    text: 'Na sala de espera escolha teclado e mouse ou controle USB/Bluetooth, teste a entrada e clique em “Começar a jogar”. O controle é só seu durante o período contratado.' },
  { icon: TimerReset, color: 'amber', title: 'Fim do tempo', tag: 'Avisos automáticos',
    text: 'Avisamos com 10, 5 e 1 minuto e 30 segundos restantes. No fim, o servidor encerra o controle automaticamente e chama o próximo jogador.' },
];

const RULES = [
  { icon: Users, text: 'Um jogador controla cada console por vez; espectadores assistem pela transmissão pública, sem controle.' },
  { icon: Wrench, text: 'Atrasos do jogador não estendem o término. Falhas da plataforma são compensadas.' },
  { icon: ShieldCheck, text: <>Veja a <Link className="link-purple" href="/politica-cancelamento">política de cancelamento e reembolso</Link>.</> },
];

export default function Page() {
  return (
    <div className="stack how" style={{ maxWidth: 1480 }}>
      <PageHeader title="Como funciona" subtitle="Aluguel de tempo em consoles físicos, jogado direto no navegador." />

      <ol className="timeline" aria-label="Passo a passo">
        {STEPS.map((s, i) => (
          <li key={s.title} className={`tl-item ${s.color}`} style={{ ['--i' as string]: i }}>
            <span className="tl-node" aria-hidden><s.icon size={22} /></span>
            <article className="tl-card">
              <header>
                <span className="tl-step">Passo {i + 1}</span>
                <span className="tl-tag">{s.tag}</span>
              </header>
              <h2>{s.title}</h2>
              <p>{s.text}</p>
            </article>
          </li>
        ))}
        <li className="tl-end" aria-hidden><span>GAME ON!</span></li>
      </ol>

      <section className="card how-rules" aria-labelledby="t-rules">
        <h2 id="t-rules">Regras importantes</h2>
        <ul>{RULES.map((r, i) => <li key={i}><r.icon size={18} aria-hidden /><span>{r.text}</span></li>)}</ul>
      </section>
    </div>
  );
}
