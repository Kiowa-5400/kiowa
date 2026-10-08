import { useState } from 'react';
import { api, API_BASE_URL, type Page } from '@shared/api';
import { formatBytes, formatDateTime } from '@shared/format';
import { Link, usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, TextField, useAction, useAsync } from '@shared/ui';
import { useAuth } from '../auth';
import { PageHeader, Pager, StatusBadge } from '../components/common';

type QueueItem = {
  id: number; label: string; original_filename: string; uploaded_at: string; review_status: string; review_notes: string | null;
  application_id: number | null; person_id: number; person_name: string; application_status: string | null;
};
type PublicDoc = { id: number; title: string; description: string | null; category: string; original_filename: string; size_bytes: number; url: string; is_published: boolean; sort_order: number };

export function DocumentsPage() {
  usePageTitle('Documents');
  const { can } = useAuth();
  const [tab, setTab] = useState<'review' | 'public'>(can('documents.review') ? 'review' : 'public');
  return (
    <div className="stack">
      <PageHeader title="Documents" description="Check the private documents members upload, and manage the forms anyone can download from the website." />
      <div className="tabs" role="tablist">
        {can('documents.review') && <button type="button" role="tab" aria-selected={tab === 'review'} className={`btn ${tab === 'review' ? 'btn-primary' : ''}`} onClick={() => setTab('review')}>Member uploads to check</button>}
        {can('content.edit') && <button type="button" role="tab" aria-selected={tab === 'public'} className={`btn ${tab === 'public' ? 'btn-primary' : ''}`} onClick={() => setTab('public')}>Website downloads</button>}
      </div>
      {tab === 'review' ? <ReviewQueue /> : <PublicDocuments />}
    </div>
  );
}

function ReviewQueue() {
  const [status, setStatus] = useState('pending');
  const [page, setPage] = useState(1);
  const queue = useAsync((signal) => api<Page<QueueItem>>('/api/board/documents', { signal, query: { review_status: status, page } }), [status, page]);
  const review = useAction(async (id: number, review_status: string) => {
    const notes = review_status === 'rejected' ? window.prompt('Tell the member why (optional):') : '';
    if (notes === null) return; // Cancelled.
    await api(`/api/board/documents/${id}/review`, { body: { review_status, notes } });
    queue.reload();
  });
  return (
    <section className="stack" aria-label="Member uploads">
      <p className="small muted">These are private (NRA cards, background checks, licenses). Opening one is recorded in the activity log.</p>
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="doc-status">Show</label>
        <select id="doc-status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="pending">Waiting to be checked</option><option value="approved">Accepted</option><option value="rejected">Not accepted</option>
        </select>
      </div>
      <FormErrors error={review.error} />
      {queue.loading && <Loading />}
      {queue.error && <ErrorState message={queue.error} onRetry={queue.reload} />}
      {queue.data && queue.data.items.length === 0 && <Empty>Nothing waiting to be checked.</Empty>}
      {queue.data && queue.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Member</th><th>Document</th><th>Uploaded</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {queue.data.items.map((d) => (
                <tr key={d.id}>
                  <td data-label="Member"><Link to={`/members/${d.person_id}`}>{d.person_name}</Link>
                    {d.application_id && <div className="small"><Link to={`/applications/${d.application_id}`}>Open application</Link></div>}</td>
                  <td data-label="Document">{d.label}<div className="small muted">{d.original_filename}</div></td>
                  <td data-label="Uploaded">{formatDateTime(d.uploaded_at)}</td>
                  <td data-label="Status"><StatusBadge status={d.review_status} label={d.review_status === 'pending' ? 'to check' : d.review_status} /></td>
                  <td data-label="">
                    <span className="row">
                      <a className="btn btn-sm" href={`${API_BASE_URL}/api/board/documents/${d.id}/file`} target="_blank" rel="noopener">Open</a>
                      {d.review_status !== 'approved' && <button type="button" className="btn btn-sm" onClick={() => void review.run(d.id, 'approved')}>Looks good</button>}
                      {d.review_status !== 'rejected' && <button type="button" className="btn btn-sm btn-danger" onClick={() => void review.run(d.id, 'rejected')}>Not acceptable</button>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {queue.data && <Pager page={page} pageSize={queue.data.page_size} total={queue.data.total} onPage={setPage} />}
    </section>
  );
}

function PublicDocuments() {
  const docs = useAsync((signal) => api<PublicDoc[]>('/api/board/public-documents', { signal }), []);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const create = useAction(async () => {
    if (!file) throw new Error('Choose a PDF or picture to upload.');
    const body = new FormData();
    body.append('title', title);
    body.append('description', description);
    body.append('category', 'membership');
    body.append('file', file);
    await api('/api/board/public-documents', { body });
    setTitle(''); setDescription(''); setFile(null); setMessage('Uploaded. It now appears on the Membership page.');
    docs.reload();
  });
  const update = useAction(async (doc: PublicDoc, changes: Partial<PublicDoc>) => {
    await api(`/api/board/public-documents/${doc.id}`, { method: 'PATCH', body: { title: doc.title, description: doc.description, category: doc.category, is_published: doc.is_published, sort_order: doc.sort_order, ...changes } });
    docs.reload();
  });
  const remove = useAction(async (doc: PublicDoc) => {
    if (!window.confirm(`Delete “${doc.title}”?`)) return;
    await api(`/api/board/public-documents/${doc.id}`, { method: 'DELETE' });
    docs.reload();
  });
  return (
    <section className="stack" aria-label="Website downloads">
      {message && <Alert kind="success">{message}</Alert>}
      <FormErrors error={update.error ?? remove.error} />
      {docs.loading && <Loading />}
      {docs.data && docs.data.length === 0 && <Empty>No downloads posted.</Empty>}
      {docs.data?.map((doc) => (
        <div key={doc.id} className="card doc-row">
          <div>
            <strong>{doc.title}</strong> <span className="small muted">({formatBytes(doc.size_bytes)})</span>
            {doc.description && <div className="small muted">{doc.description}</div>}
          </div>
          <span className="row">
            <a className="btn btn-sm" href={doc.url} target="_blank" rel="noopener">View</a>
            <Checkbox label="Show on website" checked={doc.is_published} onChange={(e) => void update.run(doc, { is_published: e.target.checked })} />
            <button type="button" className="btn btn-sm btn-danger" onClick={() => void remove.run(doc)}>Delete</button>
          </span>
        </div>
      ))}
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void create.run(); }}>
        <h2>Post a new download</h2>
        <FormErrors error={create.error} />
        <TextField label="Title" required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="2027 Range Rules and Membership Agreement" />
        <TextField label="Short description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="field"><label htmlFor="pub-file">File (PDF or picture)</label>
          <input id="pub-file" type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
        <div><button className="btn btn-primary" type="submit" disabled={create.busy}>Upload</button></div>
      </form>
    </section>
  );
}
