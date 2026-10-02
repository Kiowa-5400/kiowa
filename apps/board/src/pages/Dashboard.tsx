import { api } from '@shared/api';
import { formatClock, formatDate, formatDateTime, formatMoney } from '@shared/format';
import { Link, usePageTitle } from '@shared/router';
import { ErrorState, Loading, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader } from '../components/common';

type Dashboard = {
  applications: { pending_renewals: number; pending_waiting_list: number; needs_info: number; awaiting_payment: number };
  groups: { key: string; label: string; count: number }[];
  needs_attention: { kind: 'application' | 'document'; id: number; person_id: number; application_id?: number | null; title: string; since: string | null }[];
  documents_pending_review: number;
  renewal: { next_cutoff: string; days_until_cutoff: number; dues_season: boolean; members_paid_up: number; members_not_renewed: number; nra_lapsed: number };
  upcoming_events: { id: number; title: string; local_date: string; local_time: string | null }[];
  upcoming_matches: { id: number; discipline: string; event_date: string; has_results: boolean }[];
  recent_matches_missing_results: number;
  last_email: { subject: string; created_at: string; sent: number; failed: number; opened: number; bounced: number } | null;
  last_sms: { body: string; created_at: string; sent: number; failed: number; delivered: number } | null;
  payments?: { collected_this_year: string; recent: { id: number; name: string; amount: string; method: string; status: string; paid_at: string | null }[] };
  locked_board_accounts?: { board_user_id: number; name: string; locked_until: string }[];
};

function Stat({ value, label, to, warn }: { value: number | string; label: string; to?: string; warn?: boolean }) {
  const body = (
    <>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </>
  );
  return to ? <Link to={to} className={`stat ${warn ? 'stat-warn' : ''}`}>{body}</Link> : <div className={`stat ${warn ? 'stat-warn' : ''}`}>{body}</div>;
}

