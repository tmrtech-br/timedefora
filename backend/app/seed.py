"""Dados básicos (obrigatórios) e dados DEMONSTRATIVOS (opcionais, marcados is_demo).

  python -m app.seed                      # papéis, plataformas, políticas (rascunho), templates
  python -m app.seed --admin              # + superadministrador (ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_USERNAME)
  python -m app.seed --demo               # + jogos/consoles SIMULADOS, janelas e pacotes ilustrativos
  python -m app.seed --demo-queue         # + jogadores demo com reservas pagas no provedor SIMULADO (fila visível)
"""
import os
import sys
from datetime import datetime, time, timedelta

from psycopg.types.json import Jsonb

from .config import settings
from .core import security, timeutil
from .core.db import get_pool, insert, one, tx
from .migrate import MIGRATIONS_DIR

ROLES = [('client', 'Cliente', 'Catálogo, filas, compras, sessões e perfil próprios.'),
         ('operator', 'Operador', 'Operação, monitoramento, manutenção e suporte.'),
         ('admin', 'Administrador', 'Jogos, consoles, preços, disponibilidade, finanças e configurações operacionais.'),
         ('superadmin', 'Superadministrador', 'Permissões, configurações críticas e auditoria completa.')]
PLATFORMS = [('PS5', 'PlayStation 5', 'Sony', 'playstation', True), ('PS4', 'PlayStation 4', 'Sony', 'playstation', True),
             ('XBOX_SERIES', 'Xbox Series', 'Microsoft', 'xbox', False), ('XBOX_ONE', 'Xbox One', 'Microsoft', 'xbox', False),
             ('SWITCH', 'Nintendo Switch', 'Nintendo', 'nintendo', False)]

POLICIES = {
    'terms': ('Termos de Uso (rascunho)', 'RASCUNHO — requer revisão jurídica antes da operação comercial.\n\n'
              'A timedefora oferece acesso remoto e temporário a consoles físicos mediante reserva paga de um intervalo. '
              'O usuário deve manter seus dados corretos, não compartilhar a conta e respeitar as regras de uso dos jogos e plataformas. '
              'É proibido tentar acessar consoles, transmissões ou dados de terceiros.'),
    'privacy': ('Política de Privacidade (rascunho)', 'RASCUNHO — requer revisão jurídica (LGPD).\n\n'
                'Coletamos nome, nome de usuário público, e-mail, dados de reservas, pagamentos (processados pelo Mercado Pago; '
                'não armazenamos dados de cartão) e registros de segurança. Nas filas públicas exibimos somente o nome de usuário. '
                'Você pode solicitar acesso, correção, portabilidade, revogação de consentimento ou exclusão em Perfil > Privacidade.'),
    'cancellation': ('Política de Agendamento, Ausência, Atraso, Cancelamento e Reembolso (rascunho)',
                     'RASCUNHO — requer revisão jurídica (CDC, inclusive direito de arrependimento quando aplicável).\n\n'
                     '1. A compra reserva um intervalo exclusivo do console. Em modo fila o início é estimado e pode ser antecipado; '
                     'em horário fixo o início é o reservado.\n'
                     '2. Atraso do jogador não prorroga o término. É possível reconectar até o fim do intervalo. Minutos não usados não são transferidos.\n'
                     '3. Ausência (sem conexão no intervalo) é registrada como não comparecimento.\n'
                     '4. Cancelamento com pelo menos 2 horas de antecedência: reembolso integral automático. Com menos antecedência: '
                     'solicitação analisada pela equipe, respeitados os direitos legais do consumidor.\n'
                     '5. Falhas da plataforma, console ou transmissão não consomem seu tempo injustamente: oferecemos extensão '
                     '(quando houver capacidade), remarcação ou reembolso.'),
}

