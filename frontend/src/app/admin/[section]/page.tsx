'use client';
import { useParams } from 'next/navigation';
import Agenda from '@/components/admin/Agenda';
import Agents from '@/components/admin/Agents';
import Consoles from '@/components/admin/Consoles';
import Finance from '@/components/admin/Finance';
import Games from '@/components/admin/Games';
import { Channels, Queues, Reservations, Sessions } from '@/components/admin/Ops';
import { Audit, Lgpd, Notifications, Settings, Support, Users } from '@/components/admin/People';
import Params from '@/components/admin/Params';
import Pricing from '@/components/admin/Pricing';
import { Alert } from '@/components/ui';

const MAP: Record<string, React.ComponentType> = { consoles: Consoles, jogos: Games, agenda: Agenda, agentes: Agents, precos: Pricing, filas: Queues,
  reservas: Reservations, sessoes: Sessions, transmissoes: Channels, financeiro: Finance, usuarios: Users, notificacoes: Notifications,
  suporte: Support, lgpd: Lgpd, auditoria: Audit, parametros: Params, configuracoes: Settings };

export default function Section() {
  const { section } = useParams<{ section: string }>();
  const C = MAP[section];
  return C ? <C /> : <Alert kind="error">Seção não encontrada.</Alert>;
}
