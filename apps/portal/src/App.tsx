import { useEffect, type ReactNode } from 'react';
import { Link, matchPath, navigate, useLocation } from '@shared/router';
import { Loading } from '@shared/ui';
import { useAuth } from '@shared/member/auth';
import { APPLY_URL, WWW_URL, applyUrl } from '@shared/member/urls';
import {
  ForgotPasswordPage,
  LoginPage,
  RegisterPage,
  ResetPasswordPage,
  UnsubscribePage,
  VerifyEmailPage,
} from './pages/AccountPages';
import { ApplicationPage, DashboardPage, PayPage, PaymentReturnPage, ProfilePage } from './pages/PortalPages';

/** Full-page redirect to the application site. */
function LeaveTo({ href }: { href: string }) {
  useEffect(() => window.location.replace(href), [href]);
  return <Loading />;
}

/** Routes that work without signing in. */
const PUBLIC_ROUTES: Record<string, () => ReactNode> = {
  '/login': () => <LoginPage />,
  '/register': () => <RegisterPage />,
  '/verify-email': () => <VerifyEmailPage />,
  '/forgot-password': () => <ForgotPasswordPage />,
  '/reset-password': () => <ResetPasswordPage />,
  '/unsubscribe': () => <UnsubscribePage />,
};

function memberRoute(path: string): ReactNode {
  if (path === '/') return <DashboardPage />;
  if (path === '/profile') return <ProfilePage />;
  if (path === '/payments/return') return <PaymentReturnPage />;
  const pay = matchPath('/applications/:id/pay', path);
  if (pay) return <PayPage id={Number(pay.id)} />;
  const application = matchPath('/applications/:id', path);
  if (application) return <ApplicationPage id={Number(application.id)} />;
  return (
    <section className="card stack">
      <h1>Page not found</h1>
      <Link to="/">Go to my membership</Link>
    </section>
  );
}

export function App() {
  const { path, query } = useLocation();
  const { profile, checking, signOut } = useAuth();

  let content: ReactNode;
  // The application form lives on its own site; send /apply and /renew there.
  if (path === '/apply') content = <LeaveTo href={`${APPLY_URL}/${window.location.search}`} />;
  else if (path === '/renew') content = <LeaveTo href={applyUrl({ type: 'renewal' })} />;
  else if (checking) content = <Loading />;
  else if (PUBLIC_ROUTES[path]) content = PUBLIC_ROUTES[path]();
  else if (!profile) content = <LoginPage next={path === '/' ? undefined : `${path}?${query.toString()}`} />;
  else content = memberRoute(path);

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="app-header">
        <div className="container row-between">
          <a className="app-brand" href={WWW_URL}>Kiowa Gun Club</a>
          <nav className="row" aria-label="Member menu">
            {profile ? (
              <>
                <Link to="/" aria-current={path === '/' ? 'page' : undefined}>My membership</Link>
                <Link to="/profile" aria-current={path === '/profile' ? 'page' : undefined}>My information</Link>
                <button type="button" className="btn btn-sm" onClick={() => void signOut().then(() => navigate('/login'))}>Sign out</button>
              </>
            ) : (
              <>
                <Link to="/login">Member login</Link>
                <Link to="/register">Set up your account</Link>
              </>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="container app-main" tabIndex={-1}>{content}</main>
      <footer className="app-footer container small muted">
        <a href={WWW_URL}>Back to the club website</a>
      </footer>
    </>
  );
}
