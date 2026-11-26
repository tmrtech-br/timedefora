from ..core.db import all_, insert
from ..core.errors import conflict
from . import notifications


def ticket_messages(conn, ticket_id):
    return all_(conn, '''select m.id, m.body, m.is_staff, m.created_at, u.username author from support_messages m
                        join users u on u.id=m.author_user_id where m.ticket_id=%s
                        order by m.created_at, m.id''', (ticket_id,))


def reply(conn, ticket, author_id, body, *, is_staff):
    if ticket['status'] == 'closed':
        raise conflict('ticket_closed', 'Chamado encerrado. Abra um novo chamado.')
    message = insert(conn, 'support_messages', {'ticket_id': ticket['id'], 'author_user_id': author_id,
                                                'body': body, 'is_staff': is_staff})
    status = 'in_progress' if is_staff else 'open' if ticket['status'] == 'resolved' else ticket['status']
    conn.execute('update support_tickets set status=%s where id=%s', (status, ticket['id']))
    if is_staff and ticket['hidden_by_user_at'] is None:
        notifications.notify(conn, str(ticket['user_id']), 'support_reply', {'assunto': ticket['subject']},
                             dedupe=f"support:{message['id']}", link=f"/suporte/{ticket['id']}")
    return message
