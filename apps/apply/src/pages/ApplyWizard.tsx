import { useEffect, useState } from 'react';
import { api } from '@shared/api';
import { formatMoney } from '@shared/format';
import { Link, navigate, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, ErrorState, FormErrors, Loading, TextArea, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth, useProfile } from '../auth';
import { DocumentUpload } from '../components/DocumentUpload';
import { ProfileFields, profileForm, profilePayload, type ProfileForm } from '../components/ProfileFields';
import type { Application, FormDefinition, Profile } from '../types';

const STEPS = ['Application type', 'Your information', 'Documents', 'Read and sign the Range Rules'];
const EDITABLE = ['draft', 'needs_info'];
const WWW_URL: string = import.meta.env.VITE_WWW_URL || 'http://localhost:4173';

/** Which wizard step owns each server-side validation error. */
function stepForError(field: string): number {
  if (field.startsWith('document_') || field === 'documentation_method') return 2;
  if (['accept_rules', 'rules_version', 'printed_name', 'signature_name'].includes(field)) return 3;
  return 1;
}

export function ApplyWizard() {
  usePageTitle('Membership application');
  const { query } = useLocation();
  const profile = useProfile();
  const { setProfile } = useAuth();
  const step = Math.min(Math.max(Number(query.get('step') ?? 0), 0), STEPS.length - 1);
  const requestedType = query.get('type') === 'waiting_list' ? 'waiting_list' : query.get('type') === 'renewal' ? 'renewal' : null;

  const form = useAsync((signal) => api<FormDefinition>('/api/application/form', { signal }), []);
  const existing = useAsync((signal) => api<Application[]>('/api/applications', { signal }), []);
  const [application, setApplication] = useState<Application | null>(null);

  const open = existing.data?.find((a) => ['draft', 'submitted', 'needs_info', 'approved'].includes(a.status));
  useEffect(() => {
    if (open) setApplication(open);
  }, [open]);

  if (form.loading || existing.loading) return <Loading />;
  if (form.error || existing.error) return <ErrorState message={form.error ?? existing.error ?? ''} onRetry={() => { form.reload(); existing.reload(); }} />;
  if (application && !EDITABLE.includes(application.status)) {
    return (
      <section className="card stack">
        <h1>You already have an application in progress</h1>
        <p>Your {application.application_type === 'renewal' ? 'renewal' : 'waiting-list application'} is: <strong>{application.status_label}</strong>.</p>
        <Link className="btn btn-primary" to={`/applications/${application.id}`}>View your application</Link>
      </section>
    );
  }

  const go = (n: number) => navigate(`/apply?step=${n}`);
  const reload = async () => setApplication(await api<Application>(`/api/applications/${application!.id}`));

  return (
    <div className="wizard">
      <header className="stack-sm">
        <p className="kicker">{application?.application_type === 'waiting_list' ? 'Waiting-list application' : application ? 'Membership renewal' : 'Membership'}</p>
        <h1>Membership application</h1>
        {application?.status === 'needs_info' && (
          <Alert kind="warning" title="The board needs more information:">{application.info_request_message}</Alert>
        )}
      </header>
      <ol className="stepper" aria-label="Application progress">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? 'step' : undefined} className={i < step ? 'done' : i === step ? 'current' : ''}>
            <span className="step-number" aria-hidden="true">{i + 1}</span>
            <span className="step-label">{label}</span>
          </li>
        ))}
      </ol>
      <p className="step-count" aria-live="polite">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>

      {step === 0 && <TypeStep form={form.data!} profile={profile} application={application} requested={requestedType}
        onStarted={(a) => { setApplication(a); go(1); }} />}
      {step > 0 && !application && <Alert kind="info">Choose an application type first. <Link to="/apply?step=0">Start here</Link>.</Alert>}
      {step === 1 && application && <InfoStep application={application} profile={profile} onSaved={(p) => { setProfile(p); go(2); }} onBack={() => go(0)} />}
      {step === 2 && application && <DocumentsStep application={application} form={form.data!} reload={reload} onNext={() => go(3)} onBack={() => go(1)} />}
      {step === 3 && application && <SignStep application={application} form={form.data!} profile={profile} onBack={() => go(2)} goToStep={go} />}
    </div>
  );
}

