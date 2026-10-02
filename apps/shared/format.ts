/**
 * Formatting in the club's timezone. The club is in Kansas, so dates and times
 * are always shown as America/Chicago wall-clock time regardless of where the
 * viewer's browser thinks it is.
 */

export const CLUB_TIME_ZONE = 'America/Chicago';

/** "2026-10-10" -> "Saturday, October 10, 2026" (no timezone shift: it's a calendar date). */
export function formatDate(isoDate: string | null | undefined, style: 'long' | 'medium' | 'short' = 'long'): string {
  if (!isoDate) return '';
  const [year, month, day] = isoDate.slice(0, 10).split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const options: Intl.DateTimeFormatOptions =
    style === 'long'
      ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }
      : style === 'medium'
        ? { month: 'long', day: 'numeric', year: 'numeric' }
        : { month: 'short', day: 'numeric' };
  return new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' }).format(date);
}

/** "13:00" -> "1:00 PM" */
export function formatClock(hhmm: string | null | undefined): string {
  if (!hhmm) return '';
  const [h, m] = hhmm.split(':').map(Number);
  const suffix = h < 12 ? 'AM' : 'PM';
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${suffix}`;
}

/** A UTC instant shown in club time: "Oct 2, 2026, 3:04 PM". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: CLUB_TIME_ZONE,
  }).format(new Date(iso));
}

/** Today's date in club time as "YYYY-MM-DD". */
export function clubToday(): string {
  const parts = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: CLUB_TIME_ZONE }).format(new Date());
  return parts;
}

export function formatMoney(amount: string | number | null | undefined): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(amount ?? 0));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function titleCase(value: string | null | undefined): string {
  return (value ?? '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export const STATUS_LABELS: Record<string, string> = {
  member: 'Active member',
  waiting_list: 'Waiting list',
  non_member: 'Non-member',
  expired: 'Expired',
  terminated: 'Terminated',
};

export const CATEGORY_LABELS: Record<string, string> = {
  match: 'Match',
  member: 'Members',
  meeting: 'Meeting',
  event: 'Club event',
  closure: 'Range closed',
};
