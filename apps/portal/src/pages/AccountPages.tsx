import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from '@shared/api';
import { Link, navigate, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, FormErrors, Loading, TextField, useAction } from '@shared/ui';
import { useAuth } from '@shared/member/auth';

function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  usePageTitle(title);
  return (
    <section className="auth-card card stack" aria-labelledby="auth-title">
      <h1 id="auth-title">{title}</h1>
      {children}
    </section>
  );
}

export function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [needsVerification, setNeedsVerification] = useState(false);
  const login = useAction(async () => {
    try {
      await signIn(email, password, remember);
    } catch (error) {
      setNeedsVerification(error instanceof Error && /verify/i.test(error.message));
      throw error;
    }
    navigate('/', { replace: true });
  });
  const resend = useAction(() => api('/api/auth/email/resend', { body: { email } }));

  return (
    <AuthCard title="Member sign in">
      <p className="muted">Sign in to renew your membership, apply for the waiting list, or update your information.</p>
      <form className="stack" onSubmit={(e: FormEvent) => { e.preventDefault(); void login.run(); }} noValidate>
        <FormErrors error={login.error} />
        {needsVerification && (
          <button type="button" className="btn btn-sm" disabled={resend.busy} onClick={() => void resend.run()}>
            {resend.busy ? 'Sending…' : 'Send a new verification link'}
          </button>
        )}
        <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Checkbox label="Keep me signed in on this device" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <button className="btn btn-primary btn-block" type="submit" disabled={login.busy}>{login.busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="row-between small">
        <Link to="/forgot-password">Forgot your password?</Link>
      </p>
      <div className="card card-muted stack-sm">
        <p style={{ margin: 0 }}><strong>First time here?</strong> Longtime members and new applicants both set up an account once.</p>
        <Link className="btn" to="/register">Set up your account</Link>
      </div>
    </AuthCard>
  );
}

export function RegisterPage() {
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', phone: '', password: '' });
  const [done, setDone] = useState<string | null>(null);
  const register = useAction(async () => {
    const result = await api<{ message: string }>('/api/auth/register', { body: { ...form, phone: form.phone || null } });
    setDone(result.message);
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });

  if (done) {
    return (
      <AuthCard title="Check your email">
        <Alert kind="success">{done}</Alert>
        <p className="muted">If the club already has your email on file, the email will have a link to choose your password instead. Didn't get anything in a few minutes? Check your spam folder, or contact the club.</p>
        <Link to="/login">Back to sign in</Link>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Set up your account">
      <p className="muted">Already a member? Use the email address the club has for you, and we'll connect your account to your membership record. New to the club? Set up an account to apply for the waiting list.</p>
      <p className="muted">We'll email you a link to confirm your address before you can sign in.</p>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void register.run(); }} noValidate>
        <FormErrors error={register.error} fieldErrors={register.fieldErrors} />
        <div className="grid-2">
          <TextField label="First name" autoComplete="given-name" required value={form.first_name} onChange={set('first_name')} error={register.fieldErrors.first_name} />
          <TextField label="Last name" autoComplete="family-name" required value={form.last_name} onChange={set('last_name')} error={register.fieldErrors.last_name} />
        </div>
        <TextField label="Email" type="email" autoComplete="email" required value={form.email} onChange={set('email')} error={register.fieldErrors.email} />
        <TextField label="Mobile phone" type="tel" autoComplete="tel" inputMode="tel" value={form.phone} onChange={set('phone')} error={register.fieldErrors.phone} />
        <TextField label="Password" type="password" autoComplete="new-password" required minLength={10} hint="At least 10 characters."
          value={form.password} onChange={set('password')} error={register.fieldErrors.password} />
        <button className="btn btn-primary btn-block" type="submit" disabled={register.busy}>{register.busy ? 'Setting up…' : 'Set up my account'}</button>
      </form>
      <p className="small">Already have an account? <Link to="/login">Log in</Link></p>
    </AuthCard>
  );
}

export function VerifyEmailPage() {
  const { query } = useLocation();
  const token = query.get('token') ?? '';
  const [state, setState] = useState<{ ok: boolean; message: string } | null>(null);
  // The token is single-use, so make sure it's only ever submitted once
  // (effects run twice in development under React StrictMode).
  const submitted = useRef(false);
  useEffect(() => {
    if (submitted.current) return;
    submitted.current = true;
    api<{ message: string }>('/api/auth/email/verify', { body: { token } })
      .then((r) => setState({ ok: true, message: r.message }))
      .catch((e: Error) => setState({ ok: false, message: e.message }));
  }, [token]);
  return (
    <AuthCard title="Verify your email">
      {!state && <Loading label="Verifying…" />}
      {state && <Alert kind={state.ok ? 'success' : 'error'}>{state.message}</Alert>}
      {state && <Link className="btn btn-primary" to="/login">Go to sign in</Link>}
    </AuthCard>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const forgot = useAction(async () => setSent((await api<{ message: string }>('/api/auth/password/forgot', { body: { email } })).message));
  return (
    <AuthCard title="Reset your password">
      {sent ? <Alert kind="success">{sent}</Alert> : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void forgot.run(); }}>
          <FormErrors error={forgot.error} />
          <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn btn-primary btn-block" type="submit" disabled={forgot.busy}>Email me a reset link</button>
        </form>
      )}
      <Link to="/login">Back to sign in</Link>
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const { query } = useLocation();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [done, setDone] = useState(false);
  const reset = useAction(async () => {
    if (password !== confirm) throw new Error('The two passwords do not match.');
    await api('/api/auth/password/reset', { body: { token: query.get('token') ?? '', password } });
    setDone(true);
  });
  return (
    <AuthCard title="Choose a new password">
      {done ? (
        <>
          <Alert kind="success">Your password has been set.</Alert>
          <Link className="btn btn-primary" to="/login">Sign in</Link>
        </>
      ) : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void reset.run(); }}>
          <FormErrors error={reset.error} />
          <TextField label="New password" type="password" autoComplete="new-password" required minLength={10} hint="At least 10 characters."
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextField label="Confirm new password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button className="btn btn-primary btn-block" type="submit" disabled={reset.busy}>Save password</button>
        </form>
      )}
    </AuthCard>
  );
}

export function UnsubscribePage() {
  const { query } = useLocation();
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const unsubscribe = useAction(async () => {
    try {
      const r = await api<{ message: string }>('/api/public/unsubscribe', { method: 'POST', query: { token: query.get('token') ?? '' } });
      setResult({ ok: true, message: r.message });
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    }
  });
  return (
    <AuthCard title="Unsubscribe from club emails">
      {result ? <Alert kind={result.ok ? 'success' : 'error'}>{result.message}</Alert> : (
        <>
          <p>Stop receiving newsletters and announcements from the Kiowa Gun Club? You'll still get emails about your own account, applications and dues.</p>
          <button className="btn btn-primary" type="button" disabled={unsubscribe.busy} onClick={() => void unsubscribe.run()}>Unsubscribe</button>
        </>
      )}
    </AuthCard>
  );
}
