"""Repasse ao proprietário: agenda e envia o valor (Pix ou conta bancária cadastrados no portal).

- Agendado `PAYOUT_DELAY` após o fim de uma sessão concluída sem problemas (apuração "eligible").
- Enviado por um provedor configurável (parâmetro `payout_provider`). Hoje só existe "manual": o repasse fica
  "aguardando pagamento manual" no admin, que mostra o destino completo; a equipe paga pelo banco e marca como pago
  (com comprovante). Um provedor com API de envio de Pix (Efí, Asaas, Inter, Stark Bank…) entra implementando
  `send(payout, destination)`, sem mudar o restante.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from ..core import security, timeutil
from ..core.db import audit_event, insert
from ..core.errors import conflict, not_found
from . import notifications
from .settings_store import get_settings

log = logging.getLogger('locaplay.payouts')
PAYOUT_DELAY = timedelta(minutes=10)


class ManualProvider:
    """Sem API de envio: a equipe paga pelo banco e confirma no admin."""
    name = 'manual'

    def send(self, payout: dict, destination: dict) -> tuple[str, str | None]:
        return 'awaiting_manual', None


PROVIDERS = {'manual': ManualProvider()}


def provider(conn):
    return PROVIDERS.get(str(get_settings(conn).get('payout_provider') or 'manual'), PROVIDERS['manual'])


def destination(conn, owner_user_id) -> dict | None:
    d = conn.execute('select kind, masked, destination_enc from owner_payout_destinations where user_id=%s', (owner_user_id,)).fetchone()
    if not d:
        return None
    return {'kind': d['kind'], 'masked': d['masked'], 'data': json.loads(security.decrypt(d['destination_enc']))}


def schedule_due(conn, n=None) -> int:
    """Cria o repasse das apurações liberadas cujo atraso já passou (uma vez por apuração)."""
    n = n or timeutil.now()
    rows = conn.execute('''
        select st.id, st.owner_user_id, st.owner_cents, s.ended_at from owner_settlements st
        join game_sessions s on s.id=st.session_id
        where st.status='eligible' and st.owner_cents > 0 and s.ended_at <= %s
          and not exists (select 1 from owner_payouts p where p.settlement_id=st.id)
        for update of st skip locked''', (n - PAYOUT_DELAY,)).fetchall()
    for st in rows:
        d = destination(conn, st['owner_user_id'])
        insert(conn, 'owner_payouts', {
            'settlement_id': st['id'], 'owner_user_id': st['owner_user_id'], 'amount_cents': st['owner_cents'],
            'destination_kind': d['kind'] if d else None, 'destination_masked': d['masked'] if d else None,
            'status': 'scheduled' if d else 'waiting_destination', 'scheduled_for': n, 'provider': provider(conn).name})
    return len(rows)


def dispatch(conn, n=None) -> int:
    """Envia os repasses agendados pelo provedor configurado (ou deixa para pagamento manual)."""
    n = n or timeutil.now()
    # Proprietário cadastrou o destino depois: o repasse volta para a fila de envio.
    conn.execute('''update owner_payouts p set status='scheduled', destination_kind=d.kind, destination_masked=d.masked, updated_at=%s
                    from owner_payout_destinations d where d.user_id=p.owner_user_id and p.status='waiting_destination' ''', (n,))
    rows = conn.execute("select * from owner_payouts where status='scheduled' and scheduled_for <= %s for update skip locked",
                        (n,)).fetchall()
    prov = provider(conn)
    for p in rows:
        d = destination(conn, p['owner_user_id'])
        try:
            status, ref = prov.send(p, d)
        except Exception as e:  # provedor fora do ar: tenta de novo no próximo ciclo
            conn.execute('''update owner_payouts set attempts=attempts+1, last_error=%s, status=case when attempts >= 5 then 'failed' else status end,
                            updated_at=%s where id=%s''', (str(e)[:300], n, p['id']))
            continue
        conn.execute('update owner_payouts set status=%s, provider=%s, provider_ref=%s, attempts=attempts+1, updated_at=%s where id=%s',
                     (status, prov.name, ref, n, p['id']))
        if status == 'paid':
            _settle(conn, p, n, None)
    return len(rows)


def _settle(conn, p: dict, n, by_user) -> None:
    conn.execute("update owner_payouts set status='paid', paid_at=%s, paid_by=%s, updated_at=%s where id=%s", (n, by_user, n, p['id']))
    conn.execute("update owner_settlements set status='paid', updated_at=%s where id=%s", (n, p['settlement_id']))
    game = conn.execute('''select g.title from owner_settlements st join reservations r on r.id=st.reservation_id
                           join games g on g.id=r.game_id where st.id=%s''', (p['settlement_id'],)).fetchone()
    notifications.notify(conn, str(p['owner_user_id']), 'owner_payout_paid',
                         {'valor': timeutil.money(p['amount_cents']), 'destino': p['destination_masked'] or 'sua conta',
                          'jogo': game['title'] if game else ''},
                         dedupe=f"owner_payout_paid:{p['id']}", link='/proprietario#recebimento')


def mark_paid(conn, payout_id, by_user, proof_url: str | None, notes: str) -> dict:
    p = conn.execute('select * from owner_payouts where id=%s for update', (payout_id,)).fetchone()
    if not p:
        raise not_found('Repasse não encontrado.')
    if p['status'] == 'paid':
        raise conflict('already_paid', 'Este repasse já foi pago.')
    if p['status'] == 'waiting_destination':
        raise conflict('no_destination', 'O proprietário ainda não cadastrou Pix ou conta bancária.')
    n = timeutil.now()
    conn.execute('update owner_payouts set proof_url=%s, notes=%s where id=%s', (proof_url, notes, p['id']))
    _settle(conn, p, n, by_user)
    audit_event(conn, 'owner.payout_paid', 'owner_payouts', p['id'], reason=notes,
                details={'amount_cents': p['amount_cents'], 'proof_url': proof_url})
    return {**p, 'status': 'paid'}
