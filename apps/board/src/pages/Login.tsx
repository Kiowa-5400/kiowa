import { useState } from 'react';
import { api } from '@shared/api';
import { Link, navigate, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, FormErrors, TextField, useAction } from '@shared/ui';
import { useAuth } from '../auth';

export function LoginPage() {
  usePageTitle('Board sign in');
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const login = useAction(async () => {
    await signIn(email, password, remember);
    navigate('/', { replace: true });
  });
  return (
    <>
      <p className="kicker">Board members only</p>
      <h1>Board sign in</h1>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void login.run(); }}>
        <FormErrors error={login.error} />
        <TextField label="Email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Checkbox label="Keep me signed in on this device" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <button className="btn btn-primary btn-block" type="submit" disabled={login.busy}>{login.busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <Link to="/forgot-password">Forgot your password?</Link>
    </>
  );
}

export function ForgotPasswordPage() {
  usePageTitle('Reset password');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const forgot = useAction(async () => setMessage((await api<{ message: string }>('/api/board/auth/password/forgot', { body: { email } })).message));
  return (
    <>
      <h1>Reset your password</h1>
      {message ? <Alert kind="success">{message}</Alert> : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void forgot.run(); }}>
          <FormErrors error={forgot.error} />
          <TextField label="Board email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn btn-primary btn-block" type="submit" disabled={forgot.busy}>Email me a reset link</button>
        </form>
      )}
      <Link to="/">Back to sign in</Link>
    </>
  );
}

export function ResetPasswordPage({ invite }: { invite: boolean }) {
  usePageTitle(invite ? 'Set up your board account' : 'Choose a new password');
  const { query } = useLocation();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [done, setDone] = useState(false);
  const reset = useAction(async () => {
    if (password !== confirm) throw new Error('The two passwords do not match.');
    await api('/api/board/auth/password/reset', { body: { token: query.get('token') ?? '', password } });
    setDone(true);
  });
  return (
    <>
      <h1>{invite ? 'Welcome! Choose your password' : 'Choose a new password'}</h1>
      {done ? (
        <>
          <Alert kind="success">Your password is set.</Alert>
          <button type="button" className="btn btn-primary" onClick={() => navigate('/')}>Sign in</button>
        </>
      ) : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void reset.run(); }}>
          <FormErrors error={reset.error} fieldErrors={reset.fieldErrors} />
          <TextField label="New password" type="password" autoComplete="new-password" required minLength={10} hint="At least 10 characters."
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextField label="Confirm password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button className="btn btn-primary btn-block" type="submit" disabled={reset.busy}>Save password</button>
        </form>
      )}
    </>
  );
}
