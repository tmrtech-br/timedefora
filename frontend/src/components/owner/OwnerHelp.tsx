import Link from 'next/link';
import { BadgeCheck, CalendarClock, CircleDollarSign, Gamepad2, Landmark, MonitorSmartphone, Send, UserRoundCheck } from 'lucide-react';

const STEPS = [
  { icon: MonitorSmartphone, color: 'purple', title: 'Cadastre o console', tag: 'Cadastro de console',
    text: 'Informe código, nome, plataforma e escolha o agente da plataforma que vai controlar o seu console (o computador nosso ligado a ele).' },
  { icon: UserRoundCheck, color: 'pink', title: 'Conecte a conta PSN', tag: 'Contas PSN',
    text: 'Cadastre a conta PSN do console, faça o login Sony (pelo link que aparece) e vincule a conta ao console.' },
  { icon: Gamepad2, color: 'cyan', title: 'Cadastre os jogos e o preço', tag: 'Jogos e preços',
    text: 'Cadastre o jogo com capa, banner e descrição (ou escolha um do catálogo), defina o período em que ele fica disponível e o preço por minuto ou por hora.' },
  { icon: CalendarClock, color: 'green', title: 'Defina os dias e horários', tag: 'Disponibilidade',
    text: 'Marque os dias da semana e os horários em que o console pode ser alugado.' },
  { icon: Landmark, color: 'amber', title: 'Informe onde receber', tag: 'Configurações bancárias',
    text: 'Cadastre a chave Pix ou a conta bancária. Sua parte de cada sessão concluída é enviada a partir de 10 minutos após o fim.' },
  { icon: Send, color: 'purple', title: 'Envie para análise', tag: 'Cadastro de console',
    text: 'Com tudo preenchido, clique em "Enviar para análise". A equipe confere o cadastro, as artes e a conexão, e aprova ou pede ajustes.' },
  { icon: BadgeCheck, color: 'green', title: 'Publique e acompanhe', tag: 'Dashboard',
    text: 'Aprovado, publique o console para aluguel. Acompanhe reservas, sessões e ganhos no Dashboard. Qualquer alteração volta para a validação, e o console segue no ar com a versão aprovada.' },
];

/** Passo a passo do cadastro do console para o proprietário (mesmo estilo de "Como funciona"). */
export default function OwnerHelp() {
  return <section className="stack how" id="ajuda">
    <ol className="timeline" aria-label="Passo a passo do cadastro do console">
      {STEPS.map((s, i) => (
        <li key={s.title} className={`tl-item ${s.color}`} style={{ ['--i' as string]: i }}>
          <span className="tl-node" aria-hidden><s.icon size={22} /></span>
          <article className="tl-card">
            <header><span className="tl-step">Passo {i + 1}</span><span className="tl-tag">{s.tag}</span></header>
            <h2>{s.title}</h2>
            <p>{s.text}</p>
          </article>
        </li>))}
      <li className="tl-end" aria-hidden><span>NO AR!</span></li>
    </ol>
    <section className="card how-rules">
      <h2>Bom saber</h2>
      <ul>
        <li><CircleDollarSign size={18} aria-hidden /><span>Você recebe a sua porcentagem de cada sessão concluída sem problemas, por Pix ou transferência, sem custo.</span></li>
        <li><BadgeCheck size={18} aria-hidden /><span>Enquanto o console está em análise, a edição fica bloqueada; você pode cancelar o envio para editar.</span></li>
        <li><Send size={18} aria-hidden /><span>Dúvidas? Abra um chamado em <Link className="link-purple" href="/suporte">Suporte</Link>.</span></li>
      </ul>
    </section>
  </section>;
}