export function DashboardPage() {
  usePageTitle('Dashboard');
  const { session } = useAuth();
  const data = useAsync((signal) => api<Dashboard>('/api/board/dashboard', { signal }), []);
  if (data.loading) return <Loading />;
  if (data.error || !data.data) return <ErrorState message={data.error ?? ''} onRetry={data.reload} />;
  const d = data.data;
  const group = (key: string) => d.groups.find((g) => g.key === key)?.count ?? 0;

  return (
    <div className="stack">
      <PageHeader title={`Welcome, ${session?.person.first_name}`}
        description={<>To change the words or pictures on the public website, use <Link to="/website">Website text &amp; photos</Link> in the menu.</>} />

      <section className="card stack" aria-labelledby="attention-heading">
        <h2 id="attention-heading">Needs attention</h2>
        {d.needs_attention.length === 0 ? (
          <p className="muted">Nothing waiting for review. 🎉</p>
        ) : (
          <ul className="attention-list">
            {d.needs_attention.map((item) => (
              <li key={`${item.kind}-${item.id}`}>
                <Link to={item.kind === 'application' ? `/applications/${item.id}` : item.application_id ? `/applications/${item.application_id}` : `/documents`}>
                  {item.title}
                </Link>
                {item.since && <span className="small muted"> · since {formatDateTime(item.since)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="membership-heading" className="stack-sm">
        <h2 id="membership-heading">Membership</h2>
        <div className="stats">
          <Stat value={d.applications.pending_renewals} label="Renewals to review" to="/applications?status=submitted" warn={d.applications.pending_renewals > 0} />
          <Stat value={d.applications.pending_waiting_list} label="Waiting-list applications to review" to="/applications?status=submitted" warn={d.applications.pending_waiting_list > 0} />
          <Stat value={d.applications.awaiting_payment} label="Approved, waiting to pay" to="/applications?status=approved" />
          <Stat value={d.documents_pending_review} label="Documents to check" to="/documents" warn={d.documents_pending_review > 0} />
          <Stat value={group('active_members')} label="Active members" to="/members?group=active_members" />
          <Stat value={group('waiting_list')} label="On the waiting list" to="/members?group=waiting_list" />
          <Stat value={group('former')} label="Former, expired or terminated" to="/members?group=former" />
        </div>
      </section>

      <section aria-labelledby="dues-heading" className="stack-sm">
        <h2 id="dues-heading">Dues</h2>
        <p className="muted">
          {d.renewal.dues_season
            ? <>Dues are due by <strong>{formatDate(d.renewal.next_cutoff, 'medium')}</strong> ({d.renewal.days_until_cutoff} days from today). Members who haven't paid by then are moved to Terminated automatically.</>
            : <>Next dues are due by {formatDate(d.renewal.next_cutoff, 'medium')}. Reminders go out automatically 45 and 15 days before.</>}
        </p>
        <div className="stats">
          <Stat value={d.renewal.members_paid_up} label="Members paid up" />
          <Stat value={d.renewal.members_not_renewed} label="Members who still owe dues" warn={d.renewal.members_not_renewed > 0} to="/members?group=active_members&sort=renewal" />
          <Stat value={d.renewal.nra_lapsed} label="Members with expired NRA" warn={d.renewal.nra_lapsed > 0} />
          {d.payments && <Stat value={formatMoney(d.payments.collected_this_year)} label="Collected this year" to="/payments" />}
        </div>
      </section>

      <div className="grid-2">
        <section className="card" aria-labelledby="events-heading">
          <h2 id="events-heading">Coming up</h2>
          {d.upcoming_events.length === 0 ? <p className="muted">Nothing on the calendar.</p> : (
            <ul className="plain-list">
              {d.upcoming_events.map((e) => <li key={e.id}><strong>{formatDate(e.local_date, 'short')}</strong> {formatClock(e.local_time)} — {e.title}</li>)}
            </ul>
          )}
          <p><Link to="/calendar">Manage the calendar →</Link></p>
          {d.recent_matches_missing_results > 0 && (
            <p className="small">⚠ {d.recent_matches_missing_results} recent match{d.recent_matches_missing_results === 1 ? ' needs a' : 'es need'} results link. <Link to="/matches">Add results</Link></p>
          )}
        </section>

        <section className="card" aria-labelledby="messages-heading">
          <h2 id="messages-heading">Recent messages</h2>
          {d.last_email ? (
            <p>Last email, “{d.last_email.subject}”, went to {d.last_email.sent} people on {formatDateTime(d.last_email.created_at)}.
              {d.last_email.sent > 0 && ` ${d.last_email.opened} opened it.`}{d.last_email.bounced > 0 && ` ${d.last_email.bounced} didn't go through.`}</p>
          ) : <p className="muted">No emails sent yet.</p>}
          {d.last_sms ? (
            <p>Last text went to {d.last_sms.sent} people on {formatDateTime(d.last_sms.created_at)}; {d.last_sms.delivered} confirmed delivered.</p>
          ) : <p className="muted">No texts sent yet.</p>}
          <p className="row"><Link to="/email">Email →</Link><Link to="/sms">Texts →</Link></p>
        </section>
      </div>

      {d.payments && d.payments.recent.length > 0 && (
        <section className="card" aria-labelledby="payments-heading">
          <h2 id="payments-heading">Recent payments</h2>
          <div className="table-wrap">
            <table className="table-stack">
              <thead><tr><th>Member</th><th>Amount</th><th>How</th><th>Status</th><th>Date</th></tr></thead>
              <tbody>
                {d.payments.recent.map((p) => (
                  <tr key={p.id}>
                    <td data-label="Member">{p.name}</td><td data-label="Amount">{formatMoney(p.amount)}</td>
                    <td data-label="How">{p.method}</td><td data-label="Status">{p.status.replace('_', ' ')}</td>
                    <td data-label="Date">{formatDateTime(p.paid_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.locked_board_accounts && d.locked_board_accounts.length > 0 && (
        <section className="card" aria-labelledby="locked-heading">
          <h2 id="locked-heading">Locked board accounts</h2>
          <ul>{d.locked_board_accounts.map((a) => <li key={a.board_user_id}>{a.name}, locked until {formatDateTime(a.locked_until)}. <Link to="/board-users">Unlock</Link></li>)}</ul>
        </section>
      )}
    </div>
  );
}
