import Link from 'next/link';
import { BadgeCheck, CalendarClock, CircleDollarSign, FlaskConical, Gamepad2, Landmark, MonitorSmartphone, Send, UserRoundCheck } from 'lucide-react';

const STEPS = [
  { icon: MonitorSmartphone, color: '#a98bff', title: 'Cadastre o console', tag: 'Cadastro de console',
    text: 'Informe código, nome e plataforma. Em seguida configure a conexão (como o console será acessado) e a qualidade da transmissão.' },
  { icon: UserRoundCheck, color: '#f472d0', title: 'Associe a conta PSN', tag: 'Contas PSN',
    text: 'Cadastre a conta PSN, associe ao console e faça o login Sony. Cole o endereço de retorno da Sony para concluir o vínculo.' },
  { icon: Gamepad2, color: '#67d8f0', title: 'Cadastre os jogos e o preço', tag: 'Jogos e preços',
    text: 'Cadastre o jogo com capa, banner e descrição (ou escolha um do catálogo), defina o período em que ele fica disponível e o preço por minuto ou por hora.' },
  { icon: CalendarClock, color: '#5ee8a8', title: 'Defina os dias e horários', tag: 'Disponibilidade',
    text: 'Marque os dias da semana e os horários em que o console pode ser alugado.' },
  { icon: Landmark, color: '#f6c453', title: 'Informe onde receber', tag: 'Configurações bancárias',
    text: 'Cadastre a chave Pix ou a conta bancária. Sua parte de cada sessão concluída é enviada a partir de 10 minutos após o fim.' },
  { icon: Send, color: '#a98bff', title: 'Envie para análise', tag: 'Cadastro de console',
    text: 'Com tudo preenchido, clique em "Enviar para análise". A equipe confere o cadastro e as artes e vincula o console e a conta PSN ao agente.' },
  { icon: FlaskConical, color: '#f472d0', title: 'Teste a conexão', tag: 'Cadastro de console',
    text: 'Após a aprovação, clique em "Aplicar configuração e testar". O diagnóstico confere imagem, áudio, controles e o agente.' },
  { icon: BadgeCheck, color: '#5ee8a8', title: 'Publique e acompanhe', tag: 'Dashboard',
    text: 'Com os testes aprovados, publique o console para aluguel e acompanhe reservas, sessões e ganhos no Dashboard. Alterações voltam para a validação e o console segue no ar com a versão aprovada.' },
];

/** Passo a passo do cadastro do console (cartões em zigue-zague ligados por setas, como na referência). */
export default function OwnerHelp() {
  return <section className="stack" id="ajuda">
    <ol className="zigzag" aria-label="Passo a passo do cadastro do console">
      {STEPS.map((s, i) => (
        <li key={s.title} className={`zz-item ${i % 2 ? 'right' : 'left'}${i === STEPS.length - 1 ? ' last' : ''}`} style={{ ['--c' as string]: s.color }}>
          <span className="zz-node" aria-hidden><s.icon size={22} /></span>
          <article className="zz-card">
            <header><span className="zz-step">Passo {i + 1}</span><span className="zz-tag">{s.tag}</span></header>
            <h2>{s.title}</h2>
            <p>{s.text}</p>
          </article>
          {i < STEPS.length - 1 && <span className="zz-link" aria-hidden />}
        </li>))}
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
