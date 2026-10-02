import type { ReactNode } from 'react';
import { Link, matchPath, navigate, useLocation } from '@shared/router';
import { Loading } from '@shared/ui';
import { useAuth } from './auth';
import {
  ForgotPasswordPage,
  LoginPage,
  RegisterPage,
  ResetPasswordPage,
  UnsubscribePage,
  VerifyEmailPage,
} from './pages/AccountPages';
import { ApplyWizard } from './pages/ApplyWizard';
import { ApplicationPage, DashboardPage, PayPage, PaymentReturnPage, ProfilePage } from './pages/PortalPages';

const WWW_URL: string = import.meta.env.VITE_WWW_URL || 'http://localhost:4173';

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
  if (path === '/apply') return <ApplyWizard />;
  // Link used in renewal reminder emails.
  if (path === '/renew') {
    navigate('/apply?type=renewal', { replace: true });
    return null;
  }
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
  if (checking) content = <Loading />;
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
