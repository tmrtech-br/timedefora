'use client';
import Link from 'next/link';
import { useState } from 'react';
import {
  Bell, CalendarDays, ClipboardList, CreditCard, FileCheck, Gamepad2, Headphones,
  LayoutDashboard, ListOrdered, Monitor, Network, PanelLeftClose, PanelLeftOpen,
  Radio, Server, Settings2, Shield, SlidersHorizontal, Tags, UserCheck, Users, type LucideIcon,
} from 'lucide-react';
import { usePathname } from 'next/navigation';
import RequireAuth from '@/components/RequireAuth';
import { Alert } from '@/components/ui';
import { isStaff, useAuth } from '@/lib/auth';

const SECTIONS: [string, string, string][] = [
  ['', 'Visão geral', 'operator'], ['consoles', 'Consoles e conexão', 'operator'],
  ['cadastro-console', 'Cadastro de console', 'superadmin'],
  ['contas-psn', 'Contas PSN', 'admin'], ['jogos', 'Jogos', 'operator'],
  ['agenda', 'Vínculos e calendário', 'operator'], ['agentes', 'Agentes e dispositivos', 'operator'], ['precos', 'Preços e cupons', 'operator'],
  ['filas', 'Filas', 'operator'], ['reservas', 'Reservas', 'operator'], ['sessoes', 'Sessões e incidentes', 'operator'],
  ['transmissoes', 'Transmissões', 'operator'], ['financeiro', 'Financeiro e relatórios', 'admin'], ['usuarios', 'Usuários e permissões', 'operator'],
  ['notificacoes', 'Notificações', 'admin'], ['suporte', 'Suporte', 'operator'], ['lgpd', 'Solicitações LGPD', 'admin'],
  ['auditoria', 'Auditoria', 'admin'], ['parametros', 'Parâmetros', 'admin'], ['configuracoes', 'Configurações avançadas e políticas', 'admin'],
  ['aprovacoes', 'Aprovação de consoles', 'admin'], ['repasses', 'Repasses a proprietários', 'admin'],
];
const ORDERED_SECTIONS = [...SECTIONS.slice(0, 2), ...SECTIONS.slice(2).sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'))];
const RANK: Record<string, number> = { client: 0, operator: 1, admin: 2, superadmin: 3 };

const NAV_ICONS: Record<string, LucideIcon> = {
  '': LayoutDashboard, consoles: Monitor, 'cadastro-console': Gamepad2, 'contas-psn': Network,
  jogos: Gamepad2, agenda: CalendarDays, agentes: Server, precos: Tags, filas: ListOrdered,
  reservas: ClipboardList, sessoes: Monitor, transmissoes: Radio, financeiro: CreditCard,
  usuarios: Users, notificacoes: Bell, suporte: Headphones, lgpd: Shield,
  auditoria: FileCheck, parametros: SlidersHorizontal, configuracoes: Settings2, aprovacoes: UserCheck, repasses: CreditCard,
};

function Guard({ children }: { children: React.ReactNode }) {
  const { me } = useAuth();
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  if (!isStaff(me)) return <Alert kind="error">Acesso restrito à equipe timedefora.</Alert>;
  if (!me!.mfa_enabled) return <Alert kind="warn"><span>Ative a autenticação em dois fatores em <Link className="link-purple" href="/configuracoes">Configurações</Link> para acessar o painel.</span></Alert>;
  if (!me!.mfa_verified) return <Alert kind="warn"><span>Confirme o segundo fator: <Link className="link-purple" href={`/mfa?proximo=${path}`}>verificar código</Link>.</span></Alert>;
  const rank = Math.max(...me!.roles.map((r) => RANK[r] ?? 0));
  const overrides = me?.permission_overrides ?? {};
  const sections = ORDERED_SECTIONS.filter(([section, , minimum]) =>
    rank >= RANK[minimum] && overrides[`level:${minimum}`] !== false && overrides[`menu:${section || 'overview'}`] !== false);
  const current = path.split('/')[2] ?? '';
  const denied = SECTIONS.some(([section]) => section === current) && !sections.some(([section]) => section === current);
  return (
    <div className={`admin-grid${collapsed ? ' admin-grid-collapsed' : ''}`}>
      <div className="admin-navigation">
        <div className="admin-nav-heading">
          <div className="small dim admin-role">Papel: {me!.roles.filter((r) => r !== 'client').join(', ')}</div>
          <button className="btn sm admin-nav-toggle" type="button" aria-controls="admin-sections"
            aria-expanded={!collapsed} aria-label={collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral'}
            title={collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral'}
            onClick={() => setCollapsed((value) => !value)}>
            {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
          </button>
        </div>
        <nav id="admin-sections" className="admin-nav" aria-label="Seções do painel">
          {sections.map(([k, label]) => {
            const href = `/admin${k ? '/' + k : ''}`;
            const Icon = NAV_ICONS[k];
            return <Link key={k} href={href} aria-current={path === href ? 'page' : undefined}
              aria-label={label} title={collapsed ? label : undefined}
              className={`${path === href ? 'on' : ''} ${k === '' || k === 'consoles' ? 'menu-highlight' : ''}`}>
              <Icon size={17} aria-hidden /><span className="admin-nav-label">{label}</span>
            </Link>;
          })}
        </nav>
      </div>
      <div style={{ minWidth: 0 }}>{denied ? <Alert kind="error">Você não tem acesso a esta seção.</Alert> :
        children}</div>
    </div>
  );
}
export default function AdminLayout({ children }: { children: React.ReactNode }) { return <RequireAuth><Guard>{children}</Guard></RequireAuth>; }
