import { useState } from 'react';
import { api, type Page } from '@shared/api';
import { formatDate, formatDateTime, formatMoney } from '@shared/format';
import { Link, usePageTitle } from '@shared/router';
import { Alert, Empty, ErrorState, FormErrors, Loading, Modal, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader, Pager, StatusBadge, useDebounced } from '../components/common';

type Payment = {
  id: number; person_id: number; person_name: string; person_email: string; application_id: number | null; application_type: string | null;
  amount: string; refunded_amount: string; status: string; method: string; paid_at: string | null; created_at: string;
  covers_through: string | null; failure_reason: string | null; notes: string | null; claims_discount: boolean; has_discount_document: boolean;
};
type Summary = {
  year: number; collected: string; refunded: string; by_method: { method: string; count: number; amount: string }[];
  by_month: { month: string; amount: string }[]; pending_checkouts: number; approved_awaiting_payment: number;
};

export function PaymentsPage() {
  usePageTitle('Payments');
  const { can } = useAuth();
  const [status, setStatus] = useState('');
  const [method, setMethod] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [refunding, setRefunding] = useState<Payment | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const search = useDebounced(q);
  const summary = useAsync((signal) => api<Summary>('/api/board/payments/summary', { signal }), []);
  const list = useAsync((signal) => api<Page<Payment>>('/api/board/payments', { signal, query: { status, method, q: search, page } }), [status, method, search, page]);
  const reconcile = useAction(async () => {
    const r = await api<{ checked: number; paid: number; cancelled: number }>('/api/board/payments/reconcile', { method: 'POST' });
    setMessage(`Checked ${r.checked} unfinished online payments with Stripe: ${r.paid} were actually paid, ${r.cancelled} were abandoned.`);
    list.reload(); summary.reload();
  });
  const max = Math.max(1, ...(summary.data?.by_month.map((m) => Number(m.amount)) ?? [1]));

  return (
    <div className="stack">
      <PageHeader title="Payments" description="Every dues payment, online or by check or cash. Online payments are confirmed by Stripe before they show as paid."
        actions={can('payments.manage') && <button type="button" className="btn" disabled={reconcile.busy} onClick={() => void reconcile.run()}>Check unfinished payments with Stripe</button>} />
      {message && <Alert kind="info">{message}</Alert>}
      <FormErrors error={reconcile.error} />
      {summary.data && (
        <div className="grid-2">
          <section className="card stack-sm" aria-labelledby="sum-h">
            <h2 id="sum-h">{summary.data.year} so far</h2>
            <p className="big-number">{formatMoney(summary.data.collected)}</p>
            <p className="small muted">collected after refunds ({formatMoney(summary.data.refunded)} refunded)</p>
            <ul className="plain-list">{summary.data.by_method.map((m) => <li key={m.method}>{m.method === 'card' ? 'Online (card)' : m.method}: {m.count} payments, {formatMoney(m.amount)}</li>)}</ul>
            <p className="small">{summary.data.approved_awaiting_payment} approved members haven't paid yet. <Link to="/applications?status=approved">See who</Link></p>
          </section>
          <section className="card" aria-labelledby="month-h">
            <h2 id="month-h">By month</h2>
            {summary.data.by_month.length === 0 ? <p className="muted">No payments yet this year.</p> : (
              <ul className="bar-list">
                {summary.data.by_month.map((m) => (
                  <li key={m.month}>
                    <span>{formatDate(`${m.month}-01`, 'medium').replace(/ \d+,/, '')}</span>
                    <span className="bar" style={{ width: `${(Number(m.amount) / max) * 100}%` }} aria-hidden="true" />
                    <span>{formatMoney(m.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      <div className="filters">
        <div className="field"><label htmlFor="p-q">Search</label><input id="p-q" type="search" placeholder="Name or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        <div className="field"><label htmlFor="p-status">Status</label>
          <select id="p-status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All</option><option value="paid">Paid</option><option value="pending">Started, not finished</option>
            <option value="refunded">Refunded</option><option value="partially_refunded">Partly refunded</option><option value="failed">Failed</option><option value="cancelled">Abandoned</option>
          </select></div>
        <div className="field"><label htmlFor="p-method">How</label>
          <select id="p-method" value={method} onChange={(e) => { setMethod(e.target.value); setPage(1); }}>
            <option value="">All</option><option value="card">Online</option><option value="check">Check</option><option value="cash">Cash</option>
          </select></div>
      </div>
      {list.loading && <Loading />}
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.data && list.data.items.length === 0 && <Empty>No payments match.</Empty>}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Member</th><th>Amount</th><th>How</th><th>Status</th><th>Date</th><th>Good through</th><th></th></tr></thead>
            <tbody>
              {list.data.items.map((p) => (
                <tr key={p.id}>
                  <td data-label="Member"><Link to={`/members/${p.person_id}`}>{p.person_name}</Link>
                    {p.claims_discount && <div className="small">{p.has_discount_document ? 'Cleanup-day discount (card on file)' : '⚠ Discount claimed, no card uploaded'}</div>}</td>
                  <td data-label="Amount">{formatMoney(p.amount)}{Number(p.refunded_amount) > 0 && <div className="small muted">{formatMoney(p.refunded_amount)} refunded</div>}</td>
                  <td data-label="How">{p.method === 'card' ? 'Online' : p.method}</td>
                  <td data-label="Status"><StatusBadge status={p.status} />{p.failure_reason && <div className="small muted">{p.failure_reason}</div>}</td>
                  <td data-label="Date">{formatDateTime(p.paid_at ?? p.created_at)}</td>
                  <td data-label="Good through">{formatDate(p.covers_through, 'medium') || '—'}</td>
                  <td data-label="">{can('payments.manage') && ['paid', 'partially_refunded'].includes(p.status) && <button type="button" className="btn btn-sm" onClick={() => setRefunding(p)}>Refund</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.data && <Pager page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />}
      <p className="small muted">To record a check or cash payment, open the member's record and choose “Record a check or cash payment.”</p>

      <Modal open={refunding !== null} title="Refund a payment" onClose={() => setRefunding(null)}>
        {refunding && <RefundForm payment={refunding} onDone={(text) => { setRefunding(null); setMessage(text); list.reload(); summary.reload(); }} />}
      </Modal>
    </div>
  );
}

function RefundForm({ payment, onDone }: { payment: Payment; onDone: (message: string) => void }) {
  const remaining = (Number(payment.amount) - Number(payment.refunded_amount)).toFixed(2);
  const [amount, setAmount] = useState(remaining);
  const [reason, setReason] = useState('');
  const refund = useAction(async () => {
    await api(`/api/board/payments/${payment.id}/refund`, { body: { amount, reason } });
    onDone(`Refunded ${formatMoney(amount)} to ${payment.person_name}.`);
  });
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void refund.run(); }}>
      <p>{payment.person_name} paid {formatMoney(payment.amount)} {payment.method === 'card' ? 'online' : `by ${payment.method}`}.</p>
      {payment.method === 'card'
        ? <p className="small muted">The money goes back to their card through Stripe. It usually shows up in 5–10 days.</p>
        : <p className="small muted">This only records the refund. Return the {payment.method} yourself.</p>}
      <p className="small muted">Refunding does not change their membership status; update that on their record if needed.</p>
      <FormErrors error={refund.error} fieldErrors={refund.fieldErrors} />
      <TextField label={`Amount (up to ${formatMoney(remaining)})`} inputMode="decimal" required value={amount} onChange={(e) => setAmount(e.target.value)} />
      <TextField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />
      <button className="btn btn-danger" type="submit" disabled={refund.busy}>{refund.busy ? 'Refunding…' : 'Refund'}</button>
    </form>
  );
}
