const TZ = 'America/Fortaleza';

export const money = (cents?: number | null) =>
  cents == null ? '—' : (cents / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: cents % 100 ? 2 : 0 });

const real = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
export const moneyWithCents = (cents?: number | null) => cents == null ? '—' : real.format(cents / 100);

export const moneyShort = (cents?: number | null) => (cents == null ? '—' : `R$ ${(cents / 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}`);

export const dateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

export const time = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }) : '—';

export const duration = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
};

export const minutesLabel = (m?: number | null) => (m == null ? '—' : m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`);

export const RESERVATION_STATUS: Record<string, string> = {
  pending_payment: 'Aguardando pagamento', confirmed: 'Confirmada', active: 'Em andamento', completed: 'Concluída',
  no_show: 'Ausência', cancelled: 'Cancelada', expired: 'Expirada', needs_resolution: 'Em resolução', refunded: 'Reembolsada',
};
export const PAYMENT_STATUS: Record<string, string> = {
  created: 'Criado', pending: 'Pendente', approved: 'Aprovado', rejected: 'Recusado', cancelled: 'Cancelado',
  expired: 'Expirado', refunded: 'Reembolsado', charged_back: 'Contestado',
};
export const QUEUE_STATUS: Record<string, string> = { playing: 'jogando', next: 'próximo', waiting: 'aguardando' };
export const PLATFORM_SHORT: Record<string, string> = { PS5: 'PS5', PS4: 'PS4', XBOX_SERIES: 'Xbox Series', XBOX_ONE: 'Xbox One', SWITCH: 'Nintendo Switch' };
export const CANCEL_REQUEST_STATUS: Record<string, string> = { requested: 'Em análise', approved: 'Aprovada', denied: 'Recusada' };
export const DATA_REQUEST_STATUS: Record<string, string> = { open: 'Aberta', in_progress: 'Em andamento', completed: 'Concluída', rejected: 'Recusada' };
export const SESSION_STATUS: Record<string, string> = { ready: 'Pronta', active: 'Em andamento', ended: 'Encerrada', expired: 'Expirada', failed: 'Falhou' };
export const TICKET_STATUS: Record<string, string> = { open: 'Aberto', in_progress: 'Em andamento', resolved: 'Resolvido', closed: 'Fechado' };
export const TICKET_CATEGORY: Record<string, string> = { geral: 'Geral', pagamento: 'Pagamento', sessao: 'Sessão', conta: 'Conta', reembolso: 'Reembolso', tecnico: 'Técnico' };
