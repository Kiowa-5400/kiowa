import { useState } from 'react';
import { api } from '@shared/api';
import { formatDateTime } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, ErrorState, FormErrors, Loading, Modal, SelectField, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader } from '../components/common';

type BoardUser = {
  id: number; person_id: number; name: string; email: string; phone: string | null; role: string; role_label: string; position: string | null;
  is_active: boolean; has_password: boolean; locked_until: string | null; failed_login_count: number; last_login_at: string | null; can_manage: boolean;
};
type Role = { value: string; label: string; assignable: boolean };

const ROLE_HELP: Record<string, string> = {
  board_member: 'Website, calendar, matches, members, applications, documents and messages.',
  treasurer: 'Everything a board member can do, plus payments, refunds and contact list downloads.',
  vice_president: 'Everything, including adding and removing board users.',
  president: 'Everything, including adding and removing board users.',
  tech_admin: 'Everything. For the website administrator.',
};

export function BoardUsersPage() {
  usePageTitle('Board users');
  const { session } = useAuth();
  const users = useAsync((signal) => api<BoardUser[]>('/api/board/users', { signal }), []);
  const roles = useAsync((signal) => api<Role[]>('/api/board/roles', { signal }), []);
  const positions = useAsync((signal) => api<string[]>('/api/board/position-options', { signal }), []);
  const [inviting, setInviting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const act = useAction(async (user: BoardUser, kind: 'role' | 'position' | 'active' | 'unlock' | 'reset', value?: string | boolean) => {
    if (kind === 'unlock') await api(`/api/board/users/${user.id}/unlock`, { method: 'POST' });
    else if (kind === 'reset') setMessage((await api<{ message: string }>(`/api/board/users/${user.id}/send-reset`, { method: 'POST' })).message);
    else {
      if (kind === 'active' && value === false && !window.confirm(`Remove board access for ${user.name}? They stay on the contact list.`)) return;
      await api(`/api/board/users/${user.id}`, { method: 'PATCH', body: { [kind === 'active' ? 'is_active' : kind]: value } });
    }
    users.reload();
  });

  return (
    <div className="stack">
      <PageHeader title="Board users" description="Who can sign in to this board site, and what they can do."
        actions={<button type="button" className="btn btn-primary" onClick={() => setInviting(true)}>Add a board user</button>} />
      {message && <Alert kind="success">{message}</Alert>}
      <FormErrors error={act.error} />
      {users.loading && <Loading />}
      {users.error && <ErrorState message={users.error} onRetry={users.reload} />}
      <div className="stack">
        {users.data?.map((u) => (
          <section key={u.id} className={`card stack-sm ${u.is_active ? '' : 'inactive'}`} aria-label={u.name}>
            <div className="row-between">
              <div>
                <h2>{u.name} {!u.is_active && <span className="badge">No access</span>} {u.locked_until && <span className="badge badge-danger">Locked out</span>}</h2>
                <p className="small muted">{u.email}{u.phone && ` · ${u.phone}`} · {u.has_password ? (u.last_login_at ? `last signed in ${formatDateTime(u.last_login_at)}` : 'never signed in') : 'hasn\'t set a password yet'}</p>
              </div>
            </div>
            {u.can_manage && u.person_id !== session?.person.id ? (
              <div className="grid-3">
                <SelectField label="Access level" value={u.role} hint={ROLE_HELP[u.role]} onChange={(e) => void act.run(u, 'role', e.target.value)}>
                  {roles.data?.filter((r) => r.assignable || r.value === u.role).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </SelectField>
                <SelectField label="Title (display only)" value={u.position ?? ''} onChange={(e) => void act.run(u, 'position', e.target.value)}>
                  <option value="">—</option>
                  {[...new Set([...(positions.data ?? []), ...(u.position ? [u.position] : [])])].map((p) => <option key={p} value={p}>{p}</option>)}
                </SelectField>
              </div>
            ) : <p>{u.role_label}{u.position && ` · ${u.position}`}</p>}
            {u.can_manage && (
              <div className="row">
                {u.locked_until && <button type="button" className="btn btn-sm" onClick={() => void act.run(u, 'unlock')}>Unlock</button>}
                <button type="button" className="btn btn-sm" onClick={() => void act.run(u, 'reset')}>Email a password reset link</button>
                {u.person_id !== session?.person.id && (u.is_active
                  ? <button type="button" className="btn btn-sm btn-danger" onClick={() => void act.run(u, 'active', false)}>Remove board access</button>
                  : <button type="button" className="btn btn-sm" onClick={() => void act.run(u, 'active', true)}>Restore board access</button>)}
              </div>
            )}
          </section>
        ))}
      </div>
      <AddTitle onAdded={positions.reload} />
      <Modal open={inviting} title="Add a board user" onClose={() => setInviting(false)}>
        <Invite roles={roles.data ?? []} positions={positions.data ?? []} onDone={(text) => { setInviting(false); setMessage(text); users.reload(); }} />
      </Modal>
    </div>
  );
}

function Invite({ roles, positions, onDone }: { roles: Role[]; positions: string[]; onDone: (message: string) => void }) {
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', phone: '', role: 'board_member', position: '' });
  const invite = useAction(async () => {
    await api('/api/board/users', { body: { ...form, phone: form.phone || null, position: form.position || null } });
    onDone(`${form.first_name} was emailed instructions to sign in.`);
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void invite.run(); }}>
      <p className="small muted">They'll get an email with a link to choose their own password. You never see it.</p>
      <FormErrors error={invite.error} fieldErrors={invite.fieldErrors} />
      <div className="grid-2">
        <TextField label="First name" required value={form.first_name} onChange={set('first_name')} />
        <TextField label="Last name" required value={form.last_name} onChange={set('last_name')} />
      </div>
      <TextField label="Email" type="email" required value={form.email} onChange={set('email')} />
      <TextField label="Phone (optional)" type="tel" value={form.phone} onChange={set('phone')} />
      <SelectField label="Access level" value={form.role} hint={ROLE_HELP[form.role]} onChange={set('role')}>
        {roles.filter((r) => r.assignable).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
      </SelectField>
      <SelectField label="Title (display only)" value={form.position} onChange={set('position')}>
        <option value="">—</option>{positions.map((p) => <option key={p} value={p}>{p}</option>)}
      </SelectField>
      <button className="btn btn-primary" type="submit" disabled={invite.busy}>Send invitation</button>
    </form>
  );
}

function AddTitle({ onAdded }: { onAdded: () => void }) {
  const [label, setLabel] = useState('');
  const add = useAction(async () => {
    await api('/api/board/position-options', { body: { label } });
    setLabel('');
    onAdded();
  });
  return (
    <form className="card row" onSubmit={(e) => { e.preventDefault(); void add.run(); }}>
      <TextField label="Add a title to the list" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Range Officer" />
      <button className="btn" type="submit" disabled={!label.trim() || add.busy}>Add title</button>
      <FormErrors error={add.error} />
    </form>
  );
}
