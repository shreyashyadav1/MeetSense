import { differenceInSeconds, isValid, parseISO } from 'date-fns';

/** Locale and time zone overrides; both default to the user's own. Tests pin them. */
export interface DateFormatOptions {
  locale?: string;
  timeZone?: string;
}

function parseDate(iso: string): Date | null {
  const date = parseISO(iso);
  return isValid(date) ? date : null;
}

function format(iso: string, options: Intl.DateTimeFormatOptions, { locale, timeZone }: DateFormatOptions) {
  const date = parseDate(iso);
  return date ? new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(date) : iso;
}

/** Time of day, e.g. "3:14 PM"; returns the input unchanged if it can't be parsed. */
export function formatTime(iso: string, options: DateFormatOptions = {}): string {
  return format(iso, { hour: 'numeric', minute: '2-digit' }, options);
}

/** Full date and time, e.g. "Sunday, October 11, 2026 at 3:14 PM". */
export function formatLongDateTime(iso: string, options: DateFormatOptions = {}): string {
  return format(iso, { dateStyle: 'full', timeStyle: 'short' }, options);
}

/** Calendar day in the given time zone as YYYY-MM-DD, used to group meetings by day. */
export function dayKey(date: Date, { timeZone }: DateFormatOptions = {}): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}

/**
 * Heading for a day of meetings: "Today", "Yesterday", "Wednesday, October 8",
 * or the same with the year when it isn't the current year.
 */
export function formatDayHeading(
  iso: string,
  now: Date = new Date(),
  options: DateFormatOptions = {},
): string {
  const date = parseDate(iso);
  if (!date) return iso;

  const key = dayKey(date, options);
  const today = dayKey(now, options);
  const [year, month, day] = today.split('-').map(Number);
  const yesterday = new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10);

  if (key === today || key === yesterday) {
    const relative = new Intl.RelativeTimeFormat(options.locale, { numeric: 'auto' }).format(
      key === today ? 0 : -1,
      'day',
    );
    return relative.charAt(0).toLocaleUpperCase(options.locale) + relative.slice(1);
  }

  return new Intl.DateTimeFormat(options.locale, {
    timeZone: options.timeZone,
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: key.slice(0, 4) === today.slice(0, 4) ? undefined : 'numeric',
  }).format(date);
}

/**
 * Human-readable meeting length, e.g. "45s", "12m 5s" or "1h 20m".
 * Meetings without an end time are measured up to `now`.
 */
export function formatDuration(
  startedAt: string,
  endedAt?: string | null,
  now: Date = new Date(),
): string {
  const start = parseISO(startedAt);
  const end = endedAt ? parseISO(endedAt) : now;
  if (!isValid(start) || !isValid(end)) return '';

  const totalSeconds = Math.max(0, differenceInSeconds(end, start));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

/** Clock-style elapsed time: "1:05" or "1:02:03" ("01:05" with `padMinutes`). */
export function formatClock(totalSeconds: number, { padMinutes = false } = {}): string {
  const clamped = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0;
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = String(clamped % 60).padStart(2, '0');

  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`;
  return `${padMinutes ? String(minutes).padStart(2, '0') : minutes}:${seconds}`;
}

/** The same offset as an HTML duration string, e.g. "PT1M5S", for a <time> element. */
export function durationAttribute(totalSeconds: number): string {
  const clamped = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0;
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  return `PT${hours ? `${hours}H` : ''}${minutes ? `${minutes}M` : ''}${seconds}S`;
}
