"""Rotas públicas: home/dashboard, catálogo, página do jogo, filas públicas, políticas."""
import os

from fastapi import APIRouter, Depends, Query, Request, Response

from ..core import security, timeutil
from ..core.db import all_, one, tx
from ..core.deps import Principal, client_ip, optional_user
from ..core.errors import not_found
from ..services import catalog, scheduling
from ..services.settings_store import PUBLIC_FLAGS, disabled_platforms, get_settings
from .common import jsonable

router = APIRouter(tags=['catálogo'])


@router.get('/catalog/home')
def home(p: Principal | None = Depends(optional_user)):
    with tx() as conn:
        games = catalog.published_games(conn)
        feat, label = catalog.featured(conn, games)
        cards = [catalog.card(conn, g) for g in games]
        st = get_settings(conn)
        out = {'server_time': timeutil.now().isoformat(), 'demo_mode': any(g['is_demo'] for g in games),
               'sales_paused': bool(st['sales_paused']), 'support_hours_text': st['support_hours_text'],
               'featured': None, 'featured_games': cards[:6], 'live_queue': None, 'sections': {}}
        if feat:
            fc = next(c for c in cards if c['id'] == str(feat['id']))
            packages = scheduling.offered_minutes(conn, feat)
            consoles = scheduling.eligible_consoles(conn, feat['id'])
            console_info = None
            if consoles:
                c = consoles[0]
                console_info = {'name': c['name'], 'available': fc['status'] in ('available', 'queue_open', 'in_use'),
                                'status_label': 'disponível' if fc['status'] in ('available', 'queue_open', 'in_use') else fc['status_label'].lower()}
            out['featured'] = {**fc, 'highlight_label': label, 'description': feat['description'],
                               'packages': [{'minutes': x['minutes'], 'price_cents': x['price_cents']} for x in packages],
                               'console': console_info}
            # Fila ao vivo do jogo em destaque (console com mais movimento)
            best_q, best_c = [], None
            for c in consoles:
                q = scheduling.public_queue(conn, c['id'], p.user_id if p else None)
                if len(q) >= len(best_q):
                    best_q, best_c = q, c
            if best_c is not None:
                mine = next((x for x in best_q if x['is_me']), None)
                out['live_queue'] = {
                    'game_title': feat['title'], 'game_slug': feat['slug'], 'cover_url': feat['cover_url'],
                    'console_name': best_c['name'],
                    'playing': next((x['username'] for x in best_q if x['status'] == 'playing'), None),
                    'next': next((x['username'] for x in best_q if x['status'] == 'next'), None),
                    'my_position': mine['position'] if mine else None,
                    'estimated_wait_minutes': fc['estimated_wait_minutes'], 'size': len(best_q)}
        pop = catalog.popularity(conn, 7, 'minutes_played')
        n = timeutil.now()
        promo_ids = {str(r['game_id']) for r in all_(conn, '''select distinct game_id from price_packages where active and is_promotion
                     and game_id is not null and (valid_until is null or valid_until > %s)''', (n,))}
        favs = set()
        if p:
            favs = {str(r['game_id']) for r in all_(conn, 'select game_id from favorites where user_id=%s', (p.user_id,))}
        out['sections'] = {
            'available_now': [c for c in cards if c['status'] in ('available', 'in_use', 'queue_open')][:12],
            'most_played_week': sorted([c for c in cards if pop.get(c['id'])], key=lambda c: -pop[c['id']])[:12],
            'launches': sorted([c for c in cards if c['release_date']], key=lambda c: c['release_date'], reverse=True)[:12],
            'coming_soon': [c for c in cards if c['status'] == 'scheduled'][:12],
            'promotions': [c for c in cards if c['id'] in promo_ids][:12],
            'favorites': [c for c in cards if c['id'] in favs][:12],
        }
        if p:
            recent = all_(conn, '''select distinct on (r.game_id) r.game_id from reservations r where r.user_id=%s
                                   and r.status in ('completed','active','confirmed') order by r.game_id, r.created_at desc''', (p.user_id,))
            ids = {str(r['game_id']) for r in recent}
            out['sections']['recent'] = [c for c in cards if c['id'] in ids][:12]
            # Recomendações: mesmos gêneros dos jogos já jogados/favoritos
            liked = {g for c in cards if c['id'] in ids | favs for g in c['genres']}
            out['sections']['recommended'] = [c for c in cards if c['id'] not in ids | favs and set(c['genres']) & liked][:12]
    return out


