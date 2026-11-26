"""Provedores de pagamento (adaptador). Mercado Pago Checkout Pro reduz o escopo PCI: dados de cartão
nunca passam pela timedefora. O provedor 'simulated' existe SOMENTE para desenvolvimento e é recusado em produção."""
import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx

from ..config import settings
from ..core.errors import AppError

MP_API = 'https://api.mercadopago.com'
MP_STATUS = {'pending': 'pending', 'in_process': 'pending', 'authorized': 'pending', 'approved': 'approved',
             'rejected': 'rejected', 'cancelled': 'cancelled', 'refunded': 'refunded', 'charged_back': 'charged_back',
             'in_mediation': 'pending'}


@dataclass
class ProviderPayment:
    provider_payment_id: str
    status: str
    status_detail: str
    external_reference: str | None
    amount_cents: int
    method: str


class SimulatedProvider:
    name = 'simulated'

    def create_checkout(self, payment: dict, reservation: dict, game_title: str, method: str) -> dict:
        if settings.is_production:
            raise AppError(500, 'simulated_in_production', 'Provedor simulado não pode ser usado em produção.')
        return {'preference_id': f"sim-pref-{payment['id']}",
                'checkout_url': f"/checkout/simulado/{payment['id']}"}

    def refund(self, provider_payment_id: str, amount_cents: int, idempotency_key: str) -> str:
        return f'sim-refund-{idempotency_key[:12]}'

    def get_payment(self, provider_payment_id: str) -> ProviderPayment | None:
        return None  # sem consulta externa no simulador


class MercadoPagoProvider:
    name = 'mercadopago'

    def _headers(self, idem: str | None = None) -> dict:
        if not settings.mp_access_token:
            raise AppError(503, 'mp_not_configured', 'Mercado Pago não configurado (MP_ACCESS_TOKEN).')
        h = {'Authorization': f'Bearer {settings.mp_access_token}'}
        if idem:
            h['X-Idempotency-Key'] = idem
        return h

    def create_checkout(self, payment: dict, reservation: dict, game_title: str, method: str) -> dict:
        excluded = ([{'id': 'credit_card'}, {'id': 'debit_card'}, {'id': 'ticket'}, {'id': 'atm'}] if method == 'pix'
                    else [{'id': 'ticket'}, {'id': 'atm'}, {'id': 'bank_transfer'}])
        body = {
            'items': [{'id': str(reservation['id']), 'title': f"timedefora — {game_title} ({reservation['minutes']} min)",
                       'quantity': 1, 'currency_id': 'BRL', 'unit_price': round(payment['amount_cents'] / 100, 2)}],
            'external_reference': str(payment['id']),
            'notification_url': settings.api_public_url.rstrip('/') + '/webhooks/mercadopago',
            'back_urls': {s: f"{settings.frontend_url.rstrip('/')}/checkout/retorno?reserva={reservation['id']}"
                          for s in ('success', 'pending', 'failure')},
            'auto_return': 'approved',
            'expires': True,
            'expiration_date_to': payment['expires_at'].isoformat(timespec='milliseconds'),
            'payment_methods': {'excluded_payment_types': excluded, 'installments': 1},
            'statement_descriptor': 'TIMEDEFORA',
        }
        try:
            r = httpx.post(f'{MP_API}/checkout/preferences', json=body, headers=self._headers(payment['idempotency_key']), timeout=15)
        except httpx.HTTPError:
            raise AppError(502, 'mp_unreachable', 'Não foi possível contatar o Mercado Pago.')
        if r.status_code >= 300:
            raise AppError(502, 'mp_error', f'Mercado Pago recusou a criação do checkout (HTTP {r.status_code}).')
        d = r.json()
        sandbox = settings.mp_access_token.startswith('TEST-')
        return {'preference_id': d['id'], 'checkout_url': d['sandbox_init_point'] if sandbox else d['init_point']}

    def get_payment(self, provider_payment_id: str) -> ProviderPayment | None:
        try:
            r = httpx.get(f'{MP_API}/v1/payments/{provider_payment_id}', headers=self._headers(), timeout=15)
        except httpx.HTTPError:
            raise AppError(502, 'mp_unreachable', 'Não foi possível consultar o Mercado Pago.')
        if r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise AppError(502, 'mp_error', f'Consulta ao Mercado Pago falhou (HTTP {r.status_code}).')
        d = r.json()
        ptype = d.get('payment_type_id') or ''
        return ProviderPayment(str(d['id']), MP_STATUS.get(d.get('status'), 'pending'), d.get('status_detail') or '',
                               d.get('external_reference'), int(round(float(d.get('transaction_amount') or 0) * 100)),
                               'pix' if ptype == 'bank_transfer' else ('card' if 'card' in ptype else 'unknown'))

    def refund(self, provider_payment_id: str, amount_cents: int, idempotency_key: str) -> str:
        try:
            r = httpx.post(f'{MP_API}/v1/payments/{provider_payment_id}/refunds', json={'amount': round(amount_cents / 100, 2)},
                           headers=self._headers(idempotency_key), timeout=20)
        except httpx.HTTPError:
            raise AppError(502, 'mp_unreachable', 'Não foi possível contatar o Mercado Pago.')
        if r.status_code >= 300:
            raise AppError(502, 'mp_refund_error', f'Estorno recusado pelo Mercado Pago (HTTP {r.status_code}).')
        return str(r.json().get('id'))


def verify_mp_signature(x_signature: str, x_request_id: str, data_id: str, secret: str, max_age_seconds: int = 600) -> tuple[bool, int | None]:
    """Valida x-signature (HMAC-SHA256 do manifesto id/request-id/ts) e janela antirreplay."""
    parts = dict(p.split('=', 1) for p in (x_signature or '').split(',') if '=' in p)
    ts, v1 = parts.get('ts', '').strip(), parts.get('v1', '').strip()
    if not ts or not v1 or not secret:
        return False, None
    data_id = data_id.lower() if data_id.isalnum() else data_id
    manifest = f'id:{data_id};request-id:{x_request_id};ts:{ts};'
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    try:
        ts_i = int(ts)
    except ValueError:
        return False, None
    ts_s = ts_i / 1000 if ts_i > 10 ** 12 else ts_i
    fresh = abs(time.time() - ts_s) <= max_age_seconds
    return hmac.compare_digest(expected, v1) and fresh, ts_i


def get_provider(name: str | None = None):
    name = name or settings.payment_provider
    if name == 'mercadopago':
        return MercadoPagoProvider()
    if name == 'simulated':
        return SimulatedProvider()
    raise AppError(500, 'invalid_provider', 'Provedor de pagamento inválido.')
