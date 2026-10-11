import { describe, expect, it } from 'vitest';
import {
  durationAttribute,
  formatClock,
  formatDateTime,
  formatDayHeading,
  formatDuration,
  formatLongDateTime,
  formatTime,
} from './format';

describe('formatDuration', () => {
  const start = '2026-09-23T10:00:00+00:00';

  it('picks the two most useful units', () => {
    expect(formatDuration(start, '2026-09-23T10:00:45+00:00')).toBe('45s');
    expect(formatDuration(start, '2026-09-23T10:12:05+00:00')).toBe('12m 5s');
    expect(formatDuration(start, '2026-09-23T11:20:30+00:00')).toBe('1h 20m');
  });

  it('measures ongoing meetings up to now and never goes negative', () => {
    expect(formatDuration(start, null, new Date('2026-09-23T10:01:00Z'))).toBe('1m 0s');
    expect(formatDuration(start, undefined, new Date('2026-09-23T09:59:00Z'))).toBe('0s');
  });

  it('returns an empty string for unparseable input', () => {
    expect(formatDuration('not a date')).toBe('');
  });
});

describe('formatClock', () => {
  it('formats minutes and hours', () => {
    expect(formatClock(0)).toBe('0:00');
    expect(formatClock(65.9)).toBe('1:05');
    expect(formatClock(3723)).toBe('1:02:03');
    expect(formatClock(65, { padMinutes: true })).toBe('01:05');
    expect(formatClock(Number.NaN)).toBe('0:00');
  });
});

describe('formatDateTime', () => {
  it('falls back to the raw value when it is not a date', () => {
    expect(formatDateTime('2026-09-23T10:00:00', 'yyyy-MM-dd')).toBe('2026-09-23');
    expect(formatDateTime('garbage', 'yyyy-MM-dd')).toBe('garbage');
  });
});

describe('date formatting', () => {
  const utc = { locale: 'en-US', timeZone: 'UTC' };

  it('formats times and full dates with Intl', () => {
    expect(formatTime('2026-09-23T15:04:00+00:00', utc)).toBe('3:04 PM');
    expect(formatLongDateTime('2026-09-23T15:04:00+00:00', utc)).toBe(
      'Wednesday, September 23, 2026 at 3:04 PM',
    );
  });

  it('falls back to the raw value when it is not a date', () => {
    expect(formatTime('garbage', utc)).toBe('garbage');
    expect(formatLongDateTime('garbage', utc)).toBe('garbage');
    expect(formatDayHeading('garbage', new Date(), utc)).toBe('garbage');
  });

  it('names nearby days and adds the year only for other years', () => {
    const now = new Date('2026-09-23T12:00:00Z');
    expect(formatDayHeading('2026-09-23T01:00:00+00:00', now, utc)).toBe('Today');
    expect(formatDayHeading('2026-09-22T23:30:00+00:00', now, utc)).toBe('Yesterday');
    expect(formatDayHeading('2026-09-08T10:00:00+00:00', now, utc)).toBe('Tuesday, September 8');
    expect(formatDayHeading('2025-12-31T10:00:00+00:00', now, utc)).toBe(
      'Wednesday, December 31, 2025',
    );
  });

  it('groups by the calendar day of the given time zone', () => {
    const now = new Date('2026-09-23T12:00:00Z');
    const lateEvening = '2026-09-23T02:30:00+00:00';
    expect(formatDayHeading(lateEvening, now, utc)).toBe('Today');
    expect(formatDayHeading(lateEvening, now, { ...utc, timeZone: 'America/New_York' })).toBe(
      'Yesterday',
    );
  });
});

describe('durationAttribute', () => {
  it('writes HTML duration strings', () => {
    expect(durationAttribute(0)).toBe('PT0S');
    expect(durationAttribute(65.4)).toBe('PT1M5S');
    expect(durationAttribute(3723)).toBe('PT1H2M3S');
    expect(durationAttribute(Number.NaN)).toBe('PT0S');
  });
});
