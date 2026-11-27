"""Sessões de jogo: alocação exclusiva, token efêmero de entrada, reconexão, encerramento automático.

- Token efêmero vinculado a user_id + reservation_id + console_id, armazenado como hash, expira no fim contratual.
- Um único controlador por console (índice único parcial em game_sessions).
- O fim do tempo é aplicado pelo SERVIDOR (worker) mesmo sem navegador aberto; comandos após o fim são recusados.
"""
from datetime import timedelta

from psycopg.types.json import Jsonb

from ..core import security, timeutil
from ..core.db import audit_event, insert, tx
from ..core.errors import AppError, conflict, forbidden, not_found
from ..gamebridge import AdapterError, get_adapter
from . import console_power, notifications, owner_settlements, preparation, scheduling
from .consoles import console_ref
from .settings_store import get_settings, require_enabled


def _event(conn, session_id, kind: str, details: dict | None = None) -> None:
    conn.execute('insert into session_events(session_id, event_type, details) values (%s,%s,%s)',
                 (session_id, kind, Jsonb(details or {})))


def prepare_session(conn, r: dict) -> dict:
    """Libera o console para a reserva (chamado pelo worker no início ou no primeiro acesso)."""
    # Serializa a liberação do console com a troca da configuração de conexão.
    conn.execute('select id from consoles where id=%s for update', (r['console_id'],))
    s = conn.execute('select * from game_sessions where reservation_id=%s', (r['id'],)).fetchone()
    if s:
        return s
    # Relê a reserva: a preparação pode ter empurrado o fim (o tempo só conta com o console pronto).
    r = conn.execute('select * from reservations where id=%s', (r['id'],)).fetchone()
    # Fim empurrado = contrato começa quando o console ficou pronto (sem empurrão: o próprio início da reserva).
    starts = max(r['starts_at'], r['ends_at'] - timedelta(minutes=r['minutes']))
    # Tempo extra do jogador (clique → imagem na tela): já reservado no intervalo bloqueado, entra no fim do contrato.
    bonus = scheduling.join_bonus(get_settings(conn))
    ends = min(r['ends_at'] + bonus, r['blocked_until'])
    if ends > r['ends_at']:
        conn.execute('update reservations set ends_at=%s where id=%s', (ends, r['id']))
        r = {**r, 'ends_at': ends}
    method = conn.execute('select method from console_connection_configs where console_id=%s', (r['console_id'],)).fetchone()
    s = insert(conn, 'game_sessions', {
        'reservation_id': r['id'], 'user_id': r['user_id'], 'console_id': r['console_id'], 'status': 'ready',
        'adapter_method': method['method'] if method else 'unconfigured', 'released_at': timeutil.now(),
        'contract_starts_at': starts, 'contract_ends_at': r['ends_at']})
    conn.execute("update reservations set status='active' where id=%s", (r['id'],))
    _event(conn, s['id'], 'console_released')
    return s


