# Licenças, direitos e fontes

O código em `agent/remoteplay` é fornecido sob **GNU Affero General Public License v3.0 only (AGPL-3.0-only)**, por se tratar de uma implementação baseada no estudo da arquitetura e dos detalhes de protocolo disponibilizados pelo projeto livre Chiaki-ng.

Fontes estudadas: `chiaki-ng/lib/src/remote/holepunch.c`, `rudp.c`, `rudpsendbuffer.c`, `stun.h`, `lib/src/streamconnection.c`, `gui/src/psntoken.cpp`; disponíveis em https://github.com/chiaki-ng/chiaki-ng (licenciamento AGPL, com exceções para OpenSSL indicadas nas unidades fonte). O projeto original e os respectivos titulares mantêm seus direitos. Referências ao Sony PlayStation são marcas de seus respectivos proprietários.

Os módulos Python são uma implementação nova e parcial das partes do protocolo estudadas, não uma cópia integral nem um executável do Chiaki-ng. **Isso não elimina obrigações de copyleft quando houver derivação**, incluindo em usos através de rede; o repositório Chiaki-ng-core explicita que tradução entre linguagens pode constituir derivação. Cumprimento da AGPL e análise do conjunto frontend/backend/agente devem ser feitos antes de exploração comercial ou distribuição. Texto da licença em https://www.gnu.org/licenses/agpl-3.0.html.

A solução não é afiliada, aprovada ou certificada pela Sony. O uso de jogos e consoles em um serviço de locação remota pode exigir direitos/licenças não concedidos pelas ferramentas de código aberto. Não há promessa de compatibilidade com atualizações da PSN nem de acesso em NAT restritivo.
