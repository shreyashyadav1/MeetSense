export const MEETING_TITLE_MAX_LENGTH = 120;

/** Length as the API counts it: Unicode code points of the trimmed title. */
export function meetingTitleLength(title: string): number {
  return [...title.trim()].length;
}

/** Mirrors the API rule (1–120 characters after trimming). Returns an error message, or null. */
export function validateMeetingTitle(title: string): string | null {
  const length = meetingTitleLength(title);
  if (length === 0) return 'Enter a title for the meeting.';
  if (length > MEETING_TITLE_MAX_LENGTH) {
    return `Keep the title to ${MEETING_TITLE_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}