T = {  # code: (subject/title, text, include_email)
    'verify_email': ('Seu código de verificação timedefora', 'Olá, {nome_usuario}! Seu código é {codigo}. Ele expira em {validade}. Se você não criou uma conta, ignore este e-mail.', True),
    'email_change': ('Confirme seu novo e-mail', 'Olá, {nome_usuario}! Use o código {codigo} para confirmar a troca de e-mail. Expira em {validade}.', True),
    'password_reset': ('Recuperação de senha', 'Olá, {nome_usuario}! Para criar uma nova senha acesse: {link} (válido por {validade}). Se não foi você, ignore.', True),
    'security_alert': ('Alerta de segurança da sua conta', 'Olá, {nome_usuario}! Detectamos uma alteração ou acesso relevante na sua conta ({quando}). Se não foi você, troque sua senha e encerre as sessões no perfil.', True),
    'payment_approved': ('Pagamento aprovado — {jogo}', 'Pagamento de {valor} aprovado. Reserva {codigo}: {jogo} no {console}, {duracao}. {modo}: {inicio_previsto} até {fim_previsto}. Acompanhe em: {link}', True),
    'payment_rejected': ('Pagamento não aprovado', 'O pagamento da reserva {codigo} ({jogo}) não foi aprovado. Tente outro meio antes de a reserva provisória expirar: {link}', True),
    'hold_expired': ('Reserva provisória expirada', 'Sua reserva provisória expirou sem pagamento confirmado e o horário foi liberado.', True),
    'queue_changed': ('Sua posição na fila mudou — {jogo}', '{mensagem} Novo início previsto: {inicio_previsto}. Acompanhe: {link}', True),
    'turn_soon': ('Sua vez de jogar {jogo} está chegando!', 'Olá, {nome_usuario}! Faltam aproximadamente {minutos} minutos para sua sessão. Jogo: {jogo}. Console: {console}. Posição na fila: {posicao}. Início previsto: {inicio_previsto}. Fim previsto: {fim_previsto}. Duração: {duracao}. Prepare controle ou teclado/mouse e verifique sua conexão. Acesse a sala de espera: {link}', True),
    'turn_ready': ('{jogo} está pronto para você!', 'Sua sessão foi liberada. Tempo contratado: {duracao} (até {fim_previsto}). Acesse sua conta e clique em "Começar a jogar": {link}', True),
    'session_ending': ('Restam {restante} de sessão', 'Sua sessão de {jogo} termina em {restante}.', False),
    'session_ended': ('Sessão encerrada', 'Sua sessão de {jogo} foi encerrada ({motivo}). O controle do console foi revogado.', False),
    'console_not_ready': ('Problema técnico na sua sessão de {jogo}', 'O console {console} não ficou pronto no horário da reserva {codigo} por um problema técnico. Seu tempo NÃO foi consumido: nossa equipe já foi avisada e vai remarcar ou reembolsar sua reserva. Acompanhe: {link}', True),
    'staff_incident': ('[timedefora] Incidente: {incidente}', '{incidente}. {detalhe}. Veja e defina a compensação no painel: {link}', True),
    'console_failure': ('Problema no console', 'Detectamos uma falha no console {console}. Nossa equipe foi acionada; o tempo perdido será compensado conforme a política.', True),
    'reservation_cancelled': ('Reserva cancelada', 'A reserva {codigo} foi cancelada. Se houve pagamento, o reembolso foi solicitado.', True),
    'schedule_changed': ('Alteração na sua reserva', 'A reserva {codigo} foi alterada pela operação. Motivo: {motivo}. Acompanhe: {link}', True),
    'needs_resolution': ('Pagamento recebido após expiração', 'Recebemos o pagamento da reserva {codigo} após a expiração e o horário não estava mais disponível. Iniciamos o reembolso automático; você pode fazer uma nova reserva.', True),
    'refund_completed': ('Reembolso processado', 'O reembolso de {valor} referente à reserva {codigo} foi processado.', True),
    'cancellation_decided': ('Solicitação de cancelamento analisada', 'Sua solicitação para a reserva {codigo} foi {decisao}. Observação: {observacao}', True),
    'support_reply': ('Resposta no seu chamado', 'A equipe respondeu ao chamado "{assunto}". Veja: {link}', True),
}


