import { useEffect, useState } from 'react';
import { api } from '@shared/api';
import { formatDate, formatDateTime, formatMoney, STATUS_LABELS, titleCase } from '@shared/format';
import { Link, navigate, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth, useProfile } from '@shared/member/auth';
import { DocumentUpload } from '@shared/member/DocumentUpload';
import { ProfileFields, profileForm, profilePayload, type ProfileForm } from '@shared/member/ProfileFields';
import type { Application, PaymentSummary, Profile, UploadedDocument } from '@shared/member/types';
import { applyUrl } from '@shared/member/urls';

const OPEN = ['draft', 'submitted', 'needs_info', 'approved'];

// ---------------------------------------------------------------- home ----

export function DashboardPage() {
  usePageTitle('My membership');
  const profile = useProfile();
  const applications = useAsync((signal) => api<Application[]>('/api/applications', { signal }), []);
  const open = applications.data?.find((a) => OPEN.includes(a.status));
  const renewal = profile.renewal;

  return (
    <div className="stack">
      <header>
        <p className="kicker">Member portal</p>
        <h1>Hi, {profile.first_name}</h1>
      </header>

      {!profile.email_verified && <Alert kind="warning">Please verify your email address. Check your inbox for the link we sent.</Alert>}

      <div className="grid-2">
        <section className="card stack-sm" aria-labelledby="status-heading">
          <p className="kicker">Membership</p>
          <h2 id="status-heading">{STATUS_LABELS[profile.membership_status]}</h2>
          {profile.membership_status === 'member' && (
            renewal.is_current
              ? (renewal.paid_through && renewal.paid_through >= renewal.next_cutoff
                ? <p>Your dues are paid through <strong>{formatDate(renewal.paid_through, 'medium')}</strong>.</p>
                : <p>Your dues are paid for this year. Next dues are due by <strong>{formatDate(renewal.next_cutoff, 'medium')}</strong>.</p>)
              : <p>Your dues for this year are due by <strong>{formatDate(renewal.next_cutoff, 'medium')}</strong> ({renewal.days_until_cutoff} days from today).</p>
          )}
          {profile.member_since && <p className="small muted">Member since {formatDate(profile.member_since, 'medium')}</p>}
          {!profile.nra_active && <Alert kind="warning">Your NRA (National Rifle Association) membership is marked expired. <Link to="/profile#nra">Upload your current NRA card</Link>.</Alert>}
        </section>

        <section className="card stack-sm" aria-labelledby="app-heading">
          <p className="kicker">Applications</p>
          <h2 id="app-heading">{open ? (open.application_type === 'renewal' ? 'Your renewal' : 'Your waiting-list application') : 'Renew or apply'}</h2>
          {applications.loading && <Loading />}
          {applications.error && <ErrorState message={applications.error} onRetry={applications.reload} />}
          {open && (
            <>
              <p>Status: <strong>{open.status_label}</strong></p>
              {open.status === 'draft' || open.status === 'needs_info'
                ? <a className="btn btn-primary" href={applyUrl({ step: 1 })}>Continue my application</a>
                : open.eligibility.eligible
                  ? <Link className="btn btn-primary" to={`/applications/${open.id}/pay`}>Pay dues ({formatMoney(open.eligibility.amount)})</Link>
                  : <Link className="btn" to={`/applications/${open.id}`}>View my application</Link>}
            </>
          )}
          {applications.data && !open && (
            <>
              <p className="muted">
                {profile.membership_status === 'member' ? 'Renew your membership for the coming year.' : 'Join the waiting list to become a member.'}
              </p>
              <a className="btn btn-primary" href={applyUrl({ type: profile.membership_status === 'member' || profile.membership_status === 'expired' ? 'renewal' : 'waiting_list' })}>
                {profile.membership_status === 'member' || profile.membership_status === 'expired' ? 'Renew my membership' : 'Apply for the waiting list'}
              </a>
            </>
          )}
        </section>
      </div>

      <section className="card" aria-labelledby="history-heading">
        <h2 id="history-heading">History</h2>
        <History />
      </section>
    </div>
  );
}

