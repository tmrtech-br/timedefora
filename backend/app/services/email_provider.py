"""Provedores de e-mail transacional (adaptador). dev grava em dev_mailbox (nunca usar em produção)."""
import smtplib
from email.message import EmailMessage

import httpx

from ..config import settings
from ..core.db import get_pool


class EmailSendError(Exception):
    pass


def send_email(to: str, subject: str, text: str, html: str) -> str | None:
    provider = settings.email_provider
    if provider == 'dev':
        with get_pool().connection() as c:
            row = c.execute('insert into dev_mailbox(to_address, subject, body_text, body_html) values (%s,%s,%s,%s) returning id',
                            (to, subject, text, html)).fetchone()
        return f"dev-{row['id']}"
    if provider == 'smtp':
        if not settings.smtp_host:
            raise EmailSendError('SMTP_HOST não configurado')
        msg = EmailMessage()
        msg['From'], msg['To'], msg['Subject'] = settings.email_from, to, subject
        msg.set_content(text)
        msg.add_alternative(html, subtype='html')
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise EmailSendError(f'SMTP: {e.__class__.__name__}')
        return None
    if provider == 'resend':
        if not settings.resend_api_key:
            raise EmailSendError('RESEND_API_KEY não configurada')
        try:
            r = httpx.post('https://api.resend.com/emails', timeout=15,
                           headers={'Authorization': f'Bearer {settings.resend_api_key}'},
                           json={'from': settings.email_from, 'to': [to], 'subject': subject, 'text': text, 'html': html})
        except httpx.HTTPError as e:
            raise EmailSendError(f'Resend: {e.__class__.__name__}')
        if r.status_code >= 300:
            raise EmailSendError(f'Resend HTTP {r.status_code}')
        return r.json().get('id')
    raise EmailSendError(f'Provedor de e-mail desconhecido: {provider}')