def join(user, reservation_id, input_device: str, ip: str, ua: str) -> dict:
    if input_device not in ('keyboard_mouse', 'gamepad'):
        raise AppError(422, 'validation_error', 'Escolha teclado e mouse ou controle.')
    n = timeutil.now()
    with tx() as conn:
        r0 = conn.execute('''select r.user_id, r.starts_at, r.ends_at, r.status, p.status p_status from reservations r
                             left join console_preparations p on p.reservation_id=r.id where r.id=%s''', (reservation_id,)).fetchone()
    # Preparação em andamento vale mesmo após o fim original: o tempo do cliente só começa com o console pronto.
    if (r0 and str(r0['user_id']) == user.user_id and r0['status'] == 'confirmed' and r0['starts_at'] <= n
            and (n < r0['ends_at'] or r0['p_status'] == 'pending')):
        # Console precisa estar pronto (acordado, jogo aberto). Transação própria: a falha fica registrada.
        state = preparation.ensure_now(reservation_id)
        if state == 'pending':
            raise AppError(409, 'console_preparing', 'Estamos ligando o console e abrindo o jogo. Seu tempo só começa a contar '
                           'quando ele estiver pronto; você entra automaticamente.')
        if state == 'failed':
            raise AppError(409, 'console_unavailable', 'O console não ficou pronto por um problema técnico. Seu tempo não foi '
                           'consumido: a equipe foi avisada e vai remarcar ou reembolsar sua reserva.')
    with tx() as conn:
        if input_device == 'keyboard_mouse':
            require_enabled(conn, 'keyboard_mouse_enabled', 'Jogar com teclado e mouse está desativado no momento. Use um controle.')
        r = conn.execute('select * from reservations where id=%s for update', (reservation_id,)).fetchone()
        if not r or str(r['user_id']) != user.user_id:
            raise not_found('Reserva não encontrada.')
        if r['status'] == 'needs_resolution':
            raise AppError(409, 'console_unavailable', r['resolution_notes'] or 'Reserva em resolução pela equipe.')
        if r['status'] not in ('confirmed', 'active'):
            raise forbidden('Reserva sem pagamento confirmado ou já encerrada.', code='reservation_not_active')
        if n < r['starts_at']:
            raise AppError(409, 'too_early', 'Sua sessão ainda não começou.', {'starts_at': r['starts_at'].isoformat()})
        if n >= r['ends_at']:
            raise AppError(409, 'session_over', 'O período contratado já terminou.')
        other = conn.execute("""select id from game_sessions where console_id=%s and status in ('ready','active')
                                and reservation_id<>%s""", (r['console_id'], r['id'])).fetchone()
        if other:
            raise conflict('console_busy', 'O console ainda está em uso pela sessão anterior. Aguarde alguns instantes.')
        s = prepare_session(conn, r)
        r = conn.execute('select * from reservations where id=%s', (r['id'],)).fetchone()   # fim pode ter ganho o tempo extra
        s = conn.execute('select * from game_sessions where id=%s for update', (s['id'],)).fetchone()
        if s['status'] not in ('ready', 'active'):
            raise forbidden('Sessão encerrada.', code='session_over')
        # Revoga tokens anteriores (reconexão/outra aba): somente um controlador ativo.
        conn.execute("""update session_input_tokens set revoked_at=%s, revoke_reason='reconnected'
                        where session_id=%s and revoked_at is null""", (n, s['id']))
        conn.execute("update session_connections set disconnected_at=%s, disconnect_reason='replaced' where session_id=%s and disconnected_at is null",
                     (n, s['id']))
        token = security.new_token()
        insert(conn, 'session_input_tokens', {'session_id': s['id'], 'user_id': user.user_id, 'reservation_id': r['id'],
                                              'console_id': r['console_id'], 'token_hash': security.sha256(token),
                                              'expires_at': r['ends_at']})
        connection = insert(conn, 'session_connections', {'session_id': s['id'], 'ip': ip, 'user_agent': (ua or '')[:300]})
        conn.execute("""update game_sessions set status='active', input_device=%s, first_connected_at=coalesce(first_connected_at,%s),
                        last_connected_at=%s where id=%s""", (input_device, n, n, s['id']))
        _event(conn, s['id'], 'joined', {'input_device': input_device})
        ref = console_ref(conn, r['console_id'])
    adapter = get_adapter(ref.method)
    try:
        stream = adapter.start_stream(ref, str(s['id']))
    except AdapterError as e:
        with tx() as conn:
            _event(conn, s['id'], 'stream_error', {'code': e.code})
            insert(conn, 'service_incidents', {'console_id': r['console_id'], 'reservation_id': r['id'], 'kind': 'stream_failure',
                                               'description': f'Falha ao iniciar stream: {e.code}'})
        raise AppError(503, 'stream_unavailable', 'Não foi possível iniciar a transmissão. O suporte foi notificado; '
                       'o tempo perdido por falha da plataforma será compensado conforme a política.')
    return {'session_id': str(s['id']), 'input_token': token, 'connection_id': str(connection['id']), 'contract_ends_at': r['ends_at'].isoformat(),
            'server_time': n.isoformat(), 'simulated': adapter.simulated, 'stream': stream.to_dict()}


