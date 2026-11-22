import Link from 'next/link';
import { PageHeader } from '@/components/ui';

export const metadata = { title: 'Como funciona' };
const STEPS = [
  ['1. Escolha o jogo', 'Veja no catálogo os jogos, consoles, janelas de disponibilidade, fila atual e transmissão ao vivo.'],
  ['2. Compre o tempo', 'Escolha um pacote (ex.: 10 ou 30 minutos). Entre na fila (início estimado) ou reserve um horário fixo. A reserva fica provisória até o pagamento por Pix ou cartão ser confirmado pelo servidor.'],
  ['3. Aguarde sua vez', 'Acompanhe sua posição em tempo real. Avisamos no site e por e-mail cerca de 5 minutos antes, e quando o console estiver pronto.'],
  ['4. Jogue no navegador', 'Na sala de espera escolha teclado e mouse ou controle USB/Bluetooth, teste a entrada e clique em “Começar a jogar”. O controle é exclusivo seu durante o período contratado.'],
  ['5. Fim do tempo', 'Mostramos avisos com 10, 5 e 1 minuto e 30 segundos restantes. No fim, o servidor revoga o controle automaticamente e chama o próximo jogador.'],
];
export default function Page() {
  return (
    <div className="stack" style={{ maxWidth: 880 }}>
      <PageHeader title="Como funciona" subtitle="Aluguel de tempo em consoles físicos, jogado direto no navegador." />
      {STEPS.map(([t, d]) => <section key={t} className="card"><h2>{t}</h2><p className="muted" style={{ margin: 0 }}>{d}</p></section>)}
      <section className="card"><h2>Regras importantes</h2><ul className="muted">
        <li>Um jogador controla cada console por vez; espectadores assistem pela transmissão pública, sem controle.</li>
        <li>Atrasos do jogador não estendem o término. Falhas da plataforma são compensadas.</li>
        <li>Veja a <Link className="link-purple" href="/politica-cancelamento">política de cancelamento e reembolso</Link>.</li></ul></section>
    </div>
  );
}
