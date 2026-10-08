import { useEffect, useState, type ReactNode } from 'react';
import { Link, matchPath, navigate, useLocation } from '@shared/router';
import { Alert, Loading, useAction } from '@shared/ui';
import { useAuth } from './auth';
import { AccountPage } from './pages/Account';
import { ApplicationDetail, ApplicationsPage } from './pages/Applications';
import { AuditLogPage } from './pages/AuditLog';
import { BoardUsersPage } from './pages/BoardUsers';
import { CalendarPage } from './pages/Calendar';
import { EmailPage, SmsPage } from './pages/Communications';
import { DashboardPage } from './pages/Dashboard';
import { DocumentsPage } from './pages/Documents';
import { ForgotPasswordPage, LoginPage, ResetPasswordPage } from './pages/Login';
import { MatchesPage } from './pages/Matches';
import { MemberDetail, MembersPage } from './pages/Members';
import { PaymentsPage } from './pages/Payments';
import { SettingsPage } from './pages/Settings';
import { WebsitePage } from './pages/Website';

type NavItem = { to: string; label: string; permission?: string };

const NAV: { heading: string; items: NavItem[] }[] = [
  { heading: 'Overview', items: [{ to: '/', label: 'Dashboard' }] },
  {
    heading: 'Membership',
    items: [
      { to: '/applications', label: 'Applications', permission: 'applications.review' },
      { to: '/members', label: 'Members & contacts', permission: 'members.view' },
      { to: '/documents', label: 'Documents', permission: 'documents.review' },
      { to: '/payments', label: 'Payments', permission: 'payments.view' },
    ],
  },
  {
    heading: 'Website',
    items: [
      { to: '/website', label: 'Website text & photos', permission: 'content.edit' },
      { to: '/calendar', label: 'Calendar', permission: 'calendar.manage' },
      { to: '/matches', label: 'Matches', permission: 'matches.manage' },
    ],
  },
  {
    heading: 'Messages',
    items: [
      { to: '/email', label: 'Email', permission: 'communications.send' },
      { to: '/sms', label: 'Text messages', permission: 'communications.send' },
    ],
  },
  {
    heading: 'Administration',
    items: [
      { to: '/board-users', label: 'Board users', permission: 'board.manage' },
      { to: '/settings', label: 'Settings', permission: 'content.edit' },
      { to: '/audit', label: 'Activity log', permission: 'audit.view' },
      { to: '/account', label: 'My account' },
    ],
  },
];

function route(path: string): ReactNode {
  const simple: Record<string, () => ReactNode> = {
    '/': () => <DashboardPage />,
    '/applications': () => <ApplicationsPage />,
    '/members': () => <MembersPage />,
    '/documents': () => <DocumentsPage />,
    '/payments': () => <PaymentsPage />,
    '/website': () => <WebsitePage />,
    '/calendar': () => <CalendarPage />,
    '/matches': () => <MatchesPage />,
    '/email': () => <EmailPage />,
    '/sms': () => <SmsPage />,
    '/board-users': () => <BoardUsersPage />,
    '/settings': () => <SettingsPage />,
    '/audit': () => <AuditLogPage />,
    '/account': () => <AccountPage />,
  };
  if (simple[path]) return simple[path]();
  const application = matchPath('/applications/:id', path);
  if (application) return <ApplicationDetail id={Number(application.id)} />;
  const member = matchPath('/members/:id', path);
  if (member) return <MemberDetail id={Number(member.id)} />;
  return (
    <section className="card">
      <h1>Page not found</h1>
      <Link to="/">Back to the dashboard</Link>
    </section>
  );
}

export function App() {
  const { path } = useLocation();
  const { session, checking, can, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const signOutAction = useAction(async () => {
    await signOut();
    navigate('/');
  });
  useEffect(() => setMenuOpen(false), [path]);

  if (checking) return <Loading />;
  if (path === '/forgot-password') return <AuthFrame><ForgotPasswordPage /></AuthFrame>;
  if (path === '/reset-password' || path === '/accept-invite') return <AuthFrame><ResetPasswordPage invite={path === '/accept-invite'} /></AuthFrame>;
  if (!session) return <AuthFrame><LoginPage /></AuthFrame>;

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="shell-header">
        <Link to="/" className="shell-brand">Kiowa Gun Club <span>Board</span></Link>
        <button type="button" className="btn btn-sm menu-toggle" aria-expanded={menuOpen} aria-controls="board-nav" onClick={() => setMenuOpen((o) => !o)}>
          {menuOpen ? 'Close menu' : 'Menu'}
        </button>
        <div className="shell-user">
          <span className="small">{session.person.first_name} {session.person.last_name} · {session.role_label}</span>
          <button type="button" className="btn btn-sm" disabled={signOutAction.busy} onClick={() => void signOutAction.run()}>Sign out</button>
        </div>
      </header>
      <nav id="board-nav" className={`sidebar ${menuOpen ? 'open' : ''}`} aria-label="Board menu">
        {NAV.map((group) => {
          const items = group.items.filter((item) => !item.permission || can(item.permission));
          if (items.length === 0) return null;
          return (
            <div key={group.heading} className="sidebar-group">
              <p className="sidebar-heading">{group.heading}</p>
              <ul>
                {items.map((item) => {
                  const active = item.to === '/' ? path === '/' : path === item.to || path.startsWith(`${item.to}/`);
                  return <li key={item.to}><Link to={item.to} aria-current={active ? 'page' : undefined}>{item.label}</Link></li>;
                })}
              </ul>
            </div>
          );
        })}
      </nav>
      <main id="main" className="shell-main" tabIndex={-1}>
        {signOutAction.error && <Alert kind="error" title="You're still signed in.">{signOutAction.error}</Alert>}
        {route(path)}
      </main>
    </div>
  );
}

function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="auth-shell">
      <section className="card auth-card stack">
        <div className="auth-mark" aria-hidden="true">KG</div>
        {children}
      </section>
    </main>
  );
}
