import { useState } from 'react';
import { api, type Page } from '@shared/api';
import { formatDateTime } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Empty, ErrorState, Loading, useAsync } from '@shared/ui';
import { PageHeader, Pager, useDebounced } from '../components/common';

type Entry = { id: number; created_at: string; actor_label: string; action: string; entity_type: string | null; entity_id: string | null; summary: string | null; details: Record<string, unknown> | null; ip_address: string | null };

const AREAS = [
  ['', 'Everything'], ['application.', 'Applications'], ['document.', 'Documents'], ['person.', 'Contacts'], ['member.', 'Membership changes'],
  ['payment.', 'Payments'], ['communication.', 'Email & texts'], ['export.', 'Downloads of contact lists'], ['cms.', 'Website edits'],
  ['calendar.', 'Calendar'], ['match.', 'Matches'], ['settings.', 'Settings'], ['board', 'Board users & sign-ins'], ['account.', 'Member accounts'],
];

export function AuditLogPage() {
  usePageTitle('Activity log');
  const [action, setAction] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const search = useDebounced(q);
  const log = useAsync((signal) => api<Page<Entry>>('/api/board/audit', { signal, query: { action, q: search, page } }), [action, search, page]);
  return (
    <div className="stack">
      <PageHeader title="Activity log" description="A permanent record of important changes: who did what, and when." />
      <div className="filters">
        <div className="field"><label htmlFor="a-area">Show</label>
          <select id="a-area" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>{AREAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        <div className="field"><label htmlFor="a-q">Search</label><input id="a-q" type="search" placeholder="Person or description" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
      </div>
      {log.loading && <Loading />}
      {log.error && <ErrorState message={log.error} onRetry={log.reload} />}
      {log.data && log.data.items.length === 0 && <Empty>Nothing recorded.</Empty>}
      {log.data && log.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
            <tbody>
              {log.data.items.map((e) => (
                <tr key={e.id}>
                  <td data-label="When">{formatDateTime(e.created_at)}</td>
                  <td data-label="Who">{e.actor_label}</td>
                  <td data-label="What">{e.summary ?? e.action.replace(/[._]/g, ' ')}<div className="small muted">{e.action}{e.entity_id && ` #${e.entity_id}`}</div></td>
                  <td data-label="Details" className="small">{e.details ? <code>{JSON.stringify(e.details)}</code> : '—'}{e.ip_address && <div className="muted">{e.ip_address}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {log.data && <Pager page={page} pageSize={log.data.page_size} total={log.data.total} onPage={setPage} />}
    </div>
  );
}