def _token_session(conn, session_id, token: str) -> dict:
    n = timeutil.now()
    t = conn.execute("""select t.*, s.status s_status, s.contract_ends_at from session_input_tokens t
                        join game_sessions s on s.id=t.session_id where t.token_hash=%s""", (security.sha256(token or ''),)).fetchone()
    if not t or str(t['session_id']) != str(session_id):
        raise forbidden('Token de controle inválido.', code='invalid_input_token')
    if t['revoked_at'] or t['expires_at'] <= n or t['s_status'] != 'active' or t['contract_ends_at'] <= n:
        raise forbidden('Controle revogado: sessão encerrada ou token expirado.', code='input_revoked')
    return t


def webrtc_offer(session_id, token: str, offer: dict) -> dict:
    """Vídeo do console no navegador: só quem tem o token de controle válido da sessão recebe a transmissão."""
    if not isinstance(offer, dict) or offer.get('type') != 'offer' or not isinstance(offer.get('sdp'), str) or len(offer['sdp']) > 20000:
        raise AppError(400, 'invalid_offer', 'Oferta de vídeo inválida.')
    security.rate_limit(f'webrtc:{session_id}', 20, 60)
    with tx() as conn:
        t = _token_session(conn, session_id, token)
        ref = console_ref(conn, t['console_id'])
        max_kbps = int(get_settings(conn).get('player_video_max_kbps') or 4000)   # Parâmetros do painel
    adapter = get_adapter(ref.method)
    try:
        try:
            res = adapter.webrtc_offer(ref, str(session_id), {'type': 'offer', 'sdp': offer['sdp']}, max_kbps)
        except AdapterError as e:
            if e.code != 'input_revoked':
                raise
            # O agente perdeu a associação com a sessão (reinício, queda da conexão com o console…). O token acabou
            # de ser validado aqui — a API é a autoridade —, então reativa a sessão no agente e tenta uma vez mais.
            adapter.start_stream(ref, str(session_id))
            res = adapter.webrtc_offer(ref, str(session_id), {'type': 'offer', 'sdp': offer['sdp']}, max_kbps)
    except AdapterError as e:
        status = 501 if e.code == 'not_implemented' else 503
        raise AppError(status, 'video_unavailable', e.message)
    answer = (res.data or {}).get('answer') or {}
    if not res.ok or answer.get('type') != 'answer' or not answer.get('sdp'):
        raise AppError(503, 'video_unavailable', res.message or 'O agente do console não conseguiu iniciar o vídeo.')
    return {'answer': {'type': 'answer', 'sdp': answer['sdp']}, 'message': res.message}


def send_input(session_id, token: str, command: dict) -> dict:
    security.rate_limit(f'input:{session_id}', 3600, 60)  # ~60 comandos/s (botões + analógicos)
    with tx() as conn:
        t = _token_session(conn, session_id, token)
        if str((command or {}).get('name', '')).lower() == 'share' and not get_settings(conn).get('share_button_enabled', False):
            raise AppError(400, 'blocked_command', 'O botão Share está bloqueado nesta plataforma.')
        ref = console_ref(conn, t['console_id'])
    adapter = get_adapter(ref.method)
    try:
        try:
            res = adapter.send_input(ref, str(session_id), command)
        except AdapterError as e:
            if e.code != 'input_revoked':
                raise
            # Token válido aqui (autoridade é a API): o agente só perdeu a associação — reativa e reenvia uma vez.
            adapter.start_stream(ref, str(session_id))
            res = adapter.send_input(ref, str(session_id), command)
    except AdapterError as e:
        status = 400 if e.code in ('invalid_command', 'blocked_command') else 403
        raise AppError(status, e.code, e.message)
    return res.to_dict()


def should_standby(conn, ref, s: dict) -> bool:
    """Hibernar ao fim da sessão: parâmetros globais + cadastro do console, sem reserva começando em breve."""
    return console_power.should_standby(conn, ref, s['console_id'], exclude_session=s['id'],
                                        exclude_reservation=s['reservation_id'])


