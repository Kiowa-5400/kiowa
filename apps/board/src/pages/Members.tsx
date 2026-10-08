import { Fragment, useState } from 'react';
import { api, downloadFile, type Page } from '@shared/api';
import { formatDate, formatDateTime, formatMoney, STATUS_LABELS, titleCase } from '@shared/format';
import { Link, useLocation, usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, Modal, SelectField, TextArea, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader, Pager, StatusBadge, useDebounced, type GroupCount } from '../components/common';

type Person = {
  id: number; first_name: string; last_name: string; email: string; phone: string | null; city: string | null;
  membership_status: string; groups: string[]; renewal_date: string | null; nra_expiration_date: string | null; nra_active: boolean;
  sms_opt_in: boolean; email_opt_out: boolean; pending_documents: number; open_application_status: string | null; has_login: boolean;
};

type PersonDetail = Person & {
  address_line1: string | null; address_line2: string | null; state: string | null; zip_code: string | null;
  on_board: boolean; on_shooting_committee: boolean; member_since: string | null; terminated_at: string | null;
  nra_number: string | null; background_check_cleared: boolean; sms_opt_in_at: string | null; sms_opt_in_source: string | null;
  sms_opt_out_at: string | null; email_verified: boolean; notes: string | null; board_role: string | null;
};

type PersonRecord = {
  person: PersonDetail;
  applications: { id: number; application_type: string; status: string; status_label: string; submitted_at: string | null; payment_eligible: boolean }[];
  payments: { id: number; amount: string; status: string; method: string; paid_at: string | null; covers_through: string | null }[];
  documents: { id: number; label: string; original_filename: string; review_status: string; uploaded_at: string; purged: boolean }[];
  communications: { channel: string; subject: string; status: string; sent_at: string | null; opened_at: string | null }[];
};

const GROUP_LABELS: Record<string, string> = {
  active_members: 'Active', board: 'Board', shooting_committee: 'Shooting committee', waiting_list: 'Waiting list', non_members: 'Non-member', former: 'Former',
};

