import React from 'react';
import ReactDOM from 'react-dom/client';
import './styles.css';

const applications = [
  { name: 'Maya Johnson', type: 'Renewal', status: 'Awaiting review', amount: '$150' },
  { name: 'Chris Lee', type: 'Waiting list', status: 'Documents missing', amount: '$0' },
  { name: 'Alicia Gomez', type: 'Renewal', status: 'Approved', amount: '$150' },
];

function App() {
  return (
    <main className="board-shell">
      <header className="board-header">
        <div>
          <p className="eyebrow">Board tools</p>
          <h1>Application Review</h1>
        </div>
        <button className="primary-button">Export report</button>
      </header>

      <section className="stats-grid">
        <article className="stat-card">
          <span>Pending</span>
          <strong>12</strong>
        </article>
        <article className="stat-card">
          <span>Approved</span>
          <strong>38</strong>
        </article>
        <article className="stat-card">
          <span>Waiting list</span>
          <strong>6</strong>
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
            {applications.map((app) => (
              <tr key={app.name}>
                <td>{app.name}</td>
                <td>{app.type}</td>
                <td><span className="status-pill">{app.status}</span></td>
                <td>{app.amount}</td>
              </tr>
            ))}
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
