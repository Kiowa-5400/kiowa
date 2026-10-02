import { useState } from 'react';
import { api, API_BASE_URL, type Page } from '@shared/api';
import { formatDate, formatDateTime, formatMoney } from '@shared/format';
import { Link, navigate, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, TextArea, useAction, useAsync } from '@shared/ui';
import { PageHeader, Pager, StatusBadge, useDebounced } from '../components/common';

type Summary = {
  id: number; person_id: number; applicant_name: string; applicant_email: string; application_type: 'renewal' | 'waiting_list';
  status: string; status_label: string; submitted_at: string | null; payment_status: string; payment_eligible: boolean;
  payment_block_reason: string | null; pending_documents: number;
};

type Doc = { id: number; document_type: string; label: string; original_filename: string; mime_type: string; uploaded_at: string; review_status: string; review_notes: string | null };

type Detail = Summary & {
  documentation_method: string | null; claims_cleanup_discount: boolean; applicant_notes: string | null; rules_version: string | null;
  printed_name: string | null; signature_name: string | null; signed_at: string | null; info_request_message: string | null;
  decision_reason: string | null; payment_requested_at: string | null; documents: Doc[];
  eligibility: { eligible: boolean; reasons: string[]; amount: string };
  applicant: { id: number; name: string; email: string; phone: string | null; membership_status: string; nra_number: string | null; nra_expiration_date: string | null; nra_active: boolean; email_verified: boolean };
  submitted_profile: Record<string, string | boolean | null> | null;
  nra_verified_at: string | null; discount_approved: boolean; background_check_cleared: boolean;
  reviewed_by: string | null; reviewed_at: string | null; signature_ip: string | null;
  notes: { id: number; body: string; author_name: string | null; created_at: string }[];
  payments: { id: number; amount: string; status: string; method: string; paid_at: string | null }[];
};

const PROFILE_FIELDS: [string, string][] = [
  ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'Email'], ['phone', 'Phone'],
  ['address_line1', 'Address'], ['address_line2', 'Address line 2'], ['city', 'City'], ['state', 'State'], ['zip_code', 'ZIP'],
  ['nra_number', 'NRA number'], ['nra_expiration_date', 'NRA expires'], ['sms_opt_in', 'OK to text'],
];

const FILTERS = [
  { value: 'open', label: 'Open' },
  { value: 'submitted', label: 'Waiting for review' },
  { value: 'needs_info', label: 'Waiting on applicant' },
  { value: 'approved', label: 'Approved, waiting to pay' },
  { value: 'completed', label: 'Complete' },
  { value: 'declined', label: 'Declined' },
  { value: '', label: 'All' },
];

