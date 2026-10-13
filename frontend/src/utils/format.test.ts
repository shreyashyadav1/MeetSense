import { describe, expect, it } from 'vitest';
import { formatClock, formatDateTime, formatDuration } from './format';

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
