import { useState } from 'react';
import { api } from '@shared/api';
import { formatClock, formatDate } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, Empty, ErrorState, FormErrors, Loading, Modal, TextArea, TextField, useAction, useAsync } from '@shared/ui';
import { PageHeader } from '../components/common';

type Photo = { id: number; url: string; caption: string | null; sort_order: number };
type Match = { id: number; discipline: string; event_date: string; start_time: string | null; notes: string | null; results_url: string | null; sort_order: number; photos: Photo[] };

export function MatchesPage() {
  usePageTitle('Matches');
  const matches = useAsync((signal) => api<Match[]>('/api/board/matches', { signal }), []);
  const [editing, setEditing] = useState<Match | 'new' | null>(null);
  const [photos, setPhotos] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const move = useAction(async (index: number, delta: number) => {
    const ids = matches.data!.map((m) => m.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    await api('/api/board/matches/reorder', { body: { ids } });
    matches.reload();
  });
  const disciplines = [...new Set(matches.data?.map((m) => m.discipline) ?? ['Defensive Pistol'])];

  return (
    <div className="stack">
      <PageHeader title="Matches" description="The public Matches page groups these by discipline. Add a PractiScore link once results are posted."
        actions={<button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>Add a match</button>} />
      {message && <Alert kind="success">{message}</Alert>}
      <FormErrors error={move.error} />
      {matches.loading && <Loading />}
      {matches.error && <ErrorState message={matches.error} onRetry={matches.reload} />}
      {matches.data && matches.data.length === 0 && <Empty>No matches yet.</Empty>}
      {matches.data && matches.data.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Order</th><th>Date</th><th>Discipline</th><th>Results</th><th>Photos</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {matches.data.map((m, i) => (
                <tr key={m.id}>
                  <td data-label="Order">
                    <button type="button" className="btn btn-sm" disabled={i === 0 || move.busy} onClick={() => void move.run(i, -1)} aria-label={`Move ${formatDate(m.event_date, 'medium')} up`}>↑</button>
                    <button type="button" className="btn btn-sm" disabled={i === matches.data!.length - 1 || move.busy} onClick={() => void move.run(i, 1)} aria-label={`Move ${formatDate(m.event_date, 'medium')} down`}>↓</button>
                  </td>
                  <td data-label="Date">{formatDate(m.event_date, 'medium')}<div className="small muted">{formatClock(m.start_time)}</div></td>
                  <td data-label="Discipline">{m.discipline}{m.notes && <div className="small muted">{m.notes}</div>}</td>
                  <td data-label="Results">{m.results_url ? <a href={m.results_url} target="_blank" rel="noopener noreferrer">View</a> : <span className="muted">Not added</span>}</td>
                  <td data-label="Photos"><button type="button" className="btn btn-sm" onClick={() => setPhotos(m.id)}>{m.photos.length} photo{m.photos.length === 1 ? '' : 's'}</button></td>
                  <td data-label=""><button type="button" className="btn btn-sm" onClick={() => setEditing(m)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <datalist id="disciplines">{disciplines.map((d) => <option key={d} value={d} />)}</datalist>
      <Modal open={editing !== null} title={editing === 'new' ? 'Add a match' : 'Edit match'} onClose={() => setEditing(null)}>
        {editing && <MatchForm match={editing === 'new' ? null : editing} onDone={(text) => { setMessage(text); setEditing(null); matches.reload(); }} />}
      </Modal>
      <Modal open={photos !== null} title="Match photos" onClose={() => { setPhotos(null); matches.reload(); }}>
        {photos !== null && <PhotoManager match={matches.data!.find((m) => m.id === photos)!} onChange={matches.reload} />}
      </Modal>
    </div>
  );
}

function MatchForm({ match, onDone }: { match: Match | null; onDone: (message: string) => void }) {
  const [form, setForm] = useState({
    discipline: match?.discipline ?? 'Defensive Pistol', event_date: match?.event_date ?? '', start_time: match?.start_time ?? '09:00',
    notes: match?.notes ?? '', results_url: match?.results_url ?? '',
  });
  const save = useAction(async () => {
    const body = { ...form, start_time: form.start_time || null, notes: form.notes || null, results_url: form.results_url || null };
    if (match) await api(`/api/board/matches/${match.id}`, { method: 'PATCH', body });
    else await api('/api/board/matches', { body });
    onDone(match ? 'Match updated.' : 'Match added.');
  });
  const remove = useAction(async () => {
    if (!window.confirm('Delete this match and its photos?')) return;
    await api(`/api/board/matches/${match!.id}`, { method: 'DELETE' });
    onDone('Match deleted.');
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <FormErrors error={save.error ?? remove.error} />
      <TextField label="Discipline" required list="disciplines" value={form.discipline} onChange={set('discipline')} hint="Type a new one to add a discipline." />
      <div className="grid-2">
        <TextField label="Date" type="date" required value={form.event_date} onChange={set('event_date')} />
        <TextField label="Start time" type="time" value={form.start_time} onChange={set('start_time')} />
      </div>
      <TextArea label="Notes (optional)" value={form.notes} onChange={set('notes')} />
      <TextField label="PractiScore results link (optional)" type="url" placeholder="https://practiscore.com/results/…" value={form.results_url} onChange={set('results_url')} />
      <div className="row-between">
        <button className="btn btn-primary" type="submit" disabled={save.busy}>Save match</button>
        {match && <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove.run()}>Delete match</button>}
      </div>
    </form>
  );
}

function PhotoManager({ match, onChange }: { match: Match; onChange: () => void }) {
  const [photos, setPhotos] = useState(match.photos);
  const upload = useAction(async (files: FileList) => {
    const body = new FormData();
    Array.from(files).forEach((f) => body.append('files', f));
    setPhotos((await api<Match>(`/api/board/matches/${match.id}/photos`, { body })).photos);
    onChange();
  });
  const act = useAction(async (kind: 'remove' | 'caption' | 'move', photo: Photo, extra?: number | string) => {
    if (kind === 'remove') {
      if (!window.confirm('Remove this photo?')) return;
      await api(`/api/board/match-photos/${photo.id}`, { method: 'DELETE' });
      setPhotos(photos.filter((p) => p.id !== photo.id));
    } else if (kind === 'caption') {
      await api(`/api/board/match-photos/${photo.id}`, { method: 'PATCH', body: { caption: extra } });
    } else {
      const ids = photos.map((p) => p.id);
      const index = ids.indexOf(photo.id);
      ids.splice(index, 1);
      ids.splice(index + Number(extra), 0, photo.id);
      setPhotos((await api<Match>(`/api/board/matches/${match.id}/photos/reorder`, { body: { ids } })).photos);
    }
  });
  return (
    <div className="stack">
      <p>{match.discipline} · {formatDate(match.event_date, 'medium')}</p>
      <FormErrors error={upload.error ?? act.error} />
      <div className="field">
        <label htmlFor="photo-upload">Add photos (JPG, PNG or WEBP, up to 8 MB each)</label>
        <input id="photo-upload" type="file" accept="image/*" multiple disabled={upload.busy} onChange={(e) => { if (e.target.files?.length) void upload.run(e.target.files); e.target.value = ''; }} />
        {upload.busy && <span role="status">Uploading…</span>}
      </div>
      {photos.length === 0 ? <p className="muted">No photos yet.</p> : (
        <ul className="photo-grid">
          {photos.map((p, i) => (
            <li key={p.id}>
              <img src={p.url} alt={p.caption ?? ''} />
              <input aria-label="Caption" defaultValue={p.caption ?? ''} placeholder="Caption" onBlur={(e) => { if (e.target.value !== (p.caption ?? '')) void act.run('caption', p, e.target.value); }} />
              <div className="row">
                <button type="button" className="btn btn-sm" disabled={i === 0} onClick={() => void act.run('move', p, -1)} aria-label="Move earlier">←</button>
                <button type="button" className="btn btn-sm" disabled={i === photos.length - 1} onClick={() => void act.run('move', p, 1)} aria-label="Move later">→</button>
                <button type="button" className="btn btn-sm btn-danger" onClick={() => void act.run('remove', p)}>Remove</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