@router.get('/catalog/games')
def games(q: str = '', platform: str = '', genre: str = '', availability: str = '', max_price_cents: int | None = None,
          sort: str = Query('popularity', pattern='^(popularity|price|title|release)$')):
    with tx() as conn:
        cards = [catalog.card(conn, g) for g in catalog.published_games(conn)]
        pop = catalog.popularity(conn, 30, 'minutes_played')
    ql = q.strip().lower()
    if ql:
        cards = [c for c in cards if ql in c['title'].lower() or any(ql in g.lower() for g in c['genres'])]
    if platform:
        cards = [c for c in cards if any(p['family'] == platform or p['code'] == platform for p in c['platforms'])]
    if genre:
        cards = [c for c in cards if genre in c['genres']]
    if availability:
        cards = [c for c in cards if c['status'] == availability]
    if max_price_cents is not None:
        cards = [c for c in cards if c['starting_price_cents'] is not None and c['starting_price_cents'] <= max_price_cents]
    key = {'popularity': lambda c: (-pop.get(c['id'], 0), c['title']), 'title': lambda c: c['title'],
           'price': lambda c: (c['starting_price_cents'] is None, c['starting_price_cents'] or 0),
           'release': lambda c: c['release_date'] or ''}[sort]
    cards.sort(key=key, reverse=(sort == 'release'))
    return cards


@router.get('/net/ping')
def net_ping():
    """Usado pelo teste de conexão da sala de espera (latência até o servidor)."""
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})


@router.get('/net/download')
def net_download(request: Request, kb: int = Query(1024, ge=64, le=4096)):
    """Bytes aleatórios (não compressíveis) para estimar a velocidade de download até o servidor."""
    security.rate_limit(f'net:{client_ip(request)}', 30, 600)
    return Response(os.urandom(kb * 1024), media_type='application/octet-stream',
                    headers={'Cache-Control': 'no-store', 'Content-Encoding': 'identity'})


@router.get('/features')
def features():
    """Parâmetros liga/desliga públicos, para a interface esconder o que estiver desativado (o servidor também bloqueia)."""
    with tx() as conn:
        st = get_settings(conn)
    return {k: st[k] for k in PUBLIC_FLAGS}


@router.get('/catalog/filters')
def filters():
    with tx() as conn:
        off = disabled_platforms(conn)
        return {'platforms': jsonable(all_(conn, 'select code, name, family from platforms where not (code = any(%s)) order by name', (off,))),
                'genres': [r['name'] for r in all_(conn, 'select name from genres order by name')],
                'statuses': catalog.STATUS_LABEL}


@router.get('/catalog/games/{slug}')
def game_detail(slug: str, p: Principal | None = Depends(optional_user)):
    with tx() as conn:
        g = one(conn, f"select * from games where slug=%s and deleted_at is null and status='published' and {catalog.PLATFORM_ON}",
                (slug, disabled_platforms(conn)))
        if not g:
            raise not_found('Jogo não encontrado.')
        out = catalog.card(conn, g)
        out.update({'description': g['description'], 'age_rating': g['age_rating'], 'requirements': g['requirements'],
                    'trailer_url': g['trailer_url'] if g['trailer_licensed'] else None,
                    'min_minutes': g['min_minutes'], 'max_minutes': g['max_minutes'],
                    'commercially_licensed': g['commercial_license_status'] == 'authorized'})
        offers = scheduling.offered_minutes(conn, g)
        out['packages'] = [{'minutes': x['minutes'], 'price_cents': x['price_cents'], 'promotion': x['promo']} for x in offers]
        out['rate_cents_per_minute'] = get_settings(conn)['booking_rate_cents_per_minute']
        out['availability'] = scheduling.availability_summary(conn, g, offers=offers, viewer_id=p.user_id if p else None)
        ch = one(conn, """select provider, channel_name, external_url, status from streaming_channels
                          where status<>'disabled' and (game_id=%s or console_id in
                          (select console_id from console_game_assignments where game_id=%s and status='active'
                           and starts_at <= %s and ends_at > %s)) order by (status='live') desc limit 1""",
                 (g['id'], g['id'], timeutil.now(), timeutil.now()))
        streams_on = bool(get_settings(conn).get('public_streams_enabled', True))
        out['public_stream'] = jsonable(ch) if ch and g['stream_rights_allowed'] and streams_on else None
        out['is_favorite'] = bool(p and one(conn, 'select 1 from favorites where user_id=%s and game_id=%s', (p.user_id, g['id'])))
        cp = one(conn, "select title, body, version from policy_documents where kind='cancellation' and is_current")
        out['cancellation_policy'] = jsonable(cp)
    return out


