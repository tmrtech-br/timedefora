'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Bell, CirclePlay, CreditCard, Gamepad2, Headphones, Heart, Home, Info, Keyboard, ListOrdered, LogOut, Menu, Monitor, Receipt,
  PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck, ShieldHalf, Smartphone, Tablet, UserRound, UserRoundPlus, X, Zap,
} from 'lucide-react';
import { useAuth, isStaff } from '@/lib/auth';
import { get } from '@/lib/api';
import { useFeatures } from '@/lib/features';
import Toaster from '@/components/Toaster';

function LogoIcon() {
  // Ícone próprio (cartucho de videogame) — identidade timedefora
  return (
    <svg className="logo-icon" viewBox="0 0 48 36" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" aria-hidden>
      <path d="M14 2h20a3 3 0 0 1 3 3v22h-3v5H14v-5h-3V5a3 3 0 0 1 3-3Z" />
      <path d="M16 6.5h16" strokeWidth="1.6" />
      <rect x="15" y="11" width="18" height="12" rx="1.5" strokeWidth="1.8" />
      <path d="M19.5 15v4M17.5 17h4" strokeWidth="1.6" />
      <circle cx="27" cy="16" r=".6" fill="currentColor" /><circle cx="29.5" cy="18.5" r=".6" fill="currentColor" />
    </svg>
  );
}

const TOP = [
  { href: '/', label: 'Início', icon: Home },
  { href: '/jogos', label: 'Jogos', icon: Gamepad2 },
  { href: '/como-funciona', label: 'Como Funciona', icon: Info },
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
      <button className="icon-btn mobile-toggle" onClick={onMenu} aria-label={menuOpen ? 'Fechar menu' : 'Abrir menu'} aria-expanded={menuOpen} aria-controls="player-sidebar">
        {menuOpen ? <X size={20} /> : <Menu size={20} />}
      </button>
      <Link href="/" className="logo" aria-label="timedefora — página inicial">
        <LogoIcon /><span className="logo-text">timedefora</span>
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
            <Link href="/favoritos" className="icon-btn" aria-label="Favoritos"><Heart size={18} /></Link>
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

export function Sidebar({ open, collapsed, onToggle, onNavigate }: {
  open: boolean; collapsed: boolean; onToggle: () => void; onNavigate: () => void;
}) {
  const path = usePathname();
  const router = useRouter();
  const { me, logout } = useAuth();
  const features = useFeatures();
  const link = (i: { href: string; label: string; icon: typeof Home; also?: string[] }) => (
    <Link key={i.href + i.label} href={i.href} onClick={onNavigate} className={isActive(path, i.href, i.also) ? 'active' : ''}
      aria-current={isActive(path, i.href, i.also) ? 'page' : undefined} aria-label={i.label} title={collapsed ? i.label : undefined}>
      <i.icon aria-hidden /><span className="sidebar-label">{i.label}</span>
    </Link>
  );
  return (
    <aside id="player-sidebar" className={`sidebar ${open ? 'open' : ''}`} aria-label="Menu do jogador">
      <button className="btn sm sidebar-toggle" type="button" aria-controls="player-sections" aria-expanded={!collapsed}
        aria-label={collapsed ? 'Expandir menu principal' : 'Recolher menu principal'}
        title={collapsed ? 'Expandir menu principal' : 'Recolher menu principal'} onClick={onToggle}>
        {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
      </button>
      <nav id="player-sections" className="side-links">
        <div className="mobile-only">{TOP.filter((t) => t.href !== '/jogos').map(link)}{!me && link({ href: '/cadastrar', label: 'Cadastrar', icon: UserRoundPlus })}<div className="side-divider" /></div>
        {SIDE_MAIN.map(link)}
        <div className="side-divider" />
        {SIDE_ACCOUNT.map(link)}
        {features?.controls_menu_enabled && link({ href: '/controles', label: 'Teclado e mouse', icon: Keyboard })}
        {me && (
          <div className="side-extra">
            <div className="side-divider" />
            {link({ href: '/jogos?disponibilidade=available', label: 'Disponíveis', icon: Zap })}
            {link({ href: '/pagamentos', label: 'Pagamentos', icon: Receipt })}
            {isStaff(me) && link({ href: '/admin', label: 'Painel administrativo', icon: ShieldHalf })}
            {me.roles.includes('owner') && link({ href: '/proprietario', label: 'Portal do proprietário', icon: Monitor })}
            <a href="#sair" aria-label="Sair" title={collapsed ? 'Sair' : undefined}
              onClick={async (e) => { e.preventDefault(); await logout(); onNavigate(); router.push('/'); }}>
              <LogOut aria-hidden /><span className="sidebar-label">Sair</span>
            </a>
          </div>
        )}
      </nav>
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
  const [collapsed, setCollapsed] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    function onEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        document.querySelector<HTMLButtonElement>('.mobile-toggle')?.focus();
      }
    }
    window.addEventListener('keydown', onEscape);
    return () => window.removeEventListener('keydown', onEscape);
  }, [open]);
  return (
    <Toaster>
      <a href="#conteudo" className="skip-link">Pular para o conteúdo</a>
      <Header onMenu={() => setOpen(!open)} menuOpen={open} />
      <div className={`shell${collapsed ? ' shell-sidebar-collapsed' : ''}`}>
        <Sidebar open={open} collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} onNavigate={() => setOpen(false)} />
        <div className="main">
          <main id="conteudo" tabIndex={-1} className={path === '/' ? 'content' : 'content pad'}>{children}</main>
          <Footer />
        </div>
      </div>
    </Toaster>
  );
}
