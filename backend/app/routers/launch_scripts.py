"""Roteiros de abertura dos jogos: menu "Roteiros" do proprietário (consoles dele) e da equipe (qualquer console)."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core import timeutil
from ..core.db import all_, audit_event, one, tx
from ..core.deps import Principal, require_role
from ..core.errors import conflict, not_found
from ..gamebridge import AdapterError, get_adapter
from ..services import launch_scripts as ls
from ..services.consoles import console_ref
from .common import jsonable
from .owner import enrolled_owner

owner_router = APIRouter(prefix='/owner/consoles/{console_id}', tags=['owner'])
admin_router = APIRouter(prefix='/admin/consoles/{console_id}', tags=['admin'])
OPERATOR = require_role('operator')


class ScriptIn(BaseModel):
    steps: list[str] = Field(default_factory=list, max_length=ls.MAX_STEPS)
    images: dict[str, dict] = Field(default_factory=dict)


class TitleIn(BaseModel):
    from_detection: bool = False             # confirma o jogo achado pelo "Reconhecer": o print vem direto do agente
    title_id: str = Field(pattern=r'^[A-Za-z]{4}\d{5}(_\d{2})?$')
    title_name: str = Field(default='', max_length=120)
    settle_seconds: int | None = Field(default=None, ge=0, le=300)


class PinIn(BaseModel):
    pin: str = Field(pattern=r'^\d{8}$')     # PIN de 8 dígitos da tela "Adicionar dispositivo" do PS4


class StartIn(BaseModel):
    start: Literal['auto', 'welcome', 'menu'] = 'auto'   # como o console está agora (o usuário informa ou o sistema lê)


class TestIn(BaseModel):
    start: Literal['auto', 'welcome', 'menu'] = 'auto'
    steps: list[str] | None = None            # roteiro ainda não salvo (rascunho na tela); senão o salvo
    images: dict[str, dict] | None = None


def _console(conn, console_id: UUID, owner_id: str | None):
    row = one(conn, '''select c.id, c.name, p.code platform_code from consoles c join platforms p on p.id=c.platform_id
                       where c.id=%s and c.deleted_at is null and (%s::uuid is null or c.owner_user_id=%s::uuid)''',
              (console_id, owner_id, owner_id))
    if not row:
        raise not_found()
    return row


def _linked_game(conn, console_id: UUID, game_id: UUID):
    game = one(conn, '''select g.id, g.slug, g.title from games g where g.id=%s and g.deleted_at is null
                        and (exists (select 1 from console_game_assignments a where a.console_id=%s and a.game_id=g.id
                                     and a.status in ('active','pending_review'))
                             or exists (select 1 from game_launch_scripts s where s.console_id=%s and s.game_id=g.id))''',
               (game_id, console_id, console_id))
    if not game:
        raise not_found('Jogo não vinculado a este console.')
    return game


def _list(console_id: UUID, owner_id: str | None):
    with tx() as conn:
        console = _console(conn, console_id, owner_id)
        rows = all_(conn, '''
            select g.id game_id, g.title, g.slug, s.steps, s.images, s.updated_at, s.title_id, s.title_name, s.settle_seconds,
                   s.evidence_png, s.detected_at
            from games g left join game_launch_scripts s on s.game_id=g.id and s.console_id=%s
            where g.deleted_at is null and (s.id is not null or exists (
                select 1 from console_game_assignments a where a.console_id=%s and a.game_id=g.id
                  and a.status in ('active','pending_review')))
            order by g.title''', (console_id, console_id))
        ref = console_ref(conn, console_id)
        account = one(conn, '''select pa.online_id from console_connection_configs cc join psn_accounts pa
                               on pa.id=coalesce(cc.psn_account_id, (select owner_requested_psn_account_id from consoles where id=%s))
                               where cc.console_id=%s''', (console_id, console_id))
    return jsonable({'console': console, 'psn_online_id': account['online_id'] if account else None, 'games': [{**r, 'steps': r['steps'] or [], 'images': r['images'] or {}} for r in rows],
                     'agent_ready': bool(ref.agent_endpoint and ref.method != 'unconfigured'),
                     'buttons': list(ls.BUTTONS)})


def _save(console_id: UUID, game_id: UUID, body: ScriptIn, p: Principal, owner_id: str | None):
    steps, images = ls.validate(body.steps, body.images)
    with tx(p.user_id) as conn:
        _console(conn, console_id, owner_id)
        _linked_game(conn, console_id, game_id)
        from psycopg.types.json import Jsonb
        conn.execute('''insert into game_launch_scripts(console_id, game_id, steps, images, updated_by, updated_at)
                        values (%s,%s,%s,%s,%s,%s) on conflict (console_id, game_id) do update
                        set steps=excluded.steps, images=excluded.images, updated_by=excluded.updated_by, updated_at=excluded.updated_at''',
                     (console_id, game_id, Jsonb(steps), Jsonb(images), p.user_id, timeutil.now()))
        audit_event(conn, 'console.launch_script_saved', 'consoles', console_id,
                    details={'game_id': str(game_id), 'steps': len(steps), 'images': sorted(images)})
    return {'ok': True, 'steps': steps}


def _evidence(console_id: UUID, code: str) -> str | None:
    """Print do jogo tirado pelo agente no último "Reconhecer" (só se o código bater com o confirmado)."""
    try:
        with tx() as conn:
            ref = console_ref(conn, console_id)
        adapter = get_adapter(ref.method)
        data = (adapter.script_status(ref) or {}).get('data') or {}
    except Exception:
        return None
    shot = data.get('screenshot')
    seen = {data.get('title_id')} | {s.get('title_id') for s in data.get('seen') or [] if isinstance(s, dict)}
    return shot if isinstance(shot, str) and len(shot) < 700_000 and code in seen else None


def _save_title(console_id: UUID, game_id: UUID, body: TitleIn, p: Principal, owner_id: str | None):
    code = body.title_id.upper().split('_')[0]
    shot = _evidence(console_id, code) if body.from_detection else None
    with tx(p.user_id) as conn:
        _console(conn, console_id, owner_id)
        _linked_game(conn, console_id, game_id)
        n = timeutil.now()
        conn.execute('''insert into game_launch_scripts(console_id, game_id, title_id, title_name, settle_seconds, updated_by, updated_at,
                                                        evidence_png, detected_at, detected_by)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (console_id, game_id) do update
                        set title_id=excluded.title_id, title_name=excluded.title_name, settle_seconds=excluded.settle_seconds,
                            updated_by=excluded.updated_by, updated_at=excluded.updated_at,
                            evidence_png=excluded.evidence_png, detected_at=excluded.detected_at, detected_by=excluded.detected_by''',
                     (console_id, game_id, code, body.title_name.strip()[:120] or None, body.settle_seconds, p.user_id, n,
                      shot, n if body.from_detection else None, p.user_id if body.from_detection else None))
        audit_event(conn, 'console.game_title_saved', 'consoles', console_id, details={'game_id': str(game_id), 'title_id': code})
    return {'ok': True, 'title_id': code}


def _detect(console_id: UUID, game_id: UUID, owner_id: str | None, start: str = 'auto'):
    """Reconhecer: o agente abre o último jogo usado no console e informa o código e o nome (o usuário confirma)."""
    with tx() as conn:
        _console(conn, console_id, owner_id)
        game = _linked_game(conn, console_id, game_id)
        adapter, ref = _agent(conn, console_id, 'script_test')
        payload = ls.game_payload(conn, console_id, game)
    return _call(adapter.script_test, ref, {'id': str(game['id']), 'slug': f"detect-{game['slug']}", 'title': game['title'],
                                            'detect': True, 'max_tiles': payload['max_tiles'], 'start': start})


def _delete(console_id: UUID, game_id: UUID, p: Principal, owner_id: str | None):
    with tx(p.user_id) as conn:
        _console(conn, console_id, owner_id)
        conn.execute('delete from game_launch_scripts where console_id=%s and game_id=%s', (console_id, game_id))
        audit_event(conn, 'console.launch_script_deleted', 'consoles', console_id, details={'game_id': str(game_id)})
    return {'ok': True}


def _agent(conn, console_id: UUID, action: str):
    """Adaptador do console para testar/capturar; nunca com jogador no console."""
    if one(conn, "select 1 from game_sessions where console_id=%s and status in ('ready','active')", (console_id,)):
        raise conflict('session_active', 'Há uma sessão de jogo em andamento neste console. Teste o roteiro depois.')
    if one(conn, "select 1 from console_preparations where console_id=%s and status='pending'", (console_id,)):
        raise conflict('preparing', 'O console está sendo preparado para uma reserva. Teste o roteiro depois.')
    ref = console_ref(conn, console_id)
    if not ref.agent_endpoint or ref.method == 'unconfigured':
        raise conflict('agent_required', 'O console ainda não tem conexão aplicada a um agente: conclua a aprovação e o teste de conexão.')
    try:
        adapter = get_adapter(ref.method)
    except AdapterError as e:
        raise conflict(e.code, e.message)
    if not hasattr(adapter, action):
        raise conflict('not_supported', 'O método de conexão deste console não executa roteiros.')
    return adapter, ref


def _call(fn, *args):
    try:
        return jsonable(fn(*args))
    except AdapterError as e:
        raise conflict(e.code, e.message)


def _test(console_id: UUID, game_id: UUID, body: TestIn, owner_id: str | None):
    with tx() as conn:
        _console(conn, console_id, owner_id)
        game = _linked_game(conn, console_id, game_id)
        if body.steps is not None:
            steps, images = ls.validate(body.steps, body.images or {})
            launch = {'steps': steps, 'images': images}
            payload = {'id': str(game['id']), 'slug': game['slug'], 'title': game['title'], 'launch': launch}
        else:
            payload = ls.game_payload(conn, console_id, game)
        payload['start'] = body.start
        if not payload.get('title_id') and not (payload.get('launch') or {}).get('steps'):
            raise conflict('no_script', 'Reconheça o jogo (ou cadastre os passos do roteiro) antes de testar.')
        adapter, ref = _agent(conn, console_id, 'script_test')
    return _call(adapter.script_test, ref, payload)


def _status(console_id: UUID, owner_id: str | None):
    with tx() as conn:
        _console(conn, console_id, owner_id)
        ref = console_ref(conn, console_id)
        adapter = get_adapter(ref.method) if ref.method != 'unconfigured' else None
    if adapter is None or not hasattr(adapter, 'script_status'):
        raise conflict('not_supported', 'O método de conexão deste console não executa roteiros.')
    return _call(adapter.script_status, ref)


def _pair(console_id: UUID, body: PinIn, p: Principal, owner_id: str | None):
    with tx(p.user_id) as conn:
        _console(conn, console_id, owner_id)
        adapter, ref = _agent(conn, console_id, 'secondscreen_pair')
        audit_event(conn, 'console.secondscreen_pair', 'consoles', console_id)
    return _call(adapter.secondscreen_pair, ref, body.pin)


def _screen(console_id: UUID, owner_id: str | None):
    with tx() as conn:
        _console(conn, console_id, owner_id)
        adapter, ref = _agent(conn, console_id, 'screen_snapshot')
    return _call(adapter.screen_snapshot, ref)


# ------------------------------------------------------------------ proprietário
@owner_router.get('/launch-scripts')
def owner_list(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    return _list(console_id, p.user_id)


@owner_router.put('/launch-scripts/{game_id}')
def owner_save(console_id: UUID, game_id: UUID, body: ScriptIn, p: Principal = Depends(enrolled_owner)):
    return _save(console_id, game_id, body, p, p.user_id)


@owner_router.delete('/launch-scripts/{game_id}')
def owner_delete(console_id: UUID, game_id: UUID, p: Principal = Depends(enrolled_owner)):
    return _delete(console_id, game_id, p, p.user_id)


@owner_router.post('/launch-scripts/{game_id}/test')
def owner_test(console_id: UUID, game_id: UUID, body: TestIn, p: Principal = Depends(enrolled_owner)):
    return _test(console_id, game_id, body, p.user_id)


@owner_router.put('/launch-scripts/{game_id}/title')
def owner_title(console_id: UUID, game_id: UUID, body: TitleIn, p: Principal = Depends(enrolled_owner)):
    return _save_title(console_id, game_id, body, p, p.user_id)


@owner_router.post('/launch-scripts/{game_id}/detect')
def owner_detect(console_id: UUID, game_id: UUID, body: StartIn | None = None, p: Principal = Depends(enrolled_owner)):
    return _detect(console_id, game_id, p.user_id, (body or StartIn()).start)


@owner_router.get('/launch-test')
def owner_status(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    return _status(console_id, p.user_id)


@owner_router.post('/secondscreen/pair')
def owner_pair(console_id: UUID, body: PinIn, p: Principal = Depends(enrolled_owner)):
    return _pair(console_id, body, p, p.user_id)


@owner_router.post('/screen')
def owner_screen(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    return _screen(console_id, p.user_id)


# ------------------------------------------------------------------ equipe
@admin_router.get('/launch-scripts')
def admin_list(console_id: UUID, p: Principal = Depends(OPERATOR)):
    return _list(console_id, None)


@admin_router.put('/launch-scripts/{game_id}')
def admin_save(console_id: UUID, game_id: UUID, body: ScriptIn, p: Principal = Depends(OPERATOR)):
    return _save(console_id, game_id, body, p, None)


@admin_router.delete('/launch-scripts/{game_id}')
def admin_delete(console_id: UUID, game_id: UUID, p: Principal = Depends(OPERATOR)):
    return _delete(console_id, game_id, p, None)


@admin_router.post('/launch-scripts/{game_id}/test')
def admin_test(console_id: UUID, game_id: UUID, body: TestIn, p: Principal = Depends(OPERATOR)):
    return _test(console_id, game_id, body, None)


@admin_router.put('/launch-scripts/{game_id}/title')
def admin_title(console_id: UUID, game_id: UUID, body: TitleIn, p: Principal = Depends(OPERATOR)):
    return _save_title(console_id, game_id, body, p, None)


@admin_router.post('/launch-scripts/{game_id}/detect')
def admin_detect(console_id: UUID, game_id: UUID, body: StartIn | None = None, p: Principal = Depends(OPERATOR)):
    return _detect(console_id, game_id, None, (body or StartIn()).start)


@admin_router.get('/launch-test')
def admin_status(console_id: UUID, p: Principal = Depends(OPERATOR)):
    return _status(console_id, None)


@admin_router.post('/secondscreen/pair')
def admin_pair(console_id: UUID, body: PinIn, p: Principal = Depends(OPERATOR)):
    return _pair(console_id, body, p, None)


@admin_router.post('/screen')
def admin_screen(console_id: UUID, p: Principal = Depends(OPERATOR)):
    return _screen(console_id, None)
