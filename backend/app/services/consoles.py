"""Ponte entre o banco e a GameBridge (monta ConsoleRef sem expor segredos ao cliente)."""
from ..core import security
from ..gamebridge import ConsoleRef


def console_ref(conn, console_id) -> ConsoleRef:
    row = conn.execute(
        """select cfg.*, c.id console_pk, p.code platform_code, ag.endpoint_url, ag.outbound_token_enc,
                  cd.device_identifier capture_ident, ca.identifier control_ident
           from consoles c join platforms p on p.id=c.platform_id
           left join console_connection_configs cfg on cfg.console_id=c.id
           left join console_agents ag on ag.id=cfg.agent_id
           left join capture_devices cd on cd.id=cfg.capture_device_id
           left join control_adapters ca on ca.id=cfg.control_adapter_id
           where c.id=%s""", (console_id,)).fetchone()
    token = None
    if row and row['outbound_token_enc']:
        token = security.decrypt(row['outbound_token_enc'])
    return ConsoleRef(console_id=str(row['console_pk']) if row else str(console_id), platform_code=row['platform_code'] if row else '',
                      method=(row['method'] if row and row['method'] else 'unconfigured'),
                      agent_endpoint=row['endpoint_url'] if row else None, agent_token=token,
                      internal_host=row['internal_host'] if row else None,
                      capture_device_identifier=row['capture_ident'] if row else None,
                      control_adapter_identifier=row['control_ident'] if row else None,
                      settings={k: row[k] for k in ('resolution', 'fps', 'codec', 'bitrate_kbps', 'low_latency', 'audio_enabled')} if row else {})
