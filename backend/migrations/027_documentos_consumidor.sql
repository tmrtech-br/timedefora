-- Preserva versões aceitas e documentos que passaram por revisão jurídica.
with drafts(kind, title, body) as (
  values
  ('privacy', 'Política de Privacidade', $privacy$
1. Quem trata seus dados
A operação da timedefora é responsável pelo tratamento necessário para gerenciar sua conta, reservas e atendimento. Você pode exercer seus direitos em Configurações → Privacidade e dados (LGPD) ou pelo canal de suporte do site.

2. Quais dados usamos e por quê
Usamos nome, nome público de usuário, e-mail e credenciais protegidas para criar e autenticar a conta. Usamos jogos, horários, valores, cupons, identificadores de pagamento e histórico de atendimento para fornecer o serviço, cumprir obrigações legais e responder a solicitações. Registros como IP, dados do navegador e eventos de acesso são usados para proteger a plataforma, investigar incidentes e prevenir fraudes, observados a necessidade e os direitos do titular. O nome público pode aparecer nas filas. Você pode autorizar ofertas por e-mail e retirar essa autorização nas Configurações.

3. Compartilhamento e serviços de terceiros
Prestadores de infraestrutura, entrega de e-mail e suporte podem receber os dados necessários à atividade que realizam. O Mercado Pago processa o pagamento em seu próprio ambiente. A timedefora recebe dados de referência e confirmação da transação e não armazena dados completos do cartão. Ao escolher entrar com o Google, a plataforma recebe os dados de identidade autorizados nessa integração. A plataforma pode fornecer dados a autoridades mediante obrigação legal. Eventuais transferências internacionais dependem das garantias exigidas pela LGPD.

4. Conservação e segurança
Conservamos dados pelo tempo necessário às finalidades informadas. Obrigações legais, prevenção à fraude e exercício regular de direitos podem justificar a manutenção de registros específicos após o encerramento da conta. Aplicamos medidas de controle de acesso, proteção de credenciais e auditoria. Em incidentes com risco ou dano relevante, seguimos as obrigações de comunicação aplicáveis.

5. Seus direitos
Você pode solicitar confirmação e acesso, correção, portabilidade nos termos aplicáveis, informação sobre compartilhamento e sobre a possibilidade de negar consentimento, revogação de consentimento e anonimização, bloqueio ou eliminação nas hipóteses legais. Também pode se opor a tratamento irregular, pedir revisão de decisões exclusivamente automatizadas quando cabível e peticionar à ANPD. Podemos confirmar a identidade do solicitante para proteger os dados.

6. Sessão e atualizações
Cookies de sessão mantêm o acesso e ajudam a proteger operações autenticadas. Publicamos a versão vigente desta política no site e comunicamos alterações relevantes quando exigido.
$privacy$),
  ('terms', 'Termos de Uso', $terms$
1. Serviço
A timedefora permite reservar acesso remoto e temporário a um console. A oferta descreve o jogo, a duração, os requisitos e o preço. A contratação se refere ao intervalo reservado e não transfere propriedade do console, do jogo ou de contas de terceiros.

2. Cadastro e acesso
Mantenha seus dados atualizados, confirme o e-mail e proteja suas credenciais. Respeite a classificação indicativa e as regras da plataforma e do jogo. É vedado interferir em sessões de terceiros, contornar controles de acesso, fraudar pagamentos ou usar a plataforma para fins ilícitos.

3. Agendamento e pagamento
Revise o jogo, as datas, a duração, o preço e as condições antes de confirmar. O horário em fila pode ser antecipado conforme a disponibilidade informada. A reserva provisória expira no prazo exibido no checkout. O horário é garantido após confirmação do pagamento. O comprovante e os dados da reserva permanecem acessíveis nas áreas de pagamentos e sessões.

4. Atendimento, cancelamento e reembolso
A Política de Agendamento, Ausência, Atraso, Cancelamento e Reembolso integra as condições da reserva e é apresentada antes da confirmação. Para solicitar cancelamento ou relatar falhas, use os detalhes da sessão ou a área de suporte. Falhas imputáveis ao serviço serão tratadas com as soluções cabíveis, incluindo remarcação ou reembolso conforme o caso. Os direitos previstos no Código de Defesa do Consumidor, inclusive o direito de arrependimento nas hipóteses aplicáveis, permanecem assegurados.

5. Privacidade e vigência
A Política de Privacidade descreve os dados usados para operar a conta e os canais para exercer direitos. Alterações nos termos serão divulgadas no site e respeitarão as condições das contratações já concluídas e os direitos legais. O suporte do site atende dúvidas sobre reservas, pagamentos e exercício de direitos.
$terms$)
), superseded as (
  update policy_documents p set is_current=false
  from drafts d
  where p.kind=d.kind and p.is_current and p.requires_legal_review
    and p.version in ('0.1-rascunho', '0.2-rascunho')
  returning p.kind
)
insert into policy_documents(kind, version, title, body, is_current, published_at, requires_legal_review)
select d.kind, '0.3-rascunho', d.title, trim(d.body), true, now(), true
from drafts d
where d.kind in (select kind from superseded)
   or not exists (select 1 from policy_documents p where p.kind=d.kind and p.is_current);