function TypeStep({ form, profile, application, requested, onStarted }: {
  form: FormDefinition;
  profile: Profile;
  application: Application | null;
  requested: 'renewal' | 'waiting_list' | null;
  onStarted: (application: Application) => void;
}) {
  const suggested = profile.membership_status === 'member' || profile.membership_status === 'expired' ? 'renewal' : 'waiting_list';
  const [type, setType] = useState<'renewal' | 'waiting_list'>(application?.application_type ?? requested ?? suggested);
  const start = useAction(async () => {
    const created = await api<Application>('/api/applications', { body: { application_type: type } });
    onStarted(created);
  });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void start.run(); }}>
      <h2>What would you like to do?</h2>
      <FormErrors error={start.error} />
      <fieldset className="option-grid">
        <legend className="visually-hidden">Application type</legend>
        <label className={`option ${type === 'renewal' ? 'selected' : ''}`}>
          <input type="radio" name="type" value="renewal" checked={type === 'renewal'} onChange={() => setType('renewal')} />
          <span>
            <strong>Renew my membership</strong>
            <span className="small muted" style={{ display: 'block' }}>For current members. Dues are {formatMoney(form.dues_amount)} per year.</span>
          </span>
        </label>
        <label className={`option ${type === 'waiting_list' ? 'selected' : ''} ${!form.accepting_waiting_list ? 'disabled' : ''}`}>
          <input type="radio" name="type" value="waiting_list" checked={type === 'waiting_list'} disabled={!form.accepting_waiting_list}
            onChange={() => setType('waiting_list')} />
          <span>
            <strong>Apply for the waiting list</strong>
            <span className="small muted" style={{ display: 'block' }}>
              {form.accepting_waiting_list ? 'For new members. Requires a background check or concealed carry license.' : 'The waiting list is closed right now.'}
            </span>
          </span>
        </label>
      </fieldset>
      <div className="wizard-nav"><span /><button className="btn btn-primary" type="submit" disabled={start.busy}>Continue</button></div>
    </form>
  );
}

function InfoStep({ application, profile, onSaved, onBack }: { application: Application; profile: Profile; onSaved: (p: Profile) => void; onBack: () => void }) {
  const [form, setForm] = useState<ProfileForm>(() => profileForm(profile));
  const save = useAction(async () => {
    await api(`/api/applications/${application.id}`, { method: 'PATCH', body: { profile: profilePayload(form) } });
    onSaved(await api<Profile>('/api/me'));
  });
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }} noValidate>
      <h2>Your information</h2>
      <p className="muted">Check that everything is current. This updates your record with the club. Signed in as {profile.email}.</p>
      <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
      <ProfileFields form={form} onChange={setForm} errors={save.fieldErrors} nraRequired={application.application_type === 'renewal'} />
      <div className="wizard-nav">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button className="btn btn-primary" type="submit" disabled={save.busy}>{save.busy ? 'Saving…' : 'Save and continue'}</button>
      </div>
    </form>
  );
}