def _html(text: str) -> str:
    return ('<div style="font-family:Arial,sans-serif;background:#0b0718;color:#f1ecff;padding:24px">'
            '<h1 style="color:#c026ff;font-size:22px;margin:0 0 16px">timedefora</h1>'
            f'<p style="font-size:16px;line-height:1.5">{text}</p>'
            '<p style="font-size:12px;color:#a99bd1">Mensagem automática. Não responda este e-mail.</p></div>')


def base(conn) -> None:
    for code, name, desc in ROLES:
        conn.execute('insert into roles(code, name, description) values (%s,%s,%s) on conflict (code) do nothing', (code, name, desc))
    for code, name, man, fam, rp in PLATFORMS:
        conn.execute('''insert into platforms(code, name, manufacturer, family, remote_play_capable) values (%s,%s,%s,%s,%s)
                        on conflict (code) do nothing''', (code, name, man, fam, rp))
    for kind, (title, body) in POLICIES.items():
        version = '0.2-rascunho' if kind == 'terms' else '0.1-rascunho'
        conn.execute('''insert into policy_documents(kind, version, title, body, is_current, published_at)
                        select %s, %s, %s, %s, not exists(select 1 from policy_documents where kind=%s and is_current), now()
                        on conflict (kind, version) do nothing''', (kind, version, title, body, kind))
    for code, (subj, text, email) in T.items():
        conn.execute('''insert into notification_templates(code, channel, subject, body_text) values (%s,'in_app',%s,%s)
                        on conflict (code, channel) do nothing''', (code, subj, text))
        if email:
            conn.execute('''insert into notification_templates(code, channel, subject, body_text, body_html) values (%s,'email',%s,%s,%s)
                            on conflict (code, channel) do nothing''', (code, subj, text, _html(text)))
    # Em instalações novas, o seed insere os modelos depois da execução das migrations.
    conn.execute((MIGRATIONS_DIR / '030_visual_emails_transacionais.sql').read_text(encoding='utf-8'))


def admin(conn) -> None:
    email, pw, username = os.getenv('ADMIN_EMAIL'), os.getenv('ADMIN_PASSWORD'), os.getenv('ADMIN_USERNAME', 'admin')
    if not email or not pw:
        sys.exit('Defina ADMIN_EMAIL e ADMIN_PASSWORD (senha forte) para criar o superadministrador.')
    probs = security.password_problems(pw, email, username)
    if probs:
        sys.exit('Senha do admin fraca: ' + ' '.join(probs))
    u = one(conn, 'select id from users where lower(email)=lower(%s)', (email,))
    if not u:
        u = insert(conn, 'users', {'full_name': 'Administrador timedefora', 'username': username, 'email': email.lower(),
                                   'password_hash': security.hash_password(pw), 'status': 'active', 'email_verified_at': timeutil.now()})
        conn.execute('insert into notification_preferences(user_id) values (%s)', (u['id'],))
    for role in ('client', 'superadmin'):
        conn.execute('''insert into role_assignments(user_id, role_id) select %s, id from roles where code=%s
                        on conflict do nothing''', (u['id'], role))
    print('superadministrador pronto:', email, '(MFA será exigido no primeiro acesso ao painel)')


