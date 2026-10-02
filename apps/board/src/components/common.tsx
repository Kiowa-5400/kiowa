import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, errorMessage } from '@shared/api';

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return <p className="small muted">{total} total</p>;
  return (
    <nav className="row" aria-label="Pages">
      <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <span className="small">Page {page} of {pages} ({total} total)</span>
      <button type="button" className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </nav>
  );
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

const STATUS_STYLE: Record<string, string> = {
  submitted: 'badge-warning', needs_info: 'badge-info', approved: 'badge-success', completed: 'badge-success',
  declined: 'badge-danger', withdrawn: '', draft: '',
  pending: 'badge-warning', paid: 'badge-success', failed: 'badge-danger', cancelled: '', refunded: 'badge-info', partially_refunded: 'badge-info',
  member: 'badge-success', waiting_list: 'badge-warning', non_member: '', expired: 'badge-danger', terminated: 'badge-danger',
  rejected: 'badge-danger', sent: '', delivered: 'badge-success', bounced: 'badge-danger', complained: 'badge-danger',
  queued: '', undelivered: 'badge-danger',
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`badge ${STATUS_STYLE[status] ?? ''}`}>{label ?? status.replace(/_/g, ' ')}</span>;
}

/** Simple rich-text editor for board-written content. The API sanitizes everything it receives. */
export function RichTextEditor({ label, value, onChange, id }: { label: string; value: string; onChange: (html: string) => void; id: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) ref.current.innerHTML = value;
  }, [value]);

  const exec = (command: string, arg?: string) => {
    ref.current?.focus();
    document.execCommand(command, false, arg);
    onChange(ref.current?.innerHTML ?? '');
  };

  const addLink = () => {
    const url = window.prompt('Link address (starting with https://)', 'https://');
    if (url && /^(https?:|mailto:|tel:)/i.test(url)) exec('createLink', url);
  };

  const addImage = async (file: File) => {
    setError(null);
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const result = await api<{ url: string }>('/api/board/media', { body });
      exec('insertImage', result.url);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="field">
      <span className="field-label" id={`${id}-label`}>{label}</span>
      <div className="editor-toolbar" role="toolbar" aria-label={`${label} formatting`}>
        <button type="button" className="btn btn-sm" onClick={() => exec('bold')} aria-label="Bold"><strong>B</strong></button>
        <button type="button" className="btn btn-sm" onClick={() => exec('italic')} aria-label="Italic"><em>I</em></button>
        <button type="button" className="btn btn-sm" onClick={() => exec('formatBlock', 'h3')}>Heading</button>
        <button type="button" className="btn btn-sm" onClick={() => exec('formatBlock', 'p')}>Paragraph</button>
        <button type="button" className="btn btn-sm" onClick={() => exec('insertUnorderedList')}>• List</button>
        <button type="button" className="btn btn-sm" onClick={() => exec('insertOrderedList')}>1. List</button>
        <button type="button" className="btn btn-sm" onClick={addLink}>Link</button>
        <label className="btn btn-sm">
          {uploading ? 'Uploading…' : 'Picture'}
          <input type="file" accept="image/*" className="visually-hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void addImage(f); e.target.value = ''; }} />
        </label>
      </div>
      <div
        ref={ref}
        id={id}
        className="editor prose"
        contentEditable
        role="textbox"
        aria-multiline="true"
        aria-labelledby={`${id}-label`}
        tabIndex={0}
        onInput={() => onChange(ref.current?.innerHTML ?? '')}
        suppressContentEditableWarning
      />
      {error && <span className="error">{error}</span>}
    </div>
  );
}

/** Group + individual recipient picker shared by the email and SMS screens. */
export type GroupCount = { key: string; label: string; count: number };

export function GroupPicker({ groups, selected, onChange }: { groups: GroupCount[]; selected: string[]; onChange: (keys: string[]) => void }) {
  return (
    <fieldset>
      <legend>Send to these groups</legend>
      <div className="check-grid">
        {groups.map((group) => (
          <label key={group.key} className="check">
            <input type="checkbox" checked={selected.includes(group.key)}
              onChange={(e) => onChange(e.target.checked ? [...selected, group.key] : selected.filter((k) => k !== group.key))} />
            <span>{group.label} <span className="muted small">({group.count})</span></span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function PersonSearch({ selected, onChange }: { selected: { id: number; name: string }[]; onChange: (people: { id: number; name: string }[]) => void }) {
  const [q, setQ] = useState('');
  const debounced = useDebounced(q);
  const [results, setResults] = useState<{ id: number; first_name: string; last_name: string; email: string }[]>([]);
  useEffect(() => {
    if (debounced.trim().length < 2) {
      setResults([]);
      return;
    }
    api<{ items: { id: number; first_name: string; last_name: string; email: string }[] }>('/api/board/people', { query: { q: debounced, page_size: 8 } })
      .then((r) => setResults(r.items))
      .catch(() => setResults([]));
  }, [debounced]);
  return (
    <div className="field">
      <label htmlFor="person-search">Add individual people</label>
      <input id="person-search" type="search" placeholder="Type a name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      {results.length > 0 && (
        <ul className="search-results">
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" className="btn btn-ghost btn-sm" disabled={selected.some((s) => s.id === p.id)}
                onClick={() => { onChange([...selected, { id: p.id, name: `${p.first_name} ${p.last_name}` }]); setQ(''); }}>
                + {p.first_name} {p.last_name} <span className="muted small">{p.email}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected.length > 0 && (
        <p className="row">
          {selected.map((p) => (
            <span key={p.id} className="badge">
              {p.name}
              <button type="button" className="chip-remove" aria-label={`Remove ${p.name}`} onClick={() => onChange(selected.filter((s) => s.id !== p.id))}>✕</button>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