export function MembersPage() {
  usePageTitle('Members & contacts');
  const { can } = useAuth();
  const { query } = useLocation();
  const [q, setQ] = useState('');
  const [group, setGroup] = useState(query.get('group') ?? '');
  const [sort, setSort] = useState(query.get('sort') ?? 'name');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const search = useDebounced(q);
  const groups = useAsync((signal) => api<GroupCount[]>('/api/board/people/groups', { signal }), []);
  const list = useAsync((signal) => api<Page<Person>>('/api/board/people', { signal, query: { q: search, group: group ? [group] : undefined, sort, page } }), [search, group, sort, page]);

  return (
    <div className="stack">
      <PageHeader title="Members & contacts" description="Everyone the club keeps in touch with: members, the waiting list, board, and former members."
        actions={<>
          {can('members.edit') && <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>Add a person</button>}
          {can('members.edit') && <button type="button" className="btn" onClick={() => setImporting(true)}>Import a spreadsheet</button>}
          {can('members.export') && <button type="button" className="btn" onClick={() => setExporting(true)}>Download a list</button>}
        </>} />

      <div className="filters">
        <div className="field"><label htmlFor="m-q">Search</label><input id="m-q" type="search" placeholder="Name, email, phone or NRA number" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        <div className="field"><label htmlFor="m-group">Group</label>
          <select id="m-group" value={group} onChange={(e) => { setGroup(e.target.value); setPage(1); }}>
            <option value="">Everyone</option>
            {groups.data?.map((g) => <option key={g.key} value={g.key}>{g.label} ({g.count})</option>)}
          </select></div>
        <div className="field"><label htmlFor="m-sort">Sort by</label>
          <select id="m-sort" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
            <option value="name">Last name</option><option value="renewal">Renewal date</option><option value="recent">Newest first</option>
          </select></div>
      </div>

      {list.loading && <Loading />}
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.data && list.data.items.length === 0 && <Empty>No one matches.</Empty>}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Paid through</th><th><span className="visually-hidden">Details</span></th></tr></thead>
            <tbody>
              {list.data.items.map((p) => (
                <Fragment key={p.id}>
                  <tr>
                    <td data-label="Name"><Link to={`/members/${p.id}`}>{p.last_name}, {p.first_name}</Link>
                      {p.pending_documents > 0 && <span className="badge badge-warning" style={{ marginLeft: 6 }}>{p.pending_documents} doc{p.pending_documents === 1 ? '' : 's'} to check</span>}</td>
                    <td data-label="Email">{p.email}</td>
                    <td data-label="Status"><StatusBadge status={p.membership_status} label={STATUS_LABELS[p.membership_status]} /></td>
                    <td data-label="Paid through">{formatDate(p.renewal_date, 'medium') || '—'}</td>
                    <td data-label="">
                      <button type="button" className="btn btn-sm" aria-expanded={expanded === p.id} onClick={() => setExpanded(expanded === p.id ? null : p.id)}>
                        {expanded === p.id ? 'Hide details' : 'Details'}
                      </button>
                    </td>
                  </tr>
                  {expanded === p.id && (
                    <tr className="details-row">
                      <td colSpan={5} data-label="">
                        <dl className="kv inline-kv">
                          <dt>Phone</dt><dd>{p.phone ?? '—'}</dd>
                          <dt>Town</dt><dd>{p.city ?? '—'}</dd>
                          <dt>Groups</dt><dd>{p.groups.map((g) => GROUP_LABELS[g]).join(', ') || '—'}</dd>
                          <dt>Texts OK</dt><dd>{p.sms_opt_in ? 'Yes' : 'No'}</dd>
                          <dt>Club emails</dt><dd>{p.email_opt_out ? 'Unsubscribed' : 'Yes'}</dd>
                          <dt>NRA</dt><dd>{p.nra_active ? `Active${p.nra_expiration_date ? `, expires ${formatDate(p.nra_expiration_date, 'medium')}` : ''}` : 'Expired'}</dd>
                          <dt>Application</dt><dd>{p.open_application_status ? titleCase(p.open_application_status) : 'None open'}</dd>
                          <dt>Online account</dt><dd>{p.has_login ? 'Yes' : 'Not set up'}</dd>
                        </dl>
                        <Link className="btn btn-sm" to={`/members/${p.id}`}>Open full record</Link>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.data && <Pager page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />}

      <Modal open={adding} title="Add a person" onClose={() => setAdding(false)}>
        <AddPerson onDone={() => { setAdding(false); list.reload(); groups.reload(); }} />
      </Modal>
      <Modal open={importing} title="Import from a spreadsheet" onClose={() => setImporting(false)}>
        <ImportPeople onDone={() => { list.reload(); groups.reload(); }} />
      </Modal>
      <Modal open={exporting} title="Download a contact list" onClose={() => setExporting(false)}>
        <ExportPeople groups={groups.data ?? []} />
      </Modal>
    </div>
  );
}

function AddPerson({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', phone: '', membership_status: 'member', renewal_date: '' });
  const save = useAction(async () => {
    await api('/api/board/people', { body: { ...form, phone: form.phone || null, renewal_date: form.renewal_date || null } });
    onDone();
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
      <div className="grid-2">
        <TextField label="First name" required value={form.first_name} onChange={set('first_name')} />
        <TextField label="Last name" required value={form.last_name} onChange={set('last_name')} />
      </div>
      <TextField label="Email" type="email" required value={form.email} onChange={set('email')} />
      <TextField label="Phone" type="tel" value={form.phone} onChange={set('phone')} error={save.fieldErrors.phone} />
      <SelectField label="Status" value={form.membership_status} onChange={set('membership_status')}>
        {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </SelectField>
      <TextField label="Dues paid through (optional)" type="date" value={form.renewal_date} onChange={set('renewal_date')} />
      <button className="btn btn-primary" type="submit" disabled={save.busy}>Add person</button>
    </form>
  );
}

function ImportPeople({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState('member');
  const [result, setResult] = useState<{ created: number; skipped: number; errors: string[] } | null>(null);
  const run = useAction(async () => {
    if (!file) throw new Error('Choose a .csv file first.');
    const csv = await file.text();
    setResult(await api('/api/board/people/import', { body: { csv, membership_status: status } }));
    onDone();
  });
  const template = 'data:text/csv;charset=utf-8,' + encodeURIComponent('first_name,last_name,email,phone,address,city,state,zip\nJane,Doe,jane@example.com,620-555-0100,123 Main St,Great Bend,KS,67530\n');
  return (
    <div className="stack">
      <ol>
        <li><a href={template} download="kiowa-contacts-template.csv">Download the example spreadsheet</a> and fill in one person per row.</li>
        <li>In Excel or Google Sheets, save it as a <strong>CSV</strong> file.</li>
        <li>Choose that file below. People already on the list (same email) are skipped, never changed.</li>
      </ol>
      <FormErrors error={run.error} />
      <div className="field"><label htmlFor="csv-file">Spreadsheet (.csv)</label>
        <input id="csv-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
      <SelectField label="Add them as" value={status} onChange={(e) => setStatus(e.target.value)}>
        {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </SelectField>
      <button type="button" className="btn btn-primary" disabled={run.busy} onClick={() => void run.run()}>{run.busy ? 'Importing…' : 'Import'}</button>
      {result && (
        <Alert kind={result.errors.length ? 'warning' : 'success'}>
          Added {result.created}, skipped {result.skipped} already on the list.
          {result.errors.length > 0 && <ul>{result.errors.map((e) => <li key={e}>{e}</li>)}</ul>}
        </Alert>
      )}
    </div>
  );
}

function ExportPeople({ groups }: { groups: GroupCount[] }) {
  const [format, setFormat] = useState('mailing_list');
  const [selected, setSelected] = useState<string[]>(['active_members']);
  const download = useAction(() => downloadFile('/api/board/exports/contacts.csv', { format, group: selected }));
  return (
    <div className="stack">
      <SelectField label="What kind of list?" value={format} onChange={(e) => setFormat(e.target.value)}>
        <option value="mailing_list">Email list (name and email; skips people who unsubscribed)</option>
        <option value="postal_labels">Mailing labels (name and postal address)</option>
        <option value="full">Full contact details</option>
      </SelectField>
      <fieldset>
        <legend>Who to include</legend>
        <div className="check-grid">
          {groups.map((g) => (
            <Checkbox key={g.key} label={`${g.label} (${g.count})`} checked={selected.includes(g.key)}
              onChange={(e) => setSelected(e.target.checked ? [...selected, g.key] : selected.filter((k) => k !== g.key))} />
          ))}
        </div>
      </fieldset>
      <p className="small muted">This list contains personal information. Downloads are recorded in the activity log.</p>
      <FormErrors error={download.error} />
      <button type="button" className="btn btn-primary" disabled={download.busy || selected.length === 0} onClick={() => void download.run()}>Download CSV</button>
    </div>
  );
}

// ----------------------------------------------------------- detail ----

export function MemberDetail({ id }: { id: number }) {
  usePageTitle('Contact');
  const { can } = useAuth();
  const record = useAsync((signal) => api<PersonRecord>(`/api/board/people/${id}`, { signal }), [id]);
  if (record.loading && !record.data) return <Loading />;
  if (record.error || !record.data) return <ErrorState message={record.error ?? 'Not found'} onRetry={record.reload} />;
  const { person, applications, payments, documents, communications } = record.data;

  return (
    <div className="stack">
      <PageHeader title={`${person.first_name} ${person.last_name}`}
        description={<><StatusBadge status={person.membership_status} label={STATUS_LABELS[person.membership_status]} /> {person.board_role && <span className="badge">Board: {titleCase(person.board_role)}</span>}</>}
        actions={<Link className="btn btn-ghost" to="/members">Back to list</Link>} />
      <div className="detail-grid">
        <EditPerson person={person} editable={can('members.edit')} onSaved={record.reload} />
        <aside className="stack">
          <section className="card stack-sm">
            <h2>Applications</h2>
            {applications.length === 0 ? <p className="muted">None.</p> : applications.map((a) => (
              <p key={a.id}><Link to={`/applications/${a.id}`}>{a.application_type === 'renewal' ? 'Renewal' : 'Waiting list'} · {formatDate(a.submitted_at, 'medium') || 'not sent'}</Link><br />
                <span className="small">{a.status_label} · {a.payment_eligible ? 'Ready to pay dues' : 'Waiting on approval'}</span></p>
            ))}
          </section>
          <section className="card stack-sm">
            <h2>Payments</h2>
            {payments.length === 0 ? <p className="muted">None.</p> : payments.map((p) => (
              <p key={p.id}>{formatMoney(p.amount)} by {p.method} · <StatusBadge status={p.status} /> {formatDateTime(p.paid_at)}
                {p.covers_through && <span className="small muted"> (through {formatDate(p.covers_through, 'medium')})</span>}</p>
            ))}
            {can('payments.manage') && <ManualPayment personId={person.id} onDone={record.reload} />}
          </section>
          <section className="card stack-sm">
            <h2>Documents</h2>
            {documents.length === 0 ? <p className="muted">None.</p> : documents.map((d) => (
              <p key={d.id}>{d.label} <StatusBadge status={d.review_status} /> <span className="small muted">{formatDateTime(d.uploaded_at)}{d.purged && ' · deleted'}</span></p>
            ))}
          </section>
          <section className="card stack-sm">
            <h2>Messages sent</h2>
            {communications.length === 0 ? <p className="muted">None.</p> : communications.map((c, i) => (
              <p key={i} className="small">{c.channel === 'email' ? '✉' : '💬'} {c.subject} · {c.status}{c.opened_at && ', opened'} · {formatDateTime(c.sent_at)}</p>
            ))}
          </section>
        </aside>
      </div>
    </div>
  );
}

function EditPerson({ person, editable, onSaved }: { person: PersonDetail; editable: boolean; onSaved: () => void }) {
  const [form, setForm] = useState({
    first_name: person.first_name, last_name: person.last_name, email: person.email, phone: person.phone ?? '',
    address_line1: person.address_line1 ?? '', address_line2: person.address_line2 ?? '', city: person.city ?? '', state: person.state ?? '',
    zip_code: person.zip_code ?? '', membership_status: person.membership_status, renewal_date: person.renewal_date ?? '',
    nra_number: person.nra_number ?? '', nra_expiration_date: person.nra_expiration_date ?? '', nra_active: person.nra_active,
    background_check_cleared: person.background_check_cleared, on_board: person.on_board, on_shooting_committee: person.on_shooting_committee,
    sms_opt_in: person.sms_opt_in, email_opt_out: person.email_opt_out, notes: person.notes ?? '',
  });
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    setSaved(false);
    const blankToNull = (v: unknown) => (typeof v === 'string' && v.trim() === '' ? null : v);
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, k === 'first_name' || k === 'last_name' || k === 'email' ? v : blankToNull(v)]));
    await api(`/api/board/people/${person.id}`, { method: 'PATCH', body });
    setSaved(true);
    onSaved();
  });
  const text = (k: keyof typeof form) => ({ value: form[k] as string, disabled: !editable, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value }) });
  const flag = (k: keyof typeof form) => ({ checked: form[k] as boolean, disabled: !editable, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.checked }) });

  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <h2>Contact information</h2>
      <FormErrors error={save.error} fieldErrors={save.fieldErrors} />
      {saved && <Alert kind="success">Saved.</Alert>}
      <div className="grid-2">
        <TextField label="First name" required {...text('first_name')} />
        <TextField label="Last name" required {...text('last_name')} />
        <TextField label="Email" type="email" required {...text('email')} hint={person.email_verified ? 'Verified' : 'Not verified'} />
        <TextField label="Phone" type="tel" {...text('phone')} error={save.fieldErrors.phone} />
      </div>
      <TextField label="Street address" {...text('address_line1')} />
      <TextField label="Address line 2" {...text('address_line2')} />
      <div className="grid-3">
        <TextField label="City" {...text('city')} />
        <TextField label="State" maxLength={2} {...text('state')} />
        <TextField label="ZIP" {...text('zip_code')} error={save.fieldErrors.zip_code} />
      </div>

      <h2>Membership</h2>
      <div className="grid-2">
        <SelectField label="Status" value={form.membership_status} disabled={!editable} onChange={(e) => setForm({ ...form, membership_status: e.target.value })}>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SelectField>
        <TextField label="Dues paid through" type="date" {...text('renewal_date')} hint="Set automatically when dues are paid." />
      </div>
      <div className="check-grid">
        <Checkbox label="On the board" {...flag('on_board')} />
        <Checkbox label="On the shooting committee" {...flag('on_shooting_committee')} />
      </div>
      {person.member_since && <p className="small muted">Member since {formatDate(person.member_since, 'medium')}</p>}

      <h2>Approvals</h2>
      <div className="grid-2">
        <TextField label="NRA number" inputMode="numeric" {...text('nra_number')} error={save.fieldErrors.nra_number} />
        <TextField label="NRA expires" type="date" {...text('nra_expiration_date')} />
      </div>
      <div className="check-grid">
        <Checkbox label="NRA membership is current" hint="Turned off automatically when the expiration date passes." {...flag('nra_active')} />
        <Checkbox label="Background check cleared" hint="For new members coming off the waiting list." {...flag('background_check_cleared')} />
      </div>

      <h2>Messages</h2>
      <div className="check-grid">
        <Checkbox label="OK to send text messages" hint={form.sms_opt_in && !person.sms_opt_in ? 'Only check this if the person told you they want texts.' :
          person.sms_opt_in_at ? `Agreed ${formatDateTime(person.sms_opt_in_at)} (${person.sms_opt_in_source ?? 'unknown'})` : undefined} {...flag('sms_opt_in')} />
        <Checkbox label="Unsubscribed from club emails" {...flag('email_opt_out')} />
      </div>
      <TextArea label="Board notes about this person" value={form.notes} disabled={!editable} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      {editable && <div><button className="btn btn-primary" type="submit" disabled={save.busy}>{save.busy ? 'Saving…' : 'Save changes'}</button></div>}
    </form>
  );
}

function ManualPayment({ personId, onDone }: { personId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ amount: '150.00', method: 'check', notes: '' });
  const save = useAction(async () => {
    await api('/api/board/payments/manual', { body: { person_id: personId, ...form } });
    setOpen(false);
    onDone();
  });
  if (!open) return <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>Record a check or cash payment</button>;
  return (
    <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <FormErrors error={save.error} />
      <TextField label="Amount" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
      <SelectField label="Paid by" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
        <option value="check">Check</option><option value="cash">Cash</option><option value="other">Other</option>
      </SelectField>
      <TextField label="Note (e.g. check number)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      <p className="small muted">This marks them as a member and extends their dues to the next renewal date.</p>
      <div className="row"><button className="btn btn-primary btn-sm" type="submit" disabled={save.busy}>Record payment</button>
        <button type="button" className="btn btn-sm" onClick={() => setOpen(false)}>Cancel</button></div>
    </form>
  );
}