DEMO_GAMES = [
    ('gta-vi', 'GTA VI', 'PS5', ['Ação', 'Aventura', 'Mundo aberto'], '/assets/game-1.webp',
     'Viva uma nova história em um mundo aberto gigantesco, cheio de oportunidades, missões, ação e liberdade total. '
     'Jogue GTA VI na nuvem, com alta performance e sem precisar de console.', 'Jogue sem console', 'PS5-01', 1),
    ('zelda', 'Zelda', 'SWITCH', ['Aventura'], '/assets/game-2.webp', 'Uma jornada épica por um reino repleto de descobertas.',
     'Aventura épica', 'SWITCH-01', 2),
    ('god-of-war', 'God of War', 'PS5', ['Ação'], '/assets/game-3.webp', 'Combates intensos e uma história poderosa em terras mitológicas.',
     'Ação mitológica', 'PS5-02', 3),
    ('spider-man', 'Spider-Man', 'PS5', ['Ação', 'Aventura'], '/assets/game-4.webp', 'Acrobacias e aventuras por uma cidade vibrante.',
     'Herói da cidade', 'PS5-03', 4),
    ('forza', 'Forza', 'XBOX_SERIES', ['Corrida'], '/assets/game-5.webp', 'Carros esportivos em pistas e estradas cinematográficas.',
     'Velocidade máxima', 'XBOX-01', 5),
    ('ea-fc', 'EA FC', 'PS5', ['Esportes'], '/assets/game-6.webp', 'Entre em campo e dispute partidas de futebol.',
     'Futebol', 'PS5-04', 6),
]
DEMO_CONSOLES = [('PS5-01', 'PS5 nº 01', 'PS5'), ('PS5-02', 'PS5 nº 02', 'PS5'), ('PS5-03', 'PS5 nº 03', 'PS5'),
                 ('PS5-04', 'PS5 nº 04', 'PS5'), ('SWITCH-01', 'Nintendo Switch nº 01', 'SWITCH'), ('XBOX-01', 'Xbox nº 01', 'XBOX_SERIES')]


def demo(conn) -> None:
    ag = one(conn, "select id from console_agents where name='agente-simulado-01'")
    if not ag:
        ag = insert(conn, 'console_agents', {'name': 'agente-simulado-01', 'host_name': 'simulador', 'is_simulated': True, 'status': 'online',
                                             'description': 'Agente SIMULADO para desenvolvimento. Não controla consoles reais.'})
    n = timeutil.now()
    for code, name, plat in DEMO_CONSOLES:
        c = one(conn, 'select id from consoles where code=%s', (code,))
        if c:
            continue
        pl = one(conn, 'select id, manufacturer from platforms where code=%s', (plat,))
        c = insert(conn, 'consoles', {'code': code, 'name': name, 'platform_id': pl['id'], 'manufacturer': pl['manufacturer'],
                                      'status': 'online', 'agent_id': ag['id'], 'description': 'Console SIMULADO (demonstração).'})
        insert(conn, 'console_connection_configs', {
            'console_id': c['id'], 'method': 'simulated', 'agent_id': ag['id'], 'connection_status': 'online',
            'video_validated_at': n, 'audio_validated_at': n, 'control_validated_at': n, 'heartbeat_validated_at': n,
            'validated_at': n, 'last_check_at': n})
        for t in ('connection', 'video_audio', 'controls', 'heartbeat'):
            insert(conn, 'console_connection_tests', {'console_id': c['id'], 'test_type': t, 'result': 'passed', 'simulated': True,
                                                      'message': 'Validação SIMULADA no seed de demonstração.'})
        conn.execute('update consoles set is_published=true where id=%s', (c['id'],))
    for slug, title, plat, genres, img, desc, short, console_code, rank in DEMO_GAMES:
        g = one(conn, 'select id from games where slug=%s', (slug,))
        if not g:
            g = insert(conn, 'games', {'slug': slug, 'title': title, 'short_description': short, 'description': desc,
                                       'cover_url': img, 'banner_url': '/assets/hero-characters.webp' if slug == 'gta-vi' else img,
                                       'status': 'published', 'min_minutes': 10, 'max_minutes': 120, 'is_demo': True,
                                       'featured_manual': slug == 'gta-vi', 'featured_rank': rank, 'age_rating': '16',
                                       'image_rights_notes': 'Arte derivada da imagem de referência fornecida pelo cliente. Substituir por material licenciado antes de publicar.',
                                       'commercial_license_status': 'not_verified'})
            pl = one(conn, 'select id from platforms where code=%s', (plat,))
            insert(conn, 'game_platforms', {'game_id': g['id'], 'platform_id': pl['id']})
            for gn in genres:
                gid = one(conn, '''insert into genres(slug, name) values (%s,%s) on conflict (slug) do update set name=genres.name returning id''',
                          (gn.lower().replace(' ', '-'), gn))['id']
                conn.execute('insert into game_genres(game_id, genre_id) values (%s,%s) on conflict do nothing', (g['id'], gid))
        c = one(conn, 'select id from consoles where code=%s', (console_code,))
        # Janelas diárias 08:00–23:59 (Fortaleza) por 7 dias a partir de hoje
        today = timeutil.local(n).date()
        for d in range(0, 7):
            day = today + timedelta(days=d)
            s = datetime.combine(day, time(8, 0), tzinfo=timeutil.TZ)
            e = datetime.combine(day, time(23, 59), tzinfo=timeutil.TZ)
            if d == 0 and n > s:
                s = timeutil.local(n).replace(second=0, microsecond=0)
            if not one(conn, "select 1 from console_game_assignments where console_id=%s and status='active' and starts_at < %s and ends_at > %s", (c['id'], e, s)):
                insert(conn, 'console_game_assignments', {'console_id': c['id'], 'game_id': g['id'], 'starts_at': s, 'ends_at': e,
                                                          'notes': 'Janela demonstrativa'})
    for name, minutes, cents in (('10 minutos', 10, 3000), ('30 minutos', 30, 5000)):
        conn.execute('''insert into price_packages(name, minutes, price_cents, sort_order)
                        select %s, %s, %s, %s where not exists (select 1 from price_packages where minutes=%s and game_id is null and console_id is null)''',
                     (name, minutes, cents, minutes, minutes))
    print('dados demonstrativos (SIMULADOS) criados')


