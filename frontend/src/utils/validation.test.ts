import { describe, expect, it } from 'vitest';
import { meetingTitleLength, validateMeetingTitle } from './validation';

describe('validateMeetingTitle', () => {
  it('requires at least one character after trimming', () => {
    expect(validateMeetingTitle('')).toMatch(/enter a title/i);
    expect(validateMeetingTitle('   ')).toMatch(/enter a title/i);
    expect(validateMeetingTitle(' Standup ')).toBeNull();
  });

  it('allows at most 120 characters after trimming', () => {
    expect(validateMeetingTitle('a'.repeat(120))).toBeNull();
    expect(validateMeetingTitle(`  ${'a'.repeat(120)}  `)).toBeNull();
    expect(validateMeetingTitle('a'.repeat(121))).toMatch(/120 characters or fewer/);
  });

  it('counts code points the way the API does', () => {
    expect(meetingTitleLength('🎉'.repeat(120))).toBe(120);
    expect(validateMeetingTitle('🎉'.repeat(120))).toBeNull();
  });
});
