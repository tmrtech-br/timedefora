# Checklist de instalação de um console (PS4/PS5) no LocaPlay

Faça **uma vez por console**, na instalação. Marque cada item. Os nomes de menu são do PS4 em português e podem
variar um pouco conforme a versão do sistema; no PS5 os caminhos equivalentes ficam em **Configurações → Família e controles parentais**.

> Objetivo: o cliente aluga **o jogo**, não o console. Ele não pode comprar nada, trocar configurações,
> usar a conta em outro lugar nem sair do jogo para outros aplicativos.

## 1. Conta PSN dedicada (nunca use uma conta pessoal)
- [ ] Criar uma conta **só para o LocaPlay**, com nome neutro (ex.: `LocaPlay_PS4_118`).
- [ ] **Senha forte** e única, guardada no cofre de senhas da empresa.
- [ ] **Verificação em duas etapas** ligada (Configurações → Gerenciamento de conta → Informações da conta → Segurança).
- [ ] **Nenhum cartão ou PayPal salvo** e **carteira com saldo zero** (gerenciar pelo site da PlayStation, em Gerenciamento de conta → Pagamentos).
- [ ] Privacidade no máximo (Configurações → Gerenciamento de conta → Configurações de privacidade): nome real oculto,
      perfil e lista de amigos visíveis só para "Ninguém", solicitações de amizade bloqueadas, mensagens só de "Ninguém".

## 2. Conta de criança com restrições (Gerenciamento de Família)
Uma conta "adulta" (dona da família, também da empresa) gerencia a conta de jogo como **conta de criança**.
- [ ] **Limite de gastos mensal: R$ 0** → bloqueia **toda compra com dinheiro real**: PlayStation Store **e compras dentro do jogo**
      (ex.: Shark Cards do GTA), porque elas passam pela loja da PSN.
- [ ] **Comunicação com outros jogadores** (chat/mensagens): Restrito.
- [ ] **Conteúdo criado por outros jogadores**: Restrito.
- [ ] **Navegador de Internet**: Não permitido.
- [ ] **Nível etário dos jogos**: liberado até a classificação dos jogos vendidos (ex.: 18 anos para GTA).

## 3. Restrições do sistema do console
Configurações → Controle dos Pais/Gerenciamento de Família → **Restrições do Sistema PS4**
- [ ] Trocar a senha padrão (`0000`) por uma senha de 4 dígitos da empresa.
- [ ] **Novo usuário e login de convidado**: Não permitido.
- [ ] Deixar **apenas o usuário da conta de jogo** no console.

## 4. Remote Play e energia
- [ ] Configurações → Configurações de conexão de Uso Remoto → **Ativar Uso Remoto**.
- [ ] Configurações → Gerenciamento de conta → **Ativar como seu PS4 principal**.
- [ ] Configurações → Economia de energia → Recursos no modo de repouso: **Permanecer conectado à Internet** e **Ativar ligar o PS4 pela rede**.
- [ ] Configurações → Economia de energia → **Definir tempo até o PS4 desligar**: evitar desligamento total (só modo de repouso).

## 5. Atualizações (evitar que fechem o jogo no meio da operação)
- [ ] Configurações → Sistema → **Downloads automáticos**: desmarcar *Arquivos de atualização do software do sistema*
      e *Arquivos de atualização de aplicativos*.
- [ ] Atualizar manualmente em janela de manutenção (Painel → Vínculos e calendário → **Manutenção/bloqueios**).

## 6. Rede
- [ ] PS4 **no cabo**, com **IP fixo** reservado no roteador.
- [ ] Testar conexão no PS4 (Configurações → Rede → Testar conexão): NAT tipo 1 ou 2; upload ≥ 15 Mbps para 720p/60.

## 7. PC do agente (ao lado do console)
- [ ] Mesma rede do PS4, no cabo; energia estável (de preferência nobreak).
- [ ] chiaki-ng instalado; login PSN feito com a **conta de jogo**; **PS4 registrado** (na rede local).
- [ ] ConsoleAgent instalado (`agent/README.md`), `config.json` com os tokens, inicia junto com o Windows.
- [ ] Painel → Agentes e dispositivos: agente **online**.

## 8. Cadastro e validação no painel
- [ ] Painel → Consoles e conexão → novo console (código, nome, plataforma).
- [ ] Método **Remote Play — Chiaki**, agente, rota de rede, identificação do console.
- [ ] Testes: heartbeat, descobrir, conexão, imagem e áudio, controles — **todos aprovados e não simulados**.
- [ ] Publicar o console; criar o vínculo jogo × console (Vínculos e calendário) e conferir os preços.
- [ ] Painel → Parâmetros: **Botão Share do controle desligado** (padrão).

## 9. Antes de liberar para clientes
- [ ] Abrir o jogo, carregar um ponto neutro, e colocar o console em **modo de repouso com o jogo aberto**
      (o agente acorda o console e o cliente cai direto no jogo).
- [ ] Fazer uma reserva de teste ponta a ponta (pagamento simulado em dev).
- [ ] Revisão jurídica concluída (termos da PlayStation para uso comercial do Remote Play, licença AGPL-3.0 do chiaki-ng).

## O que o sistema já faz sozinho
| Proteção | Onde |
|---|---|
| Botão **PS** (tela inicial) e touchpad bloqueados | servidor (todo comando é filtrado) |
| Botão **Share** bloqueado (padrão) | Painel → Parâmetros |
| Console preparado **antes** da sessão, só com o console livre | worker + agente (preparação automática na Parte 2) |
| Console não ficou pronto → sessão não começa, reserva "Em resolução", **incidente** e **aviso à equipe e ao cliente** | automático |
| Tempo não é consumido quando a falha é da plataforma | reserva vai para resolução (remarcar ou reembolsar) |

## Limites conhecidos
- Moeda **virtual** ganha jogando (ex.: GTA$) pode ser gasta dentro do jogo — não envolve dinheiro real e não dá para bloquear.
- Menus do próprio jogo (modo online, opções do jogo) continuam acessíveis; o progresso salvo pode ser alterado pelo cliente.
- O nome da conta aparece no jogo; por isso a conta é dedicada, restrita e protegida por verificação em duas etapas.
