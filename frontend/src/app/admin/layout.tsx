'use client';
import Link from 'next/link';
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
];
const RANK: Record<string, number> = { client: 0, operator: 1, admin: 2, superadmin: 3 };

function Guard({ children }: { children: React.ReactNode }) {
  const { me } = useAuth();
  const path = usePathname();
  if (!isStaff(me)) return <Alert kind="error">Acesso restrito à equipe LocaPlay.</Alert>;
  if (!me!.mfa_enabled) return <Alert kind="warn"><span>Ative a autenticação em dois fatores em <Link className="link-purple" href="/configuracoes">Configurações</Link> para acessar o painel.</span></Alert>;
  if (!me!.mfa_verified) return <Alert kind="warn"><span>Confirme o segundo fator: <Link className="link-purple" href={`/mfa?proximo=${path}`}>verificar código</Link>.</span></Alert>;
  const rank = Math.max(...me!.roles.map((r) => RANK[r] ?? 0));
  const overrides = me?.permission_overrides ?? {};
  const sections = SECTIONS.filter(([section, , minimum]) =>
    rank >= RANK[minimum] && overrides[`level:${minimum}`] !== false && overrides[`menu:${section || 'overview'}`] !== false);
  const current = path.split('/')[2] ?? '';
  const denied = SECTIONS.some(([section]) => section === current) && !sections.some(([section]) => section === current);
  return (
    <div className="admin-grid">
      <nav className="admin-nav" aria-label="Seções do painel">
        <div className="small dim" style={{ padding: '0 12px 6px' }}>Papel: {me!.roles.filter((r) => r !== 'client').join(', ')}</div>
        {sections.map(([k, label]) => {
          const href = `/admin${k ? '/' + k : ''}`;
          return <Link key={k} href={href} className={path === href ? 'on' : ''}>{label}</Link>;
        })}
      </nav>
      <div style={{ minWidth: 0 }}>{denied ? <Alert kind="error">Você não tem acesso a esta seção.</Alert> : children}</div>
    </div>
  );
}
export default function AdminLayout({ children }: { children: React.ReactNode }) { return <RequireAuth><Guard>{children}</Guard></RequireAuth>; }