@router.get('/catalog/games/{slug}/quote')
def quote(slug: str, minutes: int = Query(ge=1, le=scheduling.MAX_RESERVATION_MINUTES), mode: str = 'queue', start_at: str | None = None, duration_limit: bool = False):
    """Cotação servidor: início estimado/confirmável e preço para o pacote escolhido."""
    from datetime import datetime
    with tx() as conn:
        g = one(conn, "select * from games where slug=%s and deleted_at is null and status='published'", (slug,))
        if not g:
            raise not_found('Jogo não encontrado.')
        try:
            s = datetime.fromisoformat(start_at) if start_at else None
        except ValueError:
            return {'available': False, 'message': 'Informe data e hora válidas.'}
        if mode not in ('queue', 'scheduled') or (mode == 'scheduled' and (not s or not s.tzinfo or s.second or s.microsecond)):
            return {'available': False, 'message': 'Selecione um modo e um horário de início válidos.'}
        flags = get_settings(conn)
        if flags['sales_paused'] or not flags[f'{mode}_mode_enabled']:
            return {'available': False, 'message': 'Reservas neste modo estão temporariamente indisponíveis.'}
        if duration_limit and mode == 'scheduled':
            # A duração é contínua até a primeira reserva, bloqueio ou fechamento (cálculo direto: era lento).
            return {'start_at': start_at, 'max_minutes': scheduling.max_scheduled_minutes(conn, g['id'], s)}
        slots = scheduling.find_slots(conn, g['id'], minutes, mode, s)
        if not slots:
            return {'available': False, 'message': scheduling.explain_unavailable(conn, g['id'], minutes, mode, s)}
        for sl in slots:
            plat = one(conn, 'select platform_id from consoles where id=%s', (sl.console_id,))['platform_id']
            pkg = scheduling.resolve_package(conn, g, sl.console_id, plat, minutes, sl.start)
            if pkg:
                break
        else:
            return {'available': False, 'message': 'Duração indisponível para este horário.'}
        return {'available': True, 'console_name': sl.console_name, 'starts_at': sl.start.isoformat(), 'ends_at': sl.end.isoformat(),
                'window_ends_at': sl.window_end.isoformat(), 'price_cents': pkg['price_cents'], 'mode': mode,
                'estimate_notice': 'Início estimado: pode ser antecipado se a fila andar; nunca é atrasado após a confirmação.'
                if mode == 'queue' else 'Horário fixo reservado após a confirmação do pagamento.'}


@router.get('/queues/console/{console_id}')
def console_queue(console_id: str, p: Principal | None = Depends(optional_user)):
    with tx() as conn:
        c = one(conn, 'select id, name from consoles where id=%s and is_published', (console_id,))
        if not c:
            raise not_found()
        return {'console': c['name'], 'server_time': timeutil.now().isoformat(),
                'queue': scheduling.public_queue(conn, c['id'], p.user_id if p else None)}


@router.get('/policies/{kind}')
def policy(kind: str):
    with tx() as conn:
        d = one(conn, 'select kind, version, title, body, published_at, requires_legal_review from policy_documents where kind=%s and is_current', (kind,))
    if not d:
        raise not_found('Política não encontrada.')
    return jsonable(d)