export function ApplicationsPage() {
  usePageTitle('Applications');
  const { query } = useLocation();
  const [status, setStatus] = useState(query.get('status') ?? 'open');
  const [type, setType] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const search = useDebounced(q);
  const list = useAsync((signal) => api<Page<Summary>>('/api/board/applications', { signal, query: { status, application_type: type, q: search, page } }), [status, type, search, page]);

  return (
    <div className="stack">
      <PageHeader title="Applications" description="Renewals and waiting-list applications sent in by members. Open one to review documents and approve it." />
      <div className="filters">
        <div className="field"><label htmlFor="f-status">Show</label>
          <select id="f-status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>{FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}</select></div>
        <div className="field"><label htmlFor="f-type">Type</label>
          <select id="f-type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">Both</option><option value="renewal">Renewals</option><option value="waiting_list">Waiting list</option>
          </select></div>
        <div className="field"><label htmlFor="f-q">Search</label><input id="f-q" type="search" value={q} placeholder="Name or email" onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
      </div>
      {list.loading && <Loading />}
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.data && list.data.items.length === 0 && <Empty>No applications match.</Empty>}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Applicant</th><th>Type</th><th>Status</th><th>Sent</th><th>Documents</th><th>Payment</th></tr></thead>
            <tbody>
              {list.data.items.map((a) => (
                <tr key={a.id}>
                  <td data-label="Applicant"><Link to={`/applications/${a.id}`}>{a.applicant_name}</Link><div className="small muted">{a.applicant_email}</div></td>
                  <td data-label="Type">{a.application_type === 'renewal' ? 'Renewal' : 'Waiting list'}</td>
                  <td data-label="Status"><StatusBadge status={a.status} label={a.status_label} /></td>
                  <td data-label="Sent">{formatDate(a.submitted_at, 'short')}</td>
                  <td data-label="Documents">{a.pending_documents > 0 ? <span className="badge badge-warning">{a.pending_documents} to check</span> : 'Checked'}</td>
                  <td data-label="Payment">{a.payment_status === 'paid' ? 'Paid' : a.payment_eligible ? 'Ready to pay dues' : 'Waiting on approval'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.data && <Pager page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />}
    </div>
  );
}

export function ApplicationDetail({ id }: { id: number }) {
  usePageTitle('Application');
  const detail = useAsync((signal) => api<Detail>(`/api/board/applications/${id}`, { signal }), [id]);
  const [message, setMessage] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [infoText, setInfoText] = useState('');
  const [declineReason, setDeclineReason] = useState('');
  const [sendPayment, setSendPayment] = useState(true);

  const act = useAction(async (path: string, body: unknown, done: string) => {
    await api(`/api/board/applications/${id}/${path}`, { method: 'POST', body });
    setMessage(done);
    detail.reload();
  });
  const review = useAction(async (docId: number, review_status: string) => {
    const notes = review_status === 'rejected' ? window.prompt('Tell the applicant why (optional):') ?? '' : '';
    await api(`/api/board/documents/${docId}/review`, { body: { review_status, notes } });
    detail.reload();
  });

  if (detail.loading && !detail.data) return <Loading />;
  if (detail.error || !detail.data) return <ErrorState message={detail.error ?? 'Not found'} onRetry={detail.reload} />;
  const a = detail.data;
  const reviewable = ['submitted', 'needs_info', 'approved'].includes(a.status);
  const isWaiting = a.application_type === 'waiting_list';
  const error = act.error ?? review.error;

  return (
    <div className="stack">
      <PageHeader
        title={a.applicant.name}
        description={<>{isWaiting ? 'Waiting-list application' : 'Membership renewal'} · <StatusBadge status={a.status} label={a.status_label} /></>}
        actions={<><Link className="btn" to={`/members/${a.applicant.id}`}>Contact record</Link><button type="button" className="btn btn-ghost" onClick={() => navigate('/applications')}>Back to list</button></>}
      />
      {message && <Alert kind="success">{message}</Alert>}
      <FormErrors error={error} />

      <div className="detail-grid">
        <div className="stack">
          <section className="card stack-sm" aria-labelledby="docs-h">
            <h2 id="docs-h">Documents</h2>
            {a.documents.length === 0 && <p className="muted">No documents uploaded.</p>}
            {a.documents.map((d) => (
              <div key={d.id} className="doc-row">
                <div>
                  <strong>{d.label}</strong>
                  <div className="small muted">{d.original_filename} · uploaded {formatDateTime(d.uploaded_at)}</div>
                  {d.review_notes && <div className="small">Note: {d.review_notes}</div>}
                </div>
                <div className="row">
                  <StatusBadge status={d.review_status} label={d.review_status === 'pending' ? 'to check' : d.review_status} />
                  <a className="btn btn-sm" href={`${API_BASE_URL}/api/board/documents/${d.id}/file`} target="_blank" rel="noopener">Open</a>
                  {d.review_status !== 'approved' && <button type="button" className="btn btn-sm" disabled={review.busy} onClick={() => void review.run(d.id, 'approved')}>Looks good</button>}
                  {d.review_status !== 'rejected' && <button type="button" className="btn btn-sm btn-danger" disabled={review.busy} onClick={() => void review.run(d.id, 'rejected')}>Not acceptable</button>}
                </div>
              </div>
            ))}
            <p className="small muted">Marking NRA proof “Looks good” verifies the NRA membership. Marking a background check or concealed carry license “Looks good” clears the background check.</p>
          </section>

          {reviewable && (
            <section className="card stack" aria-labelledby="decide-h">
              <h2 id="decide-h">Decision</h2>
              <ul className="checklist">
                <li className={a.nra_verified_at ? 'ok' : ''}>{a.nra_verified_at ? '✔' : '○'} NRA proof verified
                  {!a.nra_verified_at && <button type="button" className="btn btn-sm" onClick={() => void act.run('verify-nra', undefined, 'NRA proof marked verified.')}>Mark verified</button>}</li>
                {isWaiting && (
                  <li className={a.background_check_cleared ? 'ok' : ''}>{a.background_check_cleared ? '✔' : '○'} Background check cleared
                    <button type="button" className="btn btn-sm" onClick={() => void act.run(`background-check?cleared=${!a.background_check_cleared}`, undefined,
                      a.background_check_cleared ? 'Background check clearance removed.' : 'Background check cleared.')}>
                      {a.background_check_cleared ? 'Undo' : 'Mark cleared'}</button></li>
                )}
                {a.claims_cleanup_discount && (
                  <li className={a.discount_approved ? 'ok' : ''}>{a.discount_approved ? '✔' : '○'} Cleanup-day discount approved
                    <button type="button" className="btn btn-sm" onClick={() => void act.run(`discount?approved=${!a.discount_approved}`, undefined, 'Discount updated.')}>
                      {a.discount_approved ? 'Remove discount' : 'Approve discount'}</button></li>
                )}
              </ul>

              {a.status !== 'approved' && (
                <div className="stack-sm">
                  <Checkbox label="Email the payment link now" checked={sendPayment} onChange={(e) => setSendPayment(e.target.checked)}
                    hint="Leave this checked unless the applicant still needs something before paying (for example, a range orientation date)." />
                  <button type="button" className="btn btn-primary" disabled={act.busy}
                    onClick={() => void act.run('approve', { send_payment_request: sendPayment }, sendPayment ? 'Approved. The applicant was emailed a payment link.' : 'Approved.')}>
                    Approve application
                  </button>
                </div>
              )}
              {a.status === 'approved' && !a.payment_requested_at && (
                <button type="button" className="btn btn-primary" onClick={() => void act.run('payment-request', undefined, 'Payment link emailed.')}>Email the payment link</button>
              )}
              {a.status === 'approved' && a.payment_requested_at && (
                <p>Payment link sent {formatDateTime(a.payment_requested_at)}. {a.eligibility.eligible ? `They can pay ${formatMoney(a.eligibility.amount)} now.` : ''}
                  <button type="button" className="btn btn-sm" onClick={() => void act.run('payment-request', undefined, 'Payment link emailed again.')}>Send again</button></p>
              )}
              {!a.eligibility.eligible && a.status === 'approved' && <Alert kind="info">Can't pay yet: {a.eligibility.reasons.join(' ')}</Alert>}

              <details>
                <summary>Ask the applicant for more information</summary>
                <div className="stack-sm">
                  <TextArea label="What do they need to send or fix?" value={infoText} onChange={(e) => setInfoText(e.target.value)} />
                  <button type="button" className="btn" disabled={!infoText.trim() || act.busy}
                    onClick={() => void act.run('request-info', { message: infoText }, 'The applicant was emailed your request.').then(() => setInfoText(''))}>Send request</button>
                </div>
              </details>
              <details>
                <summary>Decline this application</summary>
                <div className="stack-sm">
                  <TextArea label="Reason (included in the email to the applicant)" value={declineReason} onChange={(e) => setDeclineReason(e.target.value)} />
                  <button type="button" className="btn btn-danger" disabled={act.busy}
                    onClick={() => { if (window.confirm('Decline this application?')) void act.run('decline', { reason: declineReason, notify_applicant: true }, 'Application declined.'); }}>Decline</button>
                </div>
              </details>
            </section>
          )}

          <section className="card stack-sm" aria-labelledby="notes-h">
            <h2 id="notes-h">Board notes</h2>
            <p className="small muted">Only board members see these.</p>
            {a.notes.map((n) => <blockquote key={n.id} className="note"><p>{n.body}</p><footer className="small muted">{n.author_name} · {formatDateTime(n.created_at)}</footer></blockquote>)}
            <TextArea label="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />
            <div><button type="button" className="btn" disabled={!note.trim()} onClick={() => void act.run('notes', { body: note }, 'Note added.').then(() => setNote(''))}>Add note</button></div>
          </section>
        </div>

        <aside className="stack">
          <section className="card stack-sm">
            <h2>Applicant</h2>
            <dl className="kv">
              <dt>Email</dt><dd>{a.applicant.email}{!a.applicant.email_verified && ' (not verified)'}</dd>
              <dt>Phone</dt><dd>{a.applicant.phone ?? '—'}</dd>
              <dt>Status</dt><dd>{a.applicant.membership_status.replace('_', ' ')}</dd>
              <dt>NRA number</dt><dd>{a.applicant.nra_number ?? '—'}</dd>
              <dt>NRA expires</dt><dd>{formatDate(a.applicant.nra_expiration_date, 'medium') || '—'}</dd>
              {isWaiting && <><dt>Providing</dt><dd>{a.documentation_method === 'concealed_carry' ? 'Concealed carry license' : 'Background check'}</dd></>}
            </dl>
            {a.applicant_notes && <p><strong>Applicant's note:</strong> {a.applicant_notes}</p>}
          </section>
          <section className="card stack-sm">
            <h2>Signature</h2>
            {a.signed_at ? (
              <p>Signed “{a.signature_name}” ({a.printed_name}) on {formatDateTime(a.signed_at)}. Range Rules version {a.rules_version}.{a.signature_ip && <span className="small muted"> From {a.signature_ip}.</span>}</p>
            ) : <p className="muted">Not signed yet.</p>}
          </section>
          {a.submitted_profile && (
            <section className="card stack-sm">
              <h2>As submitted</h2>
              <dl className="kv small">
                {PROFILE_FIELDS.filter(([k]) => a.submitted_profile![k] !== null && a.submitted_profile![k] !== undefined && a.submitted_profile![k] !== '').map(([k, label]) => {
                  const value = a.submitted_profile![k];
                  return <div key={k} className="kv-row"><dt>{label}</dt><dd>{typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}</dd></div>;
                })}
              </dl>
            </section>
          )}
          <section className="card stack-sm">
            <h2>Payments</h2>
            {a.payments.length === 0 ? <p className="muted">None.</p> : a.payments.map((p) => (
              <p key={p.id}>{formatMoney(p.amount)} {p.method} · <StatusBadge status={p.status} /> {formatDateTime(p.paid_at)}</p>
            ))}
            {a.reviewed_by && <p className="small muted">Reviewed by {a.reviewed_by} on {formatDateTime(a.reviewed_at)}</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
