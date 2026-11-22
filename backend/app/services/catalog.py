"""Consultas de catálogo: status do jogo, popularidade real, destaque e seções do dashboard."""
from datetime import timedelta

from ..core import timeutil
from . import scheduling
from .settings_store import get_settings

STATUS_LABEL = {'available': 'Disponível', 'in_use': 'Em uso', 'queue_open': 'Fila aberta', 'scheduled': 'Agendado',
                'unavailable': 'Indisponível', 'maintenance': 'Manutenção', 'closed': 'Encerrado'}


def platform_labels(conn, game_id) -> list[dict]:
    return conn.execute('''select p.code, p.name, p.family from game_platforms gp join platforms p on p.id=gp.platform_id
                           where gp.game_id=%s order by p.name''', (game_id,)).fetchall()


def genre_labels(conn, game_id) -> list[str]:
    return [r['name'] for r in conn.execute('''select g.name from game_genres gg join genres g on g.id=gg.genre_id
                                               where gg.game_id=%s order by g.name''', (game_id,)).fetchall()]


def game_live(conn, game: dict) -> dict:
    """Status, fila e estimativa calculados a partir de dados reais."""
    n = timeutil.now()
    if game['status'] != 'published' or game['deleted_at']:
        return {'status': 'closed', 'status_label': STATUS_LABEL['closed'], 'queue_size': 0, 'estimated_wait_minutes': None}
    consoles = scheduling.eligible_consoles(conn, game['id'])
    queue_size = 0
    playing = False
    for c in consoles:
        q = conn.execute("""select count(*) filter (where status in ('next','waiting')) waiting,
                                   count(*) filter (where status='playing') playing
                            from queue_entries where console_id=%s and status in ('playing','next','waiting')""", (c['id'],)).fetchone()
        queue_size += q['waiting'] + q['playing']
        playing = playing or q['playing'] > 0
    offers = scheduling.offered_minutes(conn, game)
    wait = None
    start = None
    if consoles and offers:
        slots = scheduling.find_slots(conn, game['id'], offers[0]['minutes'], 'queue')
        if slots:
            start = slots[0].start
            wait = max(0, int((start - n).total_seconds() // 60))
    if not consoles:
        maint = conn.execute("""select 1 from console_game_assignments a join consoles c on c.id=a.console_id
                                where a.game_id=%s and a.status='active' and a.ends_at > %s and c.status='maintenance' limit 1""",
                             (game['id'], n)).fetchone()
        key = 'maintenance' if maint else 'unavailable'
    elif start is None:
        key = 'unavailable'
    elif start > n + timedelta(minutes=60) and queue_size == 0:
        key = 'scheduled'
    elif queue_size == 0:
        key = 'available'
    elif playing and queue_size == 1:
        key = 'in_use'
    else:
        key = 'queue_open'
    return {'status': key, 'status_label': STATUS_LABEL[key], 'queue_size': queue_size, 'estimated_wait_minutes': wait,
            'next_start_at': start.isoformat() if start else None,
            'starting_price_cents': min((o['price_cents'] for o in offers), default=None)}


def popularity(conn, days: int, metric: str) -> dict:
    since = timeutil.now() - timedelta(days=days)
    if metric == 'revenue':
        q = """select r.game_id, sum(p.amount_cents) v from payments p join reservations r on r.id=p.reservation_id
               where p.status='approved' and p.approved_at >= %s group by r.game_id"""
    elif metric == 'sessions_sold':
        q = """select game_id, count(*) v from reservations where status in ('confirmed','active','completed','no_show')
               and confirmed_at >= %s group by game_id"""
    else:
        q = """select r.game_id, sum(s.seconds_used) v from game_sessions s join reservations r on r.id=s.reservation_id
               where s.ended_at >= %s group by r.game_id"""
    return {str(r['game_id']): float(r['v'] or 0) for r in conn.execute(q, (since,)).fetchall()}


def card(conn, g: dict) -> dict:
    live = game_live(conn, g)
    plats = platform_labels(conn, g['id'])
    return {'id': str(g['id']), 'slug': g['slug'], 'title': g['title'], 'cover_url': g['cover_url'],
            'banner_url': g['banner_url'], 'short_description': g['short_description'],
            'platforms': [{'code': p['code'], 'name': p['name'], 'family': p['family']} for p in plats],
            'genres': genre_labels(conn, g['id']), 'release_date': g['release_date'].isoformat() if g['release_date'] else None,
            'is_demo': g['is_demo'], **live}


def published_games(conn) -> list[dict]:
    return conn.execute("select * from games where status='published' and deleted_at is null order by featured_rank nulls last, title").fetchall()


def featured(conn, games: list[dict]) -> tuple[dict | None, str]:
    manual = [g for g in games if g['featured_manual']]
    if manual:
        return manual[0], 'Destaque da semana'
    st = get_settings(conn)
    pop = popularity(conn, int(st['featured_window_days']), st['featured_metric'])
    if pop:
        best = max(games, key=lambda g: pop.get(str(g['id']), 0), default=None)
        if best is not None and pop.get(str(best['id']), 0) > 0:
            return best, 'Mais jogado da semana'
    return (games[0] if games else None), 'Em destaque'