def _continue_with_next(conn, s: dict, n):
    """Sessão contínua: o mesmo jogador tem a próxima reserva do MESMO jogo no MESMO console logo em seguida.

    A próxima reserva é antecipada para começar agora (com os minutos dela), marcada como pronta sem nova
    preparação (o console já está com o jogo aberto) e a sessão é liberada. A tela do jogador entra sozinha nela.
    """
    r1 = conn.execute('select * from reservations where id=%s', (s['reservation_id'],)).fetchone()
    r2 = conn.execute('''select * from reservations where user_id=%s and console_id=%s and game_id=%s and id<>%s
                         and status='confirmed' and starts_at >= %s and starts_at <= %s
                         and not exists (select 1 from game_sessions x where x.reservation_id=reservations.id)
                         order by starts_at limit 1 for update''',
                      (s['user_id'], s['console_id'], r1['game_id'], r1['id'], r1['starts_at'],
                       r1['blocked_until'] + timedelta(minutes=1))).fetchone()
    if not r2:
        return None
    if r2['starts_at'] > n:                              # antecipa para agora (o intervalo do anterior já foi liberado)
        conn.execute('update reservations set starts_at=%s, ends_at=%s, blocked_until=%s where id=%s',
                     (n, n + (r2['ends_at'] - r2['starts_at']), n + (r2['blocked_until'] - r2['starts_at']), r2['id']))
    conn.execute('''insert into console_preparations(reservation_id, console_id, status, attempts, last_message, ready_at, created_at)
                    values (%s,%s,'ready',0,'Continuação da sessão anterior: console já com o jogo aberto.',%s,%s)
                    on conflict (reservation_id) do update set status='ready', ready_at=excluded.ready_at,
                      last_message=excluded.last_message''', (r2['id'], r2['console_id'], n, n))
    s2 = prepare_session(conn, r2)
    _event(conn, s2['id'], 'continuation_of', {'session_id': str(s['id'])})
    scheduling.recompute_queue(conn, s['console_id'])
    return s2


def end_session(conn, s: dict, reason: str, status: str = 'ended') -> None:
    n = timeutil.now()
    if s['status'] not in ('ready', 'active'):
        return
    used = 0
    if s['first_connected_at']:
        used = int((min(n, s['contract_ends_at']) - s['first_connected_at']).total_seconds())
    conn.execute("""update game_sessions set status=%s, ended_at=%s, end_reason=%s, seconds_used=%s where id=%s""",
                 (status, n, reason, max(0, used), s['id']))
    conn.execute("update session_input_tokens set revoked_at=%s, revoke_reason=%s where session_id=%s and revoked_at is null",
                 (n, reason, s['id']))
    conn.execute("update session_connections set disconnected_at=%s, disconnect_reason='session_end' where session_id=%s and disconnected_at is null",
                 (n, s['id']))
    new_res_status = 'no_show' if reason == 'no_show' else 'completed'
    conn.execute('update reservations set status=%s where id=%s and status in (%s,%s)', (new_res_status, s['reservation_id'], 'active', 'confirmed'))
    _event(conn, s['id'], 'ended', {'reason': reason})
    owner_settlements.refresh(conn, s['reservation_id'])
    ref = console_ref(conn, s['console_id'])
    try:
        a = get_adapter(ref.method)
    except AdapterError:
        a = None
    if a is not None:
        try:
            a.revoke_input(ref, str(s['id']))
        except AdapterError:
            pass  # tokens já revogados no banco: autoridade final é o servidor
    # Reserva concluída deixa de ocupar a agenda (status fora de OCCUPYING): o restante do intervalo fica livre.
    scheduling.recompute_queue(conn, s['console_id'])
    if reason in ('user_ended', 'admin', 'failure', 'no_show'):
        scheduling.compact_queue(conn, s['console_id'])
    nxt = _continue_with_next(conn, s, n) if reason == 'time_up' else None
    if a is not None:
        try:
            # Depois de reorganizar a fila: a próxima reserva pode ter sido antecipada.
            # Continuação: o console segue ligado e com o jogo aberto (should_standby vê a nova sessão).
            a.stop_stream(ref, str(s['id']), standby=should_standby(conn, ref, s))
        except AdapterError:
            pass
    if nxt:
        _event(conn, s['id'], 'continued', {'reservation_id': str(nxt['reservation_id']), 'session_id': str(nxt['id'])})
    r = conn.execute('select r.code, g.title from reservations r join games g on g.id=r.game_id where r.id=%s', (s['reservation_id'],)).fetchone()
    notifications.notify(conn, str(s['user_id']), 'session_ended', {'jogo': r['title'], 'motivo': {
        'time_up': 'tempo contratado encerrado', 'user_ended': 'encerrada por você', 'admin': 'encerrada pela operação',
        'failure': 'falha operacional', 'no_show': 'ausência'}.get(reason, reason)},
        dedupe=f"session_ended:{s['id']}", link='/sessoes')