def demo_queue() -> None:
    """Cria jogadores demo e reservas pagas pelo provedor SIMULADO, usando o motor real de reservas."""
    from .core.deps import Principal
    from .services import payments, scheduling
    if settings.payment_provider != 'simulated':
        sys.exit('demo-queue exige PAYMENT_PROVIDER=simulated')
    names = ['PlayerAlpha', 'GamerBR', 'Player2026', 'NeonRider', 'RetroKid']
    with tx() as conn:
        g = one(conn, "select id from games where slug='gta-vi'")
    for i, nm in enumerate(names):
        with tx() as conn:
            u = one(conn, 'select id from users where username=%s', (nm,))
            if not u:
                u = insert(conn, 'users', {'full_name': f'Jogador Demo {i + 1}', 'username': nm, 'email': f'{nm.lower()}@demo.locaplay.invalid',
                                           'password_hash': None, 'status': 'active', 'email_verified_at': timeutil.now()})
                conn.execute("insert into role_assignments(user_id, role_id) select %s, id from roles where code='client'", (u['id'],))
        p = Principal(str(u['id']), '', nm, nm, '', 'active', True, {'client'})
        with tx(actor_id=p.user_id) as conn:
            if one(conn, "select 1 from reservations where user_id=%s and status in ('confirmed','active')", (u['id'],)):
                continue
            r = scheduling.create_reservation(p, g['id'], 30 if i % 2 == 0 else 10, 'queue', None, None, True, conn=conn)
        pay = payments.start_checkout(p, r['id'], 'pix')
        payments.simulate_provider_notification(pay['payment_id'], 'approved', p)
    print('fila demonstrativa criada (pagamentos SIMULADOS)')


if __name__ == '__main__':
    settings.validate()
    with tx() as conn:
        base(conn)
        if '--admin' in sys.argv:
            admin(conn)
        if '--demo' in sys.argv:
            demo(conn)
    if '--demo-queue' in sys.argv:
        demo_queue()
    print('seed concluído')