function History() {
  const applications = useAsync((signal) => api<Application[]>('/api/applications', { signal }), []);
  const payments = useAsync((signal) => api<PaymentSummary[]>('/api/me/payments', { signal }), []);
  if (applications.loading || payments.loading) return <Loading />;
  const past = applications.data?.filter((a) => a.status !== 'draft') ?? [];
  return (
    <div className="grid-2">
      <div>
        <h3>Applications</h3>
        {past.length === 0 ? <p className="muted">None yet.</p> : (
          <ul className="plain-list">
            {past.map((a) => (
              <li key={a.id}>
                <Link to={`/applications/${a.id}`}>{a.application_type === 'renewal' ? 'Renewal' : 'Waiting list'} — {formatDate(a.submitted_at ?? a.created_at, 'medium')}</Link>
                <span className="small muted"> · {a.status_label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3>Payments</h3>
        {(payments.data ?? []).filter((p) => p.status !== 'pending').length === 0 ? <p className="muted">None yet.</p> : (
          <ul className="plain-list">
            {payments.data!.filter((p) => p.status !== 'pending').map((p) => (
              <li key={p.id}>
                {formatMoney(p.amount)} {p.method === 'card' ? 'online' : `by ${p.method}`} — {formatDateTime(p.paid_at ?? p.created_at)}
                <span className="small muted"> · {titleCase(p.status)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------- profile ----

export function ProfilePage() {
  usePageTitle('My information');
  const profile = useProfile();
  const { setProfile } = useAuth();
  const [form, setForm] = useState<ProfileForm>(() => profileForm(profile));
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    setSaved(false);
    setProfile(await api<Profile>('/api/me', { method: 'PATCH', body: profilePayload(form) }));
    setSaved(true);
  });
  const emailPrefs = useAction(async (optOut: boolean) => setProfile(await api<Profile>('/api/me/email-preferences', { method: 'PUT', body: { email_opt_out: optOut } })));

  return (
    <div className="stack">
      <header>
        <p className="kicker">Member portal</p>
        <h1>My information</h1>
        <p className="muted">Keep your contact details current so the club can reach you. Your email address is {profile.email}.</p>
      </header>
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }} noValidate>
        <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
        {saved && <Alert kind="success">Your information was saved.</Alert>}
        <ProfileFields form={form} onChange={setForm} errors={save.fieldErrors} />
        <div className="row"><button className="btn btn-primary" type="submit" disabled={save.busy}>{save.busy ? 'Saving…' : 'Save my information'}</button></div>
      </form>

      <section className="card stack" aria-labelledby="email-heading">
        <h2 id="email-heading">Club emails</h2>
        <FormErrors error={emailPrefs.error} />
        <Checkbox checked={!profile.email_opt_out} disabled={emailPrefs.busy} onChange={(e) => void emailPrefs.run(!e.target.checked)}
          label="Send me club newsletters and announcements"
          hint="You'll always get emails about your own account, applications and dues." />
      </section>

      <NraUpload />
      <ChangePassword />
    </div>
  );
}

function NraUpload() {
  const docs = useAsync((signal) => api<UploadedDocument[]>('/api/me/documents', { signal }), []);
  const [file, setFile] = useState<File | null>(null);
  const [done, setDone] = useState(false);
  const upload = useAction(async () => {
    if (!file) throw new Error('Choose a photo or PDF of your NRA card first.');
    const body = new FormData();
    body.append('file', file);
    await api('/api/me/nra-proof', { body });
    setDone(true);
    docs.reload();
  });
  const nra = docs.data?.filter((d) => d.document_type === 'nra_proof') ?? [];
  return (
    <section className="card stack" id="nra" aria-labelledby="nra-heading">
      <h2 id="nra-heading">Update your NRA card</h2>
      <p className="muted">Renewed your NRA (National Rifle Association) membership? Upload your new card and a board member will review it.</p>
      {nra[0] && <p className="small">Latest upload: {nra[0].original_filename} ({nra[0].review_status === 'pending' ? 'waiting for review' : nra[0].review_status}).</p>}
      {done && <Alert kind="success">Thanks! The board will review your new NRA card.</Alert>}
      <FormErrors error={upload.error} />
      <div className="field">
        <label htmlFor="nra-file">Photo or PDF of your current NRA card</label>
        <input id="nra-file" type="file" accept="image/*,application/pdf,.pdf,.heic" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <div className="row"><button type="button" className="btn" disabled={upload.busy} onClick={() => void upload.run()}>{upload.busy ? 'Uploading…' : 'Upload NRA card'}</button></div>
    </section>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const change = useAction(async () => {
    const result = await api<{ message: string }>('/api/auth/password/change', { body: { current_password: current, new_password: next } });
    setMessage(result.message);
    setCurrent('');
    setNext('');
  });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void change.run(); }} aria-labelledby="pw-heading">
      <h2 id="pw-heading">Change password</h2>
      <FormErrors error={change.error} />
      {message && <Alert kind="success">{message}</Alert>}
      <div className="grid-2">
        <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" required minLength={10} hint="At least 10 characters."
          value={next} onChange={(e) => setNext(e.target.value)} error={change.fieldErrors.new_password} />
      </div>
      <div className="row"><button className="btn" type="submit" disabled={change.busy}>Change password</button></div>
    </form>
  );
}

// ---------------------------------------------------------- application ----

const NEXT_STEPS: Record<Application['status'], string> = {
  draft: "You haven't sent this application yet.",
  submitted: "A board member will review your information and documents. When they're done, you'll get an email. If you're approved, it will have a link to pay your dues (and, for new members, details about the range orientation).",
  needs_info: 'The board needs a little more from you before they can finish reviewing.',
  approved: "You're approved! When the board opens payment, you'll get an email with a link, and you can pay here.",
  declined: 'The board was not able to approve this application. Contact the club if you have questions.',
  completed: 'All done. Your dues are paid and your membership is active.',
  withdrawn: 'You withdrew this application.',
};

export function ApplicationPage({ id }: { id: number }) {
  usePageTitle('My application');
  const { query } = useLocation();
  const application = useAsync((signal) => api<Application>(`/api/applications/${id}`, { signal }), [id]);
  const form = useAsync((signal) => api<{ max_upload_mb: number }>('/api/application/form', { signal }), []);
  const withdraw = useAction(async () => {
    if (!window.confirm('Withdraw this application? You can start a new one later.')) return;
    await api(`/api/applications/${id}/withdraw`, { method: 'POST' });
    application.reload();
  });

  if (application.loading) return <Loading />;
  if (application.error || !application.data) return <ErrorState message={application.error ?? 'Application not found.'} onRetry={application.reload} />;
  const a = application.data;

  return (
    <div className="stack">
      {query.get('submitted') && <Alert kind="success" title="Application sent.">Thank you! We also emailed you a confirmation.</Alert>}
      <header>
        <p className="kicker">{a.application_type === 'renewal' ? 'Membership renewal' : 'Waiting-list application'}</p>
        <h1>{a.status_label}</h1>
      </header>

      <section className="card stack-sm" aria-labelledby="next-heading">
        <h2 id="next-heading">What happens next</h2>
        <p>{NEXT_STEPS[a.status]}</p>
        {a.status === 'needs_info' && a.info_request_message && <Alert kind="warning" title="From the board:">{a.info_request_message}</Alert>}
        {a.status === 'declined' && a.decision_reason && <p className="muted">{a.decision_reason}</p>}
        <div className="row">
          {(a.status === 'draft' || a.status === 'needs_info') && <a className="btn btn-primary" href={applyUrl({ step: 1 })}>{a.status === 'draft' ? 'Finish my application' : 'Update and resubmit'}</a>}
          {a.eligibility.eligible && <Link className="btn btn-primary" to={`/applications/${a.id}/pay`}>Pay dues ({formatMoney(a.eligibility.amount)})</Link>}
          {['draft', 'submitted', 'needs_info'].includes(a.status) && (
            <button type="button" className="btn btn-danger" disabled={withdraw.busy} onClick={() => void withdraw.run()}>Withdraw application</button>
          )}
        </div>
        <FormErrors error={withdraw.error} />
      </section>

      <section className="card stack" aria-labelledby="docs-heading">
        <h2 id="docs-heading">Your documents</h2>
        {a.documents.length === 0 && <Empty>No documents uploaded.</Empty>}
        {a.document_requirements.filter((r) => r.required || a.documents.some((d) => d.document_type === r.document_type)).map((r) => (
          <DocumentUpload key={r.document_type} applicationId={a.id} requirement={r} documents={a.documents}
            editable={a.status === 'needs_info'} maxMb={form.data?.max_upload_mb ?? 10} onChange={application.reload} />
        ))}
      </section>

      {a.signed_at && (
        <p className="small muted">Signed by {a.signature_name} on {formatDateTime(a.signed_at)} (Range Rules version {a.rules_version}).</p>
      )}
    </div>
  );
}

// -------------------------------------------------------------- payment ----

export function PayPage({ id }: { id: number }) {
  usePageTitle('Pay dues');
  const { query } = useLocation();
  const application = useAsync((signal) => api<Application>(`/api/applications/${id}`, { signal }), [id]);
  const mode = useAsync((signal) => api<{ test_mode: boolean }>('/api/payments/mode', { signal }), []);
  const checkout = useAction(async () => {
    const { checkout_url } = await api<{ checkout_url: string }>(`/api/applications/${id}/checkout`, { method: 'POST' });
    window.location.assign(checkout_url);
  });

  if (application.loading) return <Loading />;
  if (application.error || !application.data) return <ErrorState message={application.error ?? 'Application not found.'} />;
  const { eligibility, application_type } = application.data;

  return (
    <section className="card stack pay-card" aria-labelledby="pay-heading">
      <p className="kicker">{application_type === 'renewal' ? 'Membership renewal' : 'New membership'}</p>
      <h1 id="pay-heading">Pay your dues</h1>
      {mode.data?.test_mode && (
        <Alert kind="warning" title="Test mode">
          Online payments are still being tested. No real charge will be made, and a payment here won't count toward your dues.
        </Alert>
      )}
      {query.get('cancelled') && <Alert kind="info">Payment was cancelled. Nothing was charged. You can try again whenever you're ready.</Alert>}
      {application.data.payment_status === 'paid' ? (
        <Alert kind="success">These dues are already paid. Thank you!</Alert>
      ) : eligibility.eligible ? (
        <>
          <p className="amount">{formatMoney(eligibility.amount)}</p>
          <p className="muted">Annual Kiowa Gun Club membership dues. You'll pay on Stripe's secure page; the club never sees your card number. Nothing is billed automatically.</p>
          <FormErrors error={checkout.error} />
          <button type="button" className="btn btn-primary btn-block" disabled={checkout.busy} onClick={() => void checkout.run()}>
            {checkout.busy ? 'Opening secure checkout…' : `Pay ${formatMoney(eligibility.amount)} securely`}
          </button>
          <p className="small muted">Prefer to pay by check or cash? Contact the club treasurer.</p>
        </>
      ) : (
        <Alert kind="info" title="Payment isn't open yet.">
          <ul>{eligibility.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </Alert>
      )}
      <Link to={`/applications/${id}`}>Back to my application</Link>
    </section>
  );
}

/** Stripe sends the member back here. We only report what the server has recorded from Stripe's confirmation. */
export function PaymentReturnPage() {
  usePageTitle('Payment');
  const { query } = useLocation();
  const { refresh } = useAuth();
  const sessionId = query.get('session_id') ?? '';
  const [status, setStatus] = useState<{ status: string; application_id: number | null; covers_through: string | null } | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return undefined;
    if (status && status.status !== 'pending') return undefined;
    const timer = window.setTimeout(async () => {
      try {
        const result = await api<{ status: string; application_id: number | null; covers_through: string | null }>(
          '/api/payments/checkout-status', { query: { session_id: sessionId } });
        setStatus(result);
        if (result.status === 'paid') void refresh();
      } catch (e) {
        setError((e as Error).message);
      }
      setAttempts((n) => n + 1);
    }, attempts === 0 ? 0 : 2500);
    return () => window.clearTimeout(timer);
  }, [sessionId, status, attempts, refresh]);

  return (
    <section className="card stack pay-card" aria-live="polite">
      <h1>Payment</h1>
      {error && <Alert kind="error">{error}</Alert>}
      {!status && !error && <Loading label="Checking your payment…" />}
      {status?.status === 'pending' && attempts < 12 && <Loading label="Waiting for confirmation from Stripe…" />}
      {status?.status === 'pending' && attempts >= 12 && (
        <Alert kind="info">We're still waiting for Stripe to confirm your payment. This can take a few minutes. We'll email your receipt when it's confirmed — you can safely close this page.</Alert>
      )}
      {status?.status === 'paid' && (
        <Alert kind="success" title="Payment received. Thank you!">
          {status.covers_through && <>Your membership is paid through {formatDate(status.covers_through, 'medium')}.</>} A receipt is on its way to your email.
        </Alert>
      )}
      {status && ['failed', 'cancelled'].includes(status.status) && <Alert kind="error">The payment didn't go through. Nothing was charged. Please try again.</Alert>}
      <button type="button" className="btn" onClick={() => navigate('/')}>Go to my membership</button>
    </section>
  );
}
