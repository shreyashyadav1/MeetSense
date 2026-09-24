import { differenceInSeconds, format, isValid, parseISO } from 'date-fns';

/** Formats an ISO timestamp with a date-fns pattern; returns the input unchanged if it can't be parsed. */
export function formatDateTime(iso: string, pattern: string): string {
  const date = parseISO(iso);
  return isValid(date) ? format(date, pattern) : iso;
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
