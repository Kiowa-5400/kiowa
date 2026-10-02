import { useState } from 'react';
import { api } from '@shared/api';
import { usePageTitle } from '@shared/router';
import { Alert, FormErrors, TextField, useAction } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader } from '../components/common';

export function AccountPage() {
  usePageTitle('My account');
  const { session } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const change = useAction(async () => {
    setMessage((await api<{ message: string }>('/api/board/auth/password/change', { body: { current_password: current, new_password: next } })).message);
    setCurrent(''); setNext('');
  });
  return (
    <div className="stack">
      <PageHeader title="My account" description={`${session?.person.email} · ${session?.role_label}${session?.position ? ` · ${session.position}` : ''}`} />
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void change.run(); }}>
        <h2>Change password</h2>
        <p className="small muted">This is the same password you use for the member portal.</p>
        <FormErrors error={change.error} fieldErrors={change.fieldErrors} />
        {message && <Alert kind="success">{message}</Alert>}
        <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" required minLength={10} hint="At least 10 characters." value={next} onChange={(e) => setNext(e.target.value)} />
        <div><button className="btn btn-primary" type="submit" disabled={change.busy}>Change password</button></div>
      </form>
    </div>
  );
}
