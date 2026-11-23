"""Configuração por variáveis de ambiente. Nenhum segredo tem valor padrão de produção."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ('1', 'true', 'yes', 'on')


def _json_list(name: str, default: list) -> list:
    import json
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        v = json.loads(raw)
    except ValueError as e:
        raise RuntimeError(f'{name} inválido: esperado JSON (lista de servidores ICE).') from e
    if not isinstance(v, list):
        raise RuntimeError(f'{name} inválido: esperado uma lista.')
    return v


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv('APP_ENV', 'development'))
    database_url: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'postgresql://postgres@localhost:5432/locaplay'))
    # Chave usada para HMAC de códigos e criptografia AES-GCM de segredos (32+ bytes, base64 ou texto).
    secret_key: str = field(default_factory=lambda: os.getenv('APP_SECRET_KEY', ''))
    frontend_url: str = field(default_factory=lambda: os.getenv('FRONTEND_URL', 'http://localhost:3000'))
    api_public_url: str = field(default_factory=lambda: os.getenv('API_PUBLIC_URL', 'http://localhost:8000'))
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',') if o.strip()])
    cookie_secure: bool = field(default_factory=lambda: _bool('COOKIE_SECURE', False))
    cookie_domain: str | None = field(default_factory=lambda: os.getenv('COOKIE_DOMAIN') or None)
    session_days: int = field(default_factory=lambda: int(os.getenv('SESSION_DAYS', '14')))
    # E-mail: dev (grava em dev_mailbox), smtp ou resend
    email_provider: str = field(default_factory=lambda: os.getenv('EMAIL_PROVIDER', 'dev'))
    email_from: str = field(default_factory=lambda: os.getenv('EMAIL_FROM', 'LocaPlay <nao-responda@locaplay.local>'))
    smtp_host: str = field(default_factory=lambda: os.getenv('SMTP_HOST', ''))
    smtp_port: int = field(default_factory=lambda: int(os.getenv('SMTP_PORT', '587')))
    smtp_user: str = field(default_factory=lambda: os.getenv('SMTP_USER', ''))
    smtp_password: str = field(default_factory=lambda: os.getenv('SMTP_PASSWORD', ''))
    resend_api_key: str = field(default_factory=lambda: os.getenv('RESEND_API_KEY', ''))
    # Pagamentos: simulated (somente desenvolvimento) ou mercadopago (sandbox/produção)
    payment_provider: str = field(default_factory=lambda: os.getenv('PAYMENT_PROVIDER', 'simulated'))
    mp_access_token: str = field(default_factory=lambda: os.getenv('MP_ACCESS_TOKEN', ''))
    mp_webhook_secret: str = field(default_factory=lambda: os.getenv('MP_WEBHOOK_SECRET', ''))
    # Google OAuth
    google_client_id: str = field(default_factory=lambda: os.getenv('GOOGLE_CLIENT_ID', ''))
    google_client_secret: str = field(default_factory=lambda: os.getenv('GOOGLE_CLIENT_SECRET', ''))
    # Worker de agendamento embutido (avisos, expiração de holds e sessões)
    run_worker: bool = field(default_factory=lambda: _bool('RUN_WORKER', True))
    worker_interval_seconds: int = field(default_factory=lambda: int(os.getenv('WORKER_INTERVAL_SECONDS', '15')))
    # Permite vender jogos is_demo sem licença comercial (somente desenvolvimento)
    allow_demo_sales: bool = field(default_factory=lambda: _bool('ALLOW_DEMO_SALES', True))
    require_admin_mfa: bool = field(default_factory=lambda: _bool('REQUIRE_ADMIN_MFA', True))
    # Vídeo do console no navegador (WebRTC): servidores STUN/TURN entregues ao navegador do jogador (JSON no formato
    # RTCIceServer[]). Em produção, inclua um TURN (ex.: coturn) para jogadores/agentes atrás de NAT restritivo.
    webrtc_ice_servers: list = field(default_factory=lambda: _json_list('WEBRTC_ICE_SERVERS', [{'urls': 'stun:stun.l.google.com:19302'}]))

    @property
    def is_production(self) -> bool:
        return self.env == 'production'

    def validate(self) -> None:
        if len(self.secret_key) < 32:
            raise RuntimeError('APP_SECRET_KEY ausente ou curta (mínimo 32 caracteres). Veja .env.example.')
        if self.is_production:
            if self.payment_provider == 'simulated':
                raise RuntimeError('PAYMENT_PROVIDER=simulated não é permitido em produção.')
            if self.email_provider == 'dev':
                raise RuntimeError('EMAIL_PROVIDER=dev não é permitido em produção.')
            if self.allow_demo_sales:
                raise RuntimeError('ALLOW_DEMO_SALES deve ser false em produção.')
            if not self.cookie_secure:
                raise RuntimeError('COOKIE_SECURE deve ser true em produção (HTTPS).')


settings = Settings()