def user_end(user, session_id) -> None:
    with tx() as conn:
        s = conn.execute('select * from game_sessions where id=%s for update', (session_id,)).fetchone()
        if not s or str(s['user_id']) != user.user_id:
            raise not_found('Sessão não encontrada.')
        end_session(conn, s, 'user_ended')


def disconnect(user, session_id) -> None:
    with tx() as conn:
        s = conn.execute('select * from game_sessions where id=%s', (session_id,)).fetchone()
        if not s or str(s['user_id']) != user.user_id:
            raise not_found('Sessão não encontrada.')
        conn.execute("update session_connections set disconnected_at=%s, disconnect_reason='user_left' where session_id=%s and disconnected_at is null",
                     (timeutil.now(), session_id))
        conn.execute("update session_input_tokens set revoked_at=%s, revoke_reason='disconnected' where session_id=%s and revoked_at is null",
                     (timeutil.now(), session_id))
        _event(conn, session_id, 'disconnected')
        ref = console_ref(conn, s['console_id'])
    try:
        get_adapter(ref.method).revoke_input(ref, str(session_id))   # agente corta controle e vídeo desta sessão
    except AdapterError:
        pass  # token já revogado no banco: o servidor continua sendo a autoridade


def session_state(user, session_id) -> dict:
    with tx() as conn:
        s = conn.execute("""select s.*, r.code, r.minutes, r.starts_at, r.ends_at, g.title, g.slug, c.name console_name
                            from game_sessions s join reservations r on r.id=s.reservation_id join games g on g.id=r.game_id
                            join consoles c on c.id=s.console_id where s.id=%s""", (session_id,)).fetchone()
        if not s or (str(s['user_id']) != user.user_id and not user.is_staff):
            raise not_found('Sessão não encontrada.')
        ref = console_ref(conn, s['console_id'])
        live = conn.execute("""select id from session_connections where session_id=%s and disconnected_at is null
                               order by connected_at desc limit 1""", (session_id,)).fetchone()
        cont = conn.execute("""select details from session_events where session_id=%s and event_type='continued'
                               order by created_at desc limit 1""", (session_id,)).fetchone()
    n = timeutil.now()
    adapter = get_adapter(ref.method)
    try:
        metrics = adapter.get_metrics(ref, str(session_id)).to_dict()
    except AdapterError:
        metrics = None
    return {'id': str(s['id']), 'status': s['status'], 'game': s['title'], 'slug': s['slug'], 'console': s['console_name'],
            'reservation_code': s['code'], 'reservation_id': str(s['reservation_id']), 'contract_starts_at': s['contract_starts_at'].isoformat(),
            'contract_ends_at': s['contract_ends_at'].isoformat(), 'server_time': n.isoformat(),
            'remaining_seconds': max(0, int((s['contract_ends_at'] - n).total_seconds())) if s['status'] in ('ready', 'active') else 0,
            'input_device': s['input_device'], 'simulated': adapter.simulated, 'metrics': metrics, 'end_reason': s['end_reason'],
            # Sessão contínua: a próxima reserva do jogador já foi liberada; a tela entra nela sozinha.
            'continued_by': cont['details'] if cont else None,
            # Conexão (aba/aparelho) que está com o controle agora: as outras mostram o aviso de transferência.
            'connection_id': str(live['id']) if live else None}


def admin_terminate(conn, session_id, reason: str, compensation: str | None) -> None:
    s = conn.execute('select * from game_sessions where id=%s for update', (session_id,)).fetchone()
    if not s:
        raise not_found()
    end_session(conn, s, 'admin' if compensation in (None, 'none') else 'failure')
    audit_event(conn, 'session.admin_terminated', 'game_sessions', session_id, reason=reason, details={'compensation': compensation})
