'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Bell, CirclePlay, CreditCard, Crown, Gamepad2, Headphones, Heart, Home, Info, ListOrdered, LogOut, Menu, Monitor, Receipt,
  Settings, ShieldCheck, ShieldHalf, Smartphone, Tablet, UserRound, UserRoundPlus, X, Zap,
} from 'lucide-react';
import { useAuth, isStaff } from '@/lib/auth';
import { get } from '@/lib/api';

function LogoIcon() {
  // Ícone próprio (ingresso/fita) — identidade LocaPlay
  return (
    <svg className="logo-icon" viewBox="0 0 48 36" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" aria-hidden>
      <path d="M8 6h32a4 4 0 0 1 4 4v4a4 4 0 0 0 0 8v4a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4v-4a4 4 0 0 0 0-8v-4a4 4 0 0 1 4-4Z" />
      <circle cx="18" cy="18" r="4" /><circle cx="30" cy="18" r="4" /><path d="M14 11h20M14 25h20" strokeWidth="1.6" />
    </svg>
  );
}

const TOP = [
  { href: '/', label: 'Início', icon: Home },
  { href: '/jogos', label: 'Jogos', icon: Gamepad2 },
  { href: '/como-funciona', label: 'Como Funciona', icon: Info },
  { href: '/planos', label: 'Planos', icon: Crown },
  { href: '/suporte', label: 'Suporte', icon: Headphones },
];
const SIDE_MAIN = [
  { href: '/jogos', label: 'Catálogo', icon: Gamepad2, also: ['/'] },
  { href: '/minhas-filas', label: 'Minhas filas', icon: ListOrdered },
  { href: '/sessoes', label: 'Sessões', icon: CirclePlay },
];
const SIDE_ACCOUNT = [
  { href: '/perfil', label: 'Perfil', icon: UserRound },
  { href: '/configuracoes', label: 'Configurações', icon: Settings },
];

function isActive(path: string, href: string, also: string[] = []) {
  if (also.includes(path)) return true;
  return href === '/' ? path === '/' : path === href || path.startsWith(href + '/');
}

export function Header({ onMenu, menuOpen }: { onMenu: () => void; menuOpen: boolean }) {
  const path = usePathname();
  const { me } = useAuth();
  return (
    <header className="topbar">
      <button className="icon-btn mobile-toggle" onClick={onMenu} aria-label={menuOpen ? 'Fechar menu' : 'Abrir menu'} aria-expanded={menuOpen}>
        {menuOpen ? <X size={20} /> : <Menu size={20} />}
      </button>
      <Link href="/" className="logo" aria-label="LocaPlay — página inicial">
        <LogoIcon /><span className="logo-text">Loca<b>Play</b></span>
      </Link>
      <nav className="top-nav" aria-label="Navegação principal">
        {TOP.map((i) => (
          <Link key={i.href} href={i.href} className={isActive(path, i.href) ? 'active' : ''} aria-current={isActive(path, i.href) ? 'page' : undefined}>
            <i.icon aria-hidden />{i.label}
          </Link>
        ))}
      </nav>
      <div className="account">
        {me ? (
          <>
            <Link href="/notificacoes" className="icon-btn" aria-label={`Notificações (${me.unread_notifications} não lidas)`}>
              <Bell size={18} />{me.unread_notifications > 0 && <span className="badge-dot">{me.unread_notifications}</span>}
            </Link>
            <Link href="/perfil" className="user-chip" title={me.username}>
              {me.avatar_url ? <img className="avatar" src={me.avatar_url} alt="" /> : <span className="avatar" aria-hidden>{me.username[0]?.toUpperCase()}</span>}
              <span>{me.username}</span>
            </Link>
          </>
        ) : (
          <>
            <Link href="/entrar" className="btn-outline-dark"><UserRound size={19} aria-hidden />Entrar</Link>
            <Link href="/cadastrar" className="btn-signup"><UserRoundPlus size={19} aria-hidden />Cadastrar</Link>
          </>
        )}
      </div>
    </header>
  );
}

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const path = usePathname();
  const router = useRouter();
  const { me, logout } = useAuth();
  const link = (i: { href: string; label: string; icon: typeof Home; also?: string[] }) => (
    <Link key={i.href + i.label} href={i.href} onClick={onNavigate} className={isActive(path, i.href, i.also) ? 'active' : ''}>
      <i.icon aria-hidden />{i.label}
    </Link>
  );
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Menu do jogador">
      <nav className="side-links">
        <div className="mobile-only">{TOP.filter((t) => t.href !== '/jogos').map(link)}<div className="side-divider" /></div>
        {SIDE_MAIN.map(link)}
        <div className="side-divider" />
        {SIDE_ACCOUNT.map(link)}
        {me && (
          <div className="side-extra">
            <div className="side-divider" />
            {link({ href: '/jogos?disponibilidade=available', label: 'Disponíveis', icon: Zap })}
            {link({ href: '/pagamentos', label: 'Pagamentos', icon: Receipt })}
            {link({ href: '/favoritos', label: 'Favoritos', icon: Heart })}
            {link({ href: '/notificacoes', label: 'Notificações', icon: Bell })}
            {isStaff(me) && link({ href: '/admin', label: 'Painel administrativo', icon: ShieldHalf })}
            <a href="#sair" onClick={async (e) => { e.preventDefault(); await logout(); onNavigate(); router.push('/'); }}><LogOut aria-hidden />Sair</a>
          </div>
        )}
      </nav>
      <div className="side-deco" aria-hidden />
    </aside>
  );
}

type Health = { payment_provider: string; payments_simulated: boolean };

export function Footer() {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => { get<Health>('/health').then(setH).catch(() => setH(null)); }, []);
  const realPayments = h && !h.payments_simulated;
  return (
    <>
      <footer className="footer">
        <span className="slogan">A locadora voltou. Agora na sua casa.</span>
        <div className="footer-items">
          <div className="footer-item pix"><Zap aria-hidden /><div><b>Pix</b><small>{realPayments ? 'Pagamento instantâneo' : 'Ambiente de testes'}</small></div></div>
          <div className="footer-item"><CreditCard aria-hidden /><div><b>Cartão</b><small>{realPayments ? 'Crédito e débito' : 'Modo sandbox'}</small></div></div>
          <div className="footer-item"><ShieldCheck aria-hidden /><div><b>Segurança</b><small>Seus dados protegidos</small></div></div>
          <div className="footer-item"><Headphones aria-hidden /><div><b>Suporte</b><small>Atendimento por chamado</small></div></div>
          <div className="footer-item footer-devices">
            <span className="icons" aria-hidden><Monitor /><Tablet /><Smartphone /></span>
            <small>Jogue no PC e notebook<br />Móvel em validação</small>
          </div>
        </div>
      </footer>
      <div className="footer-legal">
        <Link href="/termos">Termos de uso</Link><Link href="/privacidade">Privacidade (LGPD)</Link>
        <Link href="/politica-cancelamento">Cancelamento e reembolso</Link><span>Horários em America/Fortaleza</span>
      </div>
    </>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  return (
    <>
      <a href="#conteudo" className="skip-link">Pular para o conteúdo</a>
      <Header onMenu={() => setOpen(!open)} menuOpen={open} />
      <div className="shell">
        <Sidebar open={open} onNavigate={() => setOpen(false)} />
        <div className="main">
          <main id="conteudo" className={path === '/' ? 'content' : 'content pad'}>{children}</main>
          <Footer />
        </div>
      </div>
    </>
  );
}
