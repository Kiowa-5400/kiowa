import React, { FormEvent, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import './styles.css';

type Person = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
};

type DashboardSummary = {
  pending: number;
  approved: number;
  waiting_list: number;
  total: number;
};

type Submission = {
  id: number;
  name: string;
  type: string;
  status: string;
  amount: number;
};

const TOKEN_KEY = 'kiowa_board_token';

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) || '');
  const [person, setPerson] = useState<Person | null>(null);
  const [summary, setSummary] = useState<DashboardSummary>({ pending: 0, approved: 0, waiting_list: 0, total: 0 });
  const [applications, setApplications] = useState<Submission[]>([]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(token));
  const [signingIn, setSigningIn] = useState(false);
  const [loadingDashboard, setLoadingDashboard] = useState(false);

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  const clearSession = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken('');
    setPerson(null);
    setSummary({ pending: 0, approved: 0, waiting_list: 0, total: 0 });
    setApplications([]);
  };

  const authenticatedFetch = async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${token}`);
    if (init.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers });

    if (response.status === 401 || response.status === 403) {
      clearSession();
    }

    return response;
  };

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    const verifyBoardSession = async () => {
      try {
        setLoading(true);
        setAuthError('');

        const response = await authenticatedFetch('/api/auth/me');
        if (!response.ok) {
          throw new Error('Your board session is no longer valid.');
        }

        const currentPerson = (await response.json()) as Person;
        if (currentPerson.role !== 'board') {
          clearSession();
          throw new Error('Board authorization is required to access this dashboard.');
        }

        setPerson(currentPerson);
      } catch (loadError) {
        setAuthError(loadError instanceof Error ? loadError.message : 'Please sign in again.');
      } finally {
        setLoading(false);
      }
    };

    void verifyBoardSession();
  }, [token]);

  useEffect(() => {
    if (!token || !person || person.role !== 'board') return;

    const loadDashboard = async () => {
      try {
        setLoadingDashboard(true);
        setError('');

        const response = await authenticatedFetch('/api/board/dashboard');
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || 'Unable to load dashboard.');
        }

        const payload = await response.json();
        setSummary(payload.summary);
        setApplications(payload.recent_applications || []);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load dashboard.');
      } finally {
        setLoadingDashboard(false);
      }
    };

    void loadDashboard();
  }, [token, person]);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSigningIn(true);
    setAuthError('');
    setError('');

    try {
      const response = await fetch(`${apiBaseUrl}/api/auth/board-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || 'Board authentication failed.');
      }

      if (payload.person?.role !== 'board' || !payload.token) {
        throw new Error('Board authorization could not be verified.');
      }

      sessionStorage.setItem(TOKEN_KEY, payload.token);
      setToken(payload.token);
      setPerson(payload.person);
      setPassword('');
    } catch (loginError) {
      setAuthError(loginError instanceof Error ? loginError.message : 'Board authentication failed.');
    } finally {
      setSigningIn(false);
    }
  };

  if (loading) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="eyebrow">Board tools</p>
          <h1>Verifying access</h1>
          <p className="auth-copy">Checking your board authorization before loading the dashboard.</p>
        </section>
      </main>
    );
  }

  if (!token || !person || person.role !== 'board') {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <div className="auth-mark" aria-hidden="true">KG</div>
          <p className="eyebrow">Restricted area</p>
          <h1>Board member sign in</h1>
          <p className="auth-copy">
            This dashboard is limited to authorized board members. Sign in with your board credentials to continue.
          </p>

          {authError && <p className="alert error" role="alert">{authError}</p>}

          <form className="auth-form" onSubmit={handleLogin}>
            <label>
              Board email
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
              />
            </label>

            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>

            <button className="primary-button auth-submit" type="submit" disabled={signingIn}>
              {signingIn ? 'Authenticating…' : 'Sign in securely'}
            </button>
          </form>

          <p className="security-note">Your credentials are verified by the server before dashboard data is requested.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="board-shell">
      <header className="board-header">
        <div>
          <p className="eyebrow">Board tools</p>
          <h1>Application Review</h1>
          <p className="signed-in">Signed in as {person.first_name} {person.last_name}</p>
        </div>
        <button className="secondary-button" type="button" onClick={clearSession}>Sign out</button>
      </header>

      {error && <p className="alert error" role="alert">{error}</p>}

      <section className="stats-grid" aria-busy={loadingDashboard}>
        <article className="stat-card">
          <span>Pending</span>
          <strong>{summary.pending}</strong>
        </article>
        <article className="stat-card">
          <span>Approved</span>
          <strong>{summary.approved}</strong>
        </article>
        <article className="stat-card">
          <span>Waiting list</span>
          <strong>{summary.waiting_list}</strong>
        </article>
      </section>

      <section className="list-panel">
        <div className="section-heading">
          <h2>Recent submissions</h2>
          {loadingDashboard && <span className="loading-label">Refreshing…</span>}
        </div>
        <table>
          <thead>
            <tr>
              <th>Applicant</th>
              <th>Type</th>
              <th>Status</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            {applications.length === 0 ? (
              <tr>
                <td colSpan={4}>No applications found yet.</td>
              </tr>
            ) : (
              applications.map((app) => (
                <tr key={app.id}>
                  <td>{app.name}</td>
                  <td>{app.type}</td>
                  <td><span className="status-pill">{app.status}</span></td>
                  <td>${Number(app.amount || 0).toFixed(2)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
