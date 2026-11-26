# pyremoteplay — cópia modificada pelo LocaPlay

Baseado em **pyremoteplay 0.7.6** (© ktnrg45, https://github.com/ktnrg45/pyremoteplay), licenciado sob a
**GNU General Public License v3.0** (texto completo em `LICENSE`). O projeto original foi arquivado pelo autor.
Esta cópia continua sob a GPL-3.0; o histórico completo das alterações está no git deste repositório
(o primeiro commit desta pasta é a cópia fiel do pacote publicado).

## Alterações (23/11/2026)
- Removidos: interface gráfica (`gui/`) e leitura de controle físico por pygame (`gamepad/`) — não usados pelo agente.
- `ddp.py`: `netifaces` (sem pacote para Python 3.11+ no Windows) trocado por `psutil`; broadcast calculado pela máscara.
- `device.py`: removida a busca de capa/nome na PlayStation Store (dependia do pacote abandonado `pyps4-2ndscreen`
  e fazia chamada externa a cada mudança de estado). O código do jogo em execução continua em `app_id`.
- `session.py`: compatível com `pyee` 9+ (`ExecutorEventEmitter` mudou de módulo).
- `receiver/__init__.py`: compatível com PyAV 14+ (enums renomeados `LOW_DELAY`→`low_delay` etc.; layout de áudio
  como texto no reamostrador). Sem isso o decodificador de vídeo não abria e o áudio saía em formato errado.
- `profile.py`: `Profiles.save()` passa a respeitar `set_default_path()` (antes gravava sempre em `~/.pyremoteplay`).

Validado sem console (testes em `agent/tests/test_direct.py` e verificações de protocolo/criptografia).
A validação com PS4/PS5 reais está pendente.
