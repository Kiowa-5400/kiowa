import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import './styles.css';

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

function App() {
  const [summary, setSummary] = useState<DashboardSummary>({ pending: 0, approved: 0, waiting_list: 0, total: 0 });
  const [applications, setApplications] = useState<Submission[]>([]);
  const [error, setError] = useState('');
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  useEffect(() => {
    const loadDashboard = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/dashboard`);
        if (!response.ok) {
          throw new Error('Unable to load dashboard.');
        }
        const payload = await response.json();
        setSummary(payload.summary);
        setApplications(payload.recent_applications || []);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load dashboard.');
      }
    };

    void loadDashboard();
  }, []);

  return (
    <main className="board-shell">
      <header className="board-header">
        <div>
          <p className="eyebrow">Board tools</p>
          <h1>Application Review</h1>
        </div>
        <button className="primary-button">Export report</button>
      </header>

      {error && <p className="alert error">{error}</p>}

      <section className="stats-grid">
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
        <h2>Recent submissions</h2>
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
