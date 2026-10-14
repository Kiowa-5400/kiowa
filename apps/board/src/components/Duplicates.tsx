import { useEffect, useState } from 'react';
import { api } from '@shared/api';
import { formatDate, STATUS_LABELS } from '@shared/format';
import { Alert, ErrorState, FormErrors, Loading, Modal, useAction, useAsync } from '@shared/ui';
import { StatusBadge, useDebounced } from './common';

// Two records for the same person usually happen when a member the club had no email for
// signs up on the website: the site can't tell it's them, so it starts a new record.

export type PersonCard = {
  id: number; first_name: string; last_name: string; email: string | null; phone: string | null; address: string | null;
  membership_status: string; renewal_date: string | null; member_number: number | null; nra_number: string | null; has_login: boolean;
};

type Preview = { keep: PersonCard; other: PersonCard; combined: PersonCard; notes: string[]; problem: string | null };

const fullName = (p: PersonCard) => `${p.first_name} ${p.last_name}`;

function Details({ person, title, highlight = false }: { person: PersonCard; title: string; highlight?: boolean }) {
  return (
    <section className={`card stack-sm ${highlight ? '' : 'card-muted'}`}>
      <h3>{title}</h3>
      <p><strong>{fullName(person)}</strong> <StatusBadge status={person.membership_status} label={STATUS_LABELS[person.membership_status]} /></p>
      <dl className="kv">
        <dt>Email</dt><dd>{person.email ?? <span className="muted">None</span>}</dd>
        <dt>Phone</dt><dd>{person.phone ?? <span className="muted">None</span>}</dd>
        <dt>Address</dt><dd>{person.address ?? <span className="muted">None</span>}</dd>
        <dt>Paid through</dt><dd>{formatDate(person.renewal_date, 'medium') || <span className="muted">—</span>}</dd>
        {person.member_number !== null && <><dt>Member no.</dt><dd>{person.member_number}</dd></>}
        <dt>Website login</dt><dd>{person.has_login ? 'Yes' : 'Not set up'}</dd>
      </dl>
    </section>
  );
}

/** Shows both records and what they'd look like combined, then lets the board decide. */
export function CombineDialog({ personId, otherId, onClose, onDone }: {
  personId: number; otherId: number | null; onClose: () => void; onDone: (keptId: number | null) => void;
}) {
  return (
    <Modal open={otherId !== null} title="Is this the same person?" onClose={onClose}>
      {otherId !== null && <CombineBody personId={personId} otherId={otherId} onClose={onClose} onDone={onDone} />}
    </Modal>
  );
}