function DocumentsStep({ application, form, reload, onNext, onBack }: {
  application: Application; form: FormDefinition; reload: () => Promise<void>; onNext: () => void; onBack: () => void;
}) {
  const [notes, setNotes] = useState(application.applicant_notes ?? '');
  const update = useAction(async (body: Record<string, unknown>) => {
    await api(`/api/applications/${application.id}`, { method: 'PATCH', body });
    await reload();
  });
  const missing = application.document_requirements.filter((r) => r.required && !application.documents.some((d) => d.document_type === r.document_type && d.review_status !== 'rejected'));
  const needsMethod = application.application_type === 'waiting_list' && !application.documentation_method;
  const next = useAction(async () => {
    if (needsMethod) throw new Error('Choose whether you are providing a background check or a concealed carry license.');
    if (missing.length) throw new Error(`Please upload: ${missing.map((m) => m.label.toLowerCase()).join(', ')}.`);
    await api(`/api/applications/${application.id}`, { method: 'PATCH', body: { applicant_notes: notes } });
    onNext();
  });

  return (
    <section className="card stack" aria-labelledby="docs-heading">
      <h2 id="docs-heading">Documents</h2>
      <p className="muted">Your documents are private: only the board can view them.</p>
      <FormErrors error={update.error ?? next.error} />

      {application.application_type === 'waiting_list' && (
        <fieldset className="stack-sm">
          <legend className="required">Background check, or a concealed carry license</legend>
          <p className="small muted">
            New members need <strong>one</strong> of these.
            {form.background_check_url && <> Background checks are available from <a href={form.background_check_url} rel="noopener noreferrer">Criminal Watch Dog</a>.</>}
          </p>
          <div className="option-grid">
            {(['background_check', 'concealed_carry'] as const).map((method) => (
              <label key={method} className={`option ${application.documentation_method === method ? 'selected' : ''}`}>
                <input type="radio" name="documentation_method" checked={application.documentation_method === method}
                  onChange={() => void update.run({ documentation_method: method })} />
                <strong>{method === 'background_check' ? 'Background check cover page' : 'Concealed carry license from any state'}</strong>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {application.application_type === 'renewal' && (
        <Checkbox
          checked={application.claims_cleanup_discount}
          onChange={(e) => void update.run({ claims_cleanup_discount: e.target.checked })}
          label="I'm claiming the range cleanup-day discount"
          hint={Number(form.cleanup_discount_amount) > 0
            ? `Upload your cleanup card below. The board approves the ${formatMoney(form.cleanup_discount_amount)} discount before you pay.`
            : 'Upload your cleanup card below; the board reviews discount claims before you pay.'}
        />
      )}

      {application.document_requirements
        .filter((r) => r.required || r.document_type === 'cleanup_discount' || r.document_type === application.documentation_method)
        .map((requirement) => (
          <DocumentUpload key={requirement.document_type} applicationId={application.id} requirement={requirement}
            documents={application.documents} editable maxMb={form.max_upload_mb} onChange={() => void reload()} />
        ))}

      <TextArea label="Anything the board should know? (optional)" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />

      <div className="wizard-nav">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button type="button" className="btn btn-primary" disabled={next.busy || update.busy} onClick={() => void next.run()}>Continue</button>
      </div>
    </section>
  );
}

function SignStep({ application, form, profile, onBack, goToStep }: {
  application: Application; form: FormDefinition; profile: Profile; onBack: () => void; goToStep: (n: number) => void;
}) {
  const [accept, setAccept] = useState(false);
  const [printed, setPrinted] = useState(`${profile.first_name} ${profile.last_name}`.trim());
  const [signature, setSignature] = useState('');
  const submit = useAction(async () => {
    const result = await api<Application>(`/api/applications/${application.id}/submit`, {
      body: { rules_version: form.rules.version, accept_rules: accept, printed_name: printed, signature_name: signature },
    });
    navigate(`/applications/${result.id}?submitted=1`, { replace: true });
  });
  const stepsWithErrors = [...new Set(Object.keys(submit.fieldErrors).map(stepForError))].filter((s) => s !== 3);

  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void submit.run(); }} noValidate>
      <h2>Read and sign the Range Rules</h2>
      <p className="muted">Please read every rule, then sign at the bottom to send your application to the board.</p>
      <ol className="rules-list">{form.rules.rules.map((rule) => <li key={rule}>{rule}</li>)}</ol>
      {form.rules.reporting_clause && <p className="muted">{form.rules.reporting_clause}</p>}
      <p className="small muted">
        Prefer paper? <a href={`${WWW_URL}/membership`}>Download the printable agreement</a> from the Membership page.
      </p>
      <h3>Your application</h3>
      <FormErrors error={submit.error} fieldErrors={submit.fieldErrors} />
      {stepsWithErrors.length > 0 && (
        <p className="row">{stepsWithErrors.map((s) => <button key={s} type="button" className="btn btn-sm" onClick={() => goToStep(s)}>Fix: {STEPS[s]}</button>)}</p>
      )}
      {!profile.email_verified && <Alert kind="warning">Verify your email address before submitting. Check your inbox for the link.</Alert>}

      <dl className="summary">
        <div><dt>Application</dt><dd>{application.application_type === 'renewal' ? 'Membership renewal' : 'Waiting list'}</dd></div>
        <div><dt>Name</dt><dd>{profile.first_name} {profile.last_name}</dd></div>
        <div><dt>Address</dt><dd>{[profile.address_line1, profile.city, profile.state, profile.zip_code].filter(Boolean).join(', ') || '—'}</dd></div>
        <div><dt>Phone</dt><dd>{profile.phone ?? '—'}</dd></div>
        <div><dt>NRA (National Rifle Association)</dt><dd>{profile.nra_number ?? 'Number not provided'} · expires {profile.nra_expiration_date ?? '—'}</dd></div>
        <div><dt>Documents</dt><dd>{application.documents.map((d) => d.label).join(', ') || 'None uploaded'}</dd></div>
      </dl>

      <div className="agreement">
        <p>{form.rules.agreement_clause}</p>
      </div>
      <Checkbox label="I have read, understand, and agree to follow the Kiowa Gun Club Range Rules." checked={accept} onChange={(e) => setAccept(e.target.checked)} />
      {submit.fieldErrors.accept_rules && <span className="error">{submit.fieldErrors.accept_rules}</span>}
      <div className="grid-2">
        <TextField label="Printed name (first and last)" required autoComplete="name" value={printed} onChange={(e) => setPrinted(e.target.value)} error={submit.fieldErrors.printed_name} />
        <TextField label="Type your full name to sign" hint="It must match your printed name." required className="signature-input" value={signature}
          onChange={(e) => setSignature(e.target.value)} error={submit.fieldErrors.signature_name} placeholder="Sign here" />
      </div>
      <p className="small muted">Typing your name is your signature. We save the date, time, and the version of the rules you agreed to.</p>
      <div className="wizard-nav">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button className="btn btn-primary" type="submit" disabled={submit.busy || !accept}>{submit.busy ? 'Submitting…' : 'Sign and submit application'}</button>
      </div>
    </form>
  );
}
