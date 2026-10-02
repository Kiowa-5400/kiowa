import { useMemo, useState } from 'react';
import { api } from '@shared/api';
import { CATEGORY_LABELS, clubToday, formatClock, formatDate } from '@shared/format';
import { usePageTitle } from '@shared/router';
import { Empty, ErrorState, Html, Loading, Modal, useAsync } from '@shared/ui';
import { CustomSections, PageIntro } from '../components/Sections';
import { section, usePage } from '../site';

export type CalendarEvent = {
  id: number;
  title: string;
  local_date: string;
  local_time: string | null;
  local_end_time: string | null;
  all_day: boolean;
  category: string;
  description_html: string | null;
  link_url: string | null;
  link_label: string | null;
  image_url: string | null;
  document_url: string | null;
  document_filename: string | null;
  recurrence_label: string | null;
};

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function monthLabel(year: number, month: number): string {
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month, 1)));
}

export function eventTime(event: CalendarEvent): string {
  if (event.all_day) return 'All day';
  return event.local_end_time ? `${formatClock(event.local_time)} – ${formatClock(event.local_end_time)}` : formatClock(event.local_time);
}

export function CalendarPage() {
  usePageTitle('Calendar');
  const page = usePage('calendar');
  const today = clubToday();
  const [cursor, setCursor] = useState(() => ({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) - 1 }));
  const [selected, setSelected] = useState<CalendarEvent | null>(null);

  const first = new Date(Date.UTC(cursor.year, cursor.month, 1));
  const daysInMonth = new Date(Date.UTC(cursor.year, cursor.month + 1, 0)).getUTCDate();
  const start = `${cursor.year}-${pad(cursor.month + 1)}-01`;
  const end = `${cursor.year}-${pad(cursor.month + 1)}-${pad(daysInMonth)}`;
  const events = useAsync((signal) => api<CalendarEvent[]>('/api/public/calendar', { signal, query: { start, end } }), [start]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of events.data ?? []) map.set(event.local_date, [...(map.get(event.local_date) ?? []), event]);
    return map;
  }, [events.data]);

  const move = (delta: number) => setCursor(({ year, month }) => {
    const next = month + delta;
    return { year: year + Math.floor(next / 12), month: ((next % 12) + 12) % 12 };
  });

  const cells: (string | null)[] = [
    ...Array.from({ length: first.getUTCDay() }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => `${start.slice(0, 8)}${pad(i + 1)}`),
  ];
  while (cells.length % 7) cells.push(null);
  const weeks = Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));

  return (
    <>
      <PageIntro section={section(page.data, 'intro')} kicker="Schedule" />

      <section className="card calendar" aria-labelledby="month-heading">
        <div className="row-between calendar-toolbar">
          <button type="button" className="btn btn-sm" onClick={() => move(-1)} aria-label="Previous month">← Prev</button>
          <h2 id="month-heading" aria-live="polite">{monthLabel(cursor.year, cursor.month)}</h2>
          <button type="button" className="btn btn-sm" onClick={() => move(1)} aria-label="Next month">Next →</button>
        </div>
        <ul className="legend" aria-label="Event categories">
          {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
            <li key={key} className={`cat-${key}`}><span className="cat-dot" aria-hidden="true" /> {label}</li>
          ))}
        </ul>

        {events.loading && <Loading label="Loading events…" />}
        {events.error && <ErrorState message="The calendar couldn't be loaded right now." onRetry={events.reload} />}

        {events.data && (
          <>
            <table className="month-grid">
              <caption className="visually-hidden">Events in {monthLabel(cursor.year, cursor.month)}</caption>
              <thead><tr>{WEEKDAYS.map((d) => <th key={d} scope="col">{d}</th>)}</tr></thead>
              <tbody>
                {weeks.map((week, i) => (
                  <tr key={i}>
                    {week.map((day, j) => (
                      <td key={j} className={day === today ? 'today' : undefined}>
                        {day && (
                          <>
                            <span className="day-number">{Number(day.slice(8))}</span>
                            {(byDay.get(day) ?? []).map((event) => (
                              <button key={event.id} type="button" className={`event-chip cat-${event.category}`} onClick={() => setSelected(event)}>
                                {!event.all_day && <span className="event-chip-time">{formatClock(event.local_time)}</span>} {event.title}
                              </button>
                            ))}
                          </>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>

            <ol className="agenda" aria-label="Events this month">
              {events.data.length === 0 && <li><Empty>No events are scheduled this month.</Empty></li>}
              {events.data.map((event) => (
                <li key={event.id} className={`cat-${event.category}`}>
                  <button type="button" className="agenda-item" onClick={() => setSelected(event)}>
                    <span className="cat-dot" aria-hidden="true" />
                    <span>
                      <strong>{event.title}</strong>
                      <span className="small muted" style={{ display: 'block' }}>{formatDate(event.local_date)} · {eventTime(event)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            {events.data.length === 0 && <p className="muted month-empty">No events are scheduled this month.</p>}
          </>
        )}
      </section>

      <Modal open={selected !== null} title={selected?.title ?? ''} onClose={() => setSelected(null)}>
        {selected && <EventDetail event={selected} />}
      </Modal>
      <CustomSections sections={page.data} />
    </>
  );
}

function EventDetail({ event }: { event: CalendarEvent }) {
  return (
    <div className="stack">
      <p>
        <strong>{formatDate(event.local_date)}</strong>
        <br />
        {eventTime(event)} <span className="muted">(Kansas time)</span>
      </p>
      <p className={`row cat-${event.category}`}><span className="cat-dot" aria-hidden="true" /> {CATEGORY_LABELS[event.category] ?? event.category}</p>
      {event.recurrence_label && <p className="badge">Recurring — {event.recurrence_label}</p>}
      {event.image_url && <img src={event.image_url} alt="" className="event-image" />}
      <Html html={event.description_html} />
      <div className="row">
        {event.link_url && <a className="btn btn-primary" href={event.link_url} rel="noopener noreferrer">{event.link_label || 'More information'}</a>}
        {event.document_url && <a className="btn" href={event.document_url} rel="noopener">Download {event.document_filename ?? 'document'}</a>}
      </div>
    </div>
  );
}