function CombineBody({ personId, otherId, onClose, onDone }: { personId: number; otherId: number; onClose: () => void; onDone: (keptId: number | null) => void }) {
  const preview = useAsync((signal) => api<Preview>(`/api/board/people/${personId}/combine/${otherId}`, { signal }), [personId, otherId]);
  const combine = useAction(async () => {
    const result = await api<{ person_id: number }>(`/api/board/people/${personId}/combine/${otherId}`, { method: 'POST' });
    onDone(result.person_id);
  });
  const different = useAction(async () => {
    await api(`/api/board/people/${personId}/not-duplicate/${otherId}`, { method: 'POST' });
    onDone(null);
  });
  if (preview.loading) return <Loading />;
  if (preview.error || !preview.data) return <ErrorState message={preview.error ?? 'Something went wrong.'} onRetry={preview.reload} />;
  const { keep, other, combined, notes, problem } = preview.data;
  const busy = combine.busy || different.busy;

  return (
    <div className="stack">
      <p>The club has two records that look like the same person. Compare them below.</p>
      <div className="grid-2">
        <Details person={keep} title="Record 1" />
        <Details person={other} title="Record 2" />
      </div>

      {problem ? <Alert kind="warning" title="These can't be combined yet.">{problem}</Alert> : (
        <>
          <Details person={combined} title="If you combine them, they'll have one record:" highlight />
          <ul className="small">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
      <FormErrors error={combine.error ?? different.error} />
      <div className="row">
        {!problem && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void combine.run()}>
          {combine.busy ? 'Combining…' : 'Yes, same person: combine them'}</button>}
        <button type="button" className="btn" disabled={busy} onClick={() => void different.run()}>No, these are different people</button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>Decide later</button>
      </div>
      {!problem && <p className="small muted">Combining can't be undone, but nothing is lost: payments, documents and history all move to the one record.</p>}
    </div>
  );
}

/** Members page: a heads-up listing every pair that may be the same person. */
export function DuplicatesNotice({ canEdit, onChanged }: { canEdit: boolean; onChanged: () => void }) {
  const pairs = useAsync((signal) => api<{ keep: PersonCard; other: PersonCard }[]>('/api/board/people/duplicates', { signal }), []);
  const [reviewing, setReviewing] = useState<{ keep: PersonCard; other: PersonCard } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const count = pairs.data?.length ?? 0;
  if (count === 0) return message ? <Alert kind="success">{message}</Alert> : null;

  return (
    <>
      {message && <Alert kind="success">{message}</Alert>}
      <Alert kind="warning" title={count === 1 ? '1 person may be listed twice.' : `${count} people may be listed twice.`}>
        <p className="small">This usually happens when a member signs up on the website with an email the club didn't have. These records share a last name and phone number.</p>
        <ul className="stack-sm" style={{ listStyle: 'none', padding: 0 }}>
          {pairs.data!.map((pair) => (
            <li key={`${pair.keep.id}-${pair.other.id}`} className="row">
              <span><strong>{fullName(pair.keep)}</strong> ({STATUS_LABELS[pair.keep.membership_status]}) and <strong>{fullName(pair.other)}</strong> ({STATUS_LABELS[pair.other.membership_status]})</span>
              {canEdit && <button type="button" className="btn btn-sm" onClick={() => { setMessage(null); setReviewing(pair); }}>Review</button>}
            </li>
          ))}
        </ul>
      </Alert>
      <CombineDialog personId={reviewing?.keep.id ?? 0} otherId={reviewing?.other.id ?? null} onClose={() => setReviewing(null)}
        onDone={(kept) => {
          setMessage(kept ? `Done. ${fullName(reviewing!.keep)} now has one record.` : 'Got it. They won\'t be flagged again.');
          setReviewing(null);
          pairs.reload();
          onChanged();
        }} />
    </>
  );
}

/** A person's page: flags likely matches, and lets the board pick one by hand when the site didn't spot it. */
export function PersonDuplicates({ personId, canEdit, onCombined }: { personId: number; canEdit: boolean; onCombined: (keptId: number) => void }) {
  const matches = useAsync((signal) => api<PersonCard[]>(`/api/board/people/${personId}/matches`, { signal }), [personId]);
  const [reviewing, setReviewing] = useState<number | null>(null);
  const [searching, setSearching] = useState(false);
  if (!canEdit) return null;
  const done = (kept: number | null) => {
    setReviewing(null);
    setSearching(false);
    if (kept) onCombined(kept);
    else matches.reload();
  };

  return (
    <>
      {matches.data?.map((m) => (
        <Alert key={m.id} kind="warning" title="This may be the same person as another record.">
          <span className="row">
            <span>{fullName(m)} ({STATUS_LABELS[m.membership_status]}) has the same last name and phone number.</span>
            <button type="button" className="btn btn-sm" onClick={() => setReviewing(m.id)}>Review</button>
          </span>
        </Alert>
      ))}
      <section className="card stack-sm">
        <h2>Listed twice?</h2>
        {searching ? <FindPerson excludeId={personId} onPick={setReviewing} onCancel={() => setSearching(false)} /> : <>
          <p className="small muted">If this person has a second record, you can combine the two.</p>
          <div><button type="button" className="btn btn-sm" onClick={() => setSearching(true)}>Find their other record</button></div>
        </>}
      </section>
      <CombineDialog personId={personId} otherId={reviewing} onClose={() => setReviewing(null)} onDone={done} />
    </>
  );
}

function FindPerson({ excludeId, onPick, onCancel }: { excludeId: number; onPick: (id: number) => void; onCancel: () => void }) {
  const [q, setQ] = useState('');
  const search = useDebounced(q);
  const [results, setResults] = useState<PersonCard[]>([]);
  useEffect(() => {
    if (search.trim().length < 2) {
      setResults([]);
      return;
    }
    api<{ items: PersonCard[] }>('/api/board/people', { query: { q: search, page_size: 8 } })
      .then((r) => setResults(r.items.filter((p) => p.id !== excludeId)))
      .catch(() => setResults([]));
  }, [search, excludeId]);
  return (
    <div className="stack-sm">
      <div className="field"><label htmlFor="dup-search">Search by name, email or phone</label>
        <input id="dup-search" type="search" autoFocus value={q} onChange={(e) => setQ(e.target.value)} /></div>
      {results.length > 0 && (
        <ul className="search-results">
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onPick(p.id)}>
                {fullName(p)} <span className="muted small">{STATUS_LABELS[p.membership_status]}{p.email ? ` · ${p.email}` : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {search.trim().length >= 2 && results.length === 0 && <p className="small muted">No one else matches.</p>}
      <div><button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button></div>
    </div>
  );
}
