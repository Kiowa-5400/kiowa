import { useState } from 'react';
import { api } from '@shared/api';
import { CATEGORY_LABELS, clubToday, formatClock, formatDate } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Alert, Checkbox, Empty, ErrorState, FormErrors, Loading, Modal, SelectField, TextField, useAction, useAsync } from '@shared/ui';
import { PageHeader, RichTextEditor } from '../components/common';

type CalendarEvent = {
  id: number; title: string; local_date: string; local_time: string | null; local_end_time: string | null; all_day: boolean;
  category: string; description_html: string | null; link_url: string | null; link_label: string | null;
  image_url: string | null; document_url: string | null; document_filename: string | null; series_id: string | null; recurrence_label: string | null;
};

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const ORDINALS = [[1, '1st'], [2, '2nd'], [3, '3rd'], [4, '4th'], [5, 'Last']] as const;

function addMonths(isoMonth: string, delta: number): string {
  const [y, m] = isoMonth.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

export function CalendarPage() {
  usePageTitle('Calendar');
  const [month, setMonth] = useState(clubToday().slice(0, 7));
  const [editing, setEditing] = useState<CalendarEvent | 'new' | null>(null);
  const [series, setSeries] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const end = addMonths(month, 3);
  const events = useAsync((signal) => api<CalendarEvent[]>('/api/board/calendar', { signal, query: { start: `${month}-01`, end: `${end}-01` } }), [month]);
  const done = (text: string) => { setMessage(text); setEditing(null); setSeries(false); events.reload(); };

  return (
    <div className="stack">
      <PageHeader title="Calendar" description="Events here appear on the public calendar right away. Times are Kansas time."
        actions={<><button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>Add an event</button>
          <button type="button" className="btn" onClick={() => setSeries(true)}>Add a repeating event</button></>} />
      {message && <Alert kind="success">{message}</Alert>}
      <div className="row">
        <button type="button" className="btn btn-sm" onClick={() => setMonth(addMonths(month, -1))}>← Earlier</button>
        <strong>{formatDate(`${month}-01`, 'medium').replace(/ \d+,/, '')} – {formatDate(`${addMonths(month, 2)}-01`, 'medium').replace(/ \d+,/, '')}</strong>
        <button type="button" className="btn btn-sm" onClick={() => setMonth(addMonths(month, 1))}>Later →</button>
      </div>
      {events.loading && <Loading />}
      {events.error && <ErrorState message={events.error} onRetry={events.reload} />}
      {events.data && events.data.length === 0 && <Empty>No events in these months.</Empty>}
      {events.data && events.data.length > 0 && (
        <div className="table-wrap">
          <table className="table-stack">
            <thead><tr><th>Date</th><th>Time</th><th>Event</th><th>Type</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {events.data.map((e) => (
                <tr key={e.id}>
                  <td data-label="Date">{formatDate(e.local_date, 'long')}</td>
                  <td data-label="Time">{e.all_day ? 'All day' : `${formatClock(e.local_time)}${e.local_end_time ? ` – ${formatClock(e.local_end_time)}` : ''}`}</td>
                  <td data-label="Event">{e.title}{e.recurrence_label && <div className="small muted">↻ {e.recurrence_label}</div>}</td>
                  <td data-label="Type"><span className={`row cat-${e.category}`}><span className="cat-dot" aria-hidden="true" /> {CATEGORY_LABELS[e.category]}</span></td>
                  <td data-label=""><button type="button" className="btn btn-sm" onClick={() => setEditing(e)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={editing !== null} title={editing === 'new' ? 'Add an event' : 'Edit event'} onClose={() => setEditing(null)}>
        {editing && <EventForm event={editing === 'new' ? null : editing} onDone={done} />}
      </Modal>
      <Modal open={series} title="Add a repeating event" onClose={() => setSeries(false)}>
        {series && <SeriesForm onDone={done} />}
      </Modal>
    </div>
  );
}

function EventForm({ event, onDone }: { event: CalendarEvent | null; onDone: (message: string) => void }) {
  const [form, setForm] = useState({
    title: event?.title ?? '', event_date: event?.local_date ?? clubToday(), start_time: event?.local_time ?? '13:00',
    end_time: event?.local_end_time ?? '', all_day: event?.all_day ?? false, category: event?.category ?? 'event',
    description_html: event?.description_html ?? '', link_url: event?.link_url ?? '', link_label: event?.link_label ?? '',
  });
  const [image, setImage] = useState<File | null>(null);
  const [document, setDocument] = useState<File | null>(null);
  const [removeImage, setRemoveImage] = useState(false);
  const [removeDocument, setRemoveDocument] = useState(false);
  const save = useAction(async () => {
    const body = new FormData();
    Object.entries(form).forEach(([k, v]) => body.append(k, String(v)));
    if (image) body.append('image', image);
    if (document) body.append('document', document);
    if (event) {
      body.append('remove_image', String(removeImage));
      body.append('remove_document', String(removeDocument));
      await api(`/api/board/calendar/${event.id}`, { method: 'PATCH', body });
    } else {
      await api('/api/board/calendar', { body });
    }
    onDone(event ? 'Event updated.' : 'Event added.');
  });
  const remove = useAction(async (scope?: 'future' | 'all') => {
    if (scope && event?.series_id) {
      if (!window.confirm(scope === 'all' ? 'Delete every event in this series?' : 'Delete this and all future events in this series?')) return;
      await api(`/api/board/calendar/series/${event.series_id}`, { method: 'DELETE', query: { scope } });
    } else {
      if (!window.confirm('Delete this event?')) return;
      await api(`/api/board/calendar/${event!.id}`, { method: 'DELETE' });
    }
    onDone('Deleted.');
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <FormErrors error={save.error ?? remove.error} />
      {event?.recurrence_label && <Alert kind="info">Part of a repeating event ({event.recurrence_label}). Changes here only affect this date.</Alert>}
      <TextField label="Title" required value={form.title} onChange={set('title')} />
      <div className="grid-3">
        <TextField label="Date" type="date" required value={form.event_date} onChange={set('event_date')} />
        {!form.all_day && <TextField label="Starts" type="time" required value={form.start_time} onChange={set('start_time')} />}
        {!form.all_day && <TextField label="Ends (optional)" type="time" value={form.end_time} onChange={set('end_time')} />}
      </div>
      <Checkbox label="All-day event" checked={form.all_day} onChange={(e) => setForm({ ...form, all_day: e.target.checked })} />
      <SelectField label="Type (sets the color)" value={form.category} onChange={set('category')}>
        {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </SelectField>
      <RichTextEditor id="event-description" label="Description (optional)" value={form.description_html} onChange={(html) => setForm({ ...form, description_html: html })} />
      <div className="grid-2">
        <TextField label="Link (optional)" type="url" placeholder="https://" value={form.link_url} onChange={set('link_url')} />
        <TextField label="Link button text" placeholder="Sign up" value={form.link_label} onChange={set('link_label')} />
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="ev-image">Picture (optional)</label>
          {event?.image_url && !removeImage && <img src={event.image_url} alt="" className="thumb" />}
          <input id="ev-image" type="file" accept="image/*" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
          {event?.image_url && <Checkbox label="Remove the picture" checked={removeImage} onChange={(e) => setRemoveImage(e.target.checked)} />}
        </div>
        <div className="field">
          <label htmlFor="ev-doc">Flyer or form, PDF (optional)</label>
          {event?.document_url && !removeDocument && <a href={event.document_url} target="_blank" rel="noopener">{event.document_filename}</a>}
          <input id="ev-doc" type="file" accept="application/pdf" onChange={(e) => setDocument(e.target.files?.[0] ?? null)} />
          {event?.document_url && <Checkbox label="Remove the PDF" checked={removeDocument} onChange={(e) => setRemoveDocument(e.target.checked)} />}
        </div>
      </div>
      <div className="row-between">
        <button className="btn btn-primary" type="submit" disabled={save.busy}>{save.busy ? 'Saving…' : 'Save event'}</button>
        {event && (
          <span className="row">
            <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove.run()}>Delete</button>
            {event.series_id && <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove.run('future')}>Delete this and later repeats</button>}
          </span>
        )}
      </div>
    </form>
  );
}

function SeriesForm({ onDone }: { onDone: (message: string) => void }) {
  const today = clubToday();
  const [form, setForm] = useState({
    title: '', weekday: 6, nth: 2, start_time: '13:00', end_time: '', category: 'match',
    start_year: Number(today.slice(0, 4)), start_month: Number(today.slice(5, 7)), month_count: 12,
  });
  const body = () => ({ ...form, end_time: form.end_time || null });
  const preview = useAsync<{ label: string; dates: string[] } | null>(
    (signal) => (form.title ? api('/api/board/calendar/series/preview', { body: body(), signal }) : Promise.resolve(null)),
    [JSON.stringify(form)],
  );
  const save = useAction(async () => {
    const result = await api<{ created: number; label: string }>('/api/board/calendar/series', { body: body() });
    onDone(`Added ${result.created} events (${result.label}). Each one can be edited separately.`);
  });
  const num = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => setForm({ ...form, [k]: Number(e.target.value) });

  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
      <FormErrors error={save.error} />
      <TextField label="Title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Defensive Pistol Shoot" />
      <div className="grid-2">
        <SelectField label="Which week" value={form.nth} onChange={num('nth')}>{ORDINALS.map(([n, l]) => <option key={n} value={n}>{l}</option>)}</SelectField>
        <SelectField label="Day" value={form.weekday} onChange={num('weekday')}>{WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</SelectField>
      </div>
      <div className="grid-2">
        <TextField label="Starts" type="time" required value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
        <TextField label="Ends (optional)" type="time" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
      </div>
      <div className="grid-3">
        <SelectField label="First month" value={form.start_month} onChange={num('start_month')}>
          {Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2000, i, 1).toLocaleString('en-US', { month: 'long' })}</option>)}
        </SelectField>
        <TextField label="Year" type="number" min={2000} max={2100} value={form.start_year} onChange={num('start_year')} />
        <TextField label="For how many months" type="number" min={1} max={36} value={form.month_count} onChange={num('month_count')} />
      </div>
      <SelectField label="Type" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
        {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </SelectField>
      {preview.data && (
        <div className="card card-muted">
          <strong>{preview.data.label}</strong>, {preview.data.dates.length} dates:
          <p className="small">{preview.data.dates.map((d) => formatDate(d, 'short')).join(' · ')}</p>
        </div>
      )}
      <button className="btn btn-primary" type="submit" disabled={save.busy || !form.title}>Create events</button>
    </form>
  );
}
