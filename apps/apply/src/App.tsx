import { useEffect, useState } from 'react';
import { navigate, useLocation } from '@shared/router';
import { Alert, Loading, useAction } from '@shared/ui';
import { useAuth } from '@shared/member/auth';
import { PORTAL_URL, WWW_URL } from '@shared/member/urls';
import { ApplyWizard } from './pages/ApplyWizard';

/** Full-page redirect to another site (the member portal). */
function LeaveTo({ href }: { href: string }) {
  useEffect(() => window.location.replace(href), [href]);
  return <Loading />;
}

/** In-app redirect, done after render. */
function GoTo({ to }: { to: string }) {
  useEffect(() => navigate(to, { replace: true }), [to]);
  return null;
}

/**
 * apply.kiowagunclub.org is only the application form, served at "/".
 * Signing in, account pages, application status and payment live on the
 * member portal; any other path here is forwarded there.
 */
export function App() {
  const { path, query } = useLocation();
  const { profile, checking, signOut } = useAuth();
  // Set once signed out, so clearing the profile doesn't also trigger the
  // "not signed in" redirect below and race the one to the portal's login page.
  const [leaving, setLeaving] = useState(false);
  const signOutAction = useAction(async () => {
    await signOut();
    setLeaving(true);
    window.location.replace(`${PORTAL_URL}/login`);
  });

  let content;
  if (signOutAction.busy || leaving) {
    content = <Loading />;
  } else if (path === '/apply' || path === '/renew') {
    // Older links: apply.kiowagunclub.org/apply?type=… and the renewal-reminder /renew link.
    const params = new URLSearchParams(query);
    if (path === '/renew') params.set('type', 'renewal');
    const search = params.toString();
    content = <GoTo to={search ? `/?${search}` : '/'} />;
  } else if (path !== '/') {
    content = <LeaveTo href={`${PORTAL_URL}${path}${window.location.search}${window.location.hash}`} />;
  } else if (checking) {
    content = <Loading />;
  } else if (!profile) {
    content = <LeaveTo href={`${PORTAL_URL}/`} />;
  } else {
    content = <ApplyWizard />;
  }

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="app-header">
        <div className="container row-between">
          <a className="app-brand" href={WWW_URL}>Kiowa Gun Club</a>
          {profile && (
            <nav className="row" aria-label="Member menu">
              <a href={`${PORTAL_URL}/`}>My membership</a>
              <a href={`${PORTAL_URL}/profile`}>My information</a>
              <button type="button" className="btn btn-sm" disabled={signOutAction.busy} onClick={() => void signOutAction.run()}>Sign out</button>
            </nav>
          )}
        </div>
      </header>
      <main id="main" className="container app-main" tabIndex={-1}>
        {signOutAction.error && <Alert kind="error" title="You're still signed in.">{signOutAction.error}</Alert>}
        {content}
      </main>
      <footer className="app-footer container small muted">
        <a href={WWW_URL}>Back to the club website</a>
      </footer>
    </>
  );
}
