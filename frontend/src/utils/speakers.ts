/** Speaker colours, handed out in order of first appearance. */
export const SPEAKER_COLORS = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#f97316',
  '#ec4899',
] as const;

/** For segments whose speaker isn't known yet (e.g. interim results). */
export const UNKNOWN_SPEAKER_COLOR = '#94a3b8';

/**
 * Maps each speaker to a colour by order of first appearance, cycling through
 * the palette, so any labels ("Speaker 1", real names, ...) get distinct colours.
 */
export function assignSpeakerColors(speakers: Iterable<string>): Map<string, string> {
  const colors = new Map<string, string>();
  for (const speaker of speakers) {
    if (speaker && !colors.has(speaker)) {
      colors.set(speaker, SPEAKER_COLORS[colors.size % SPEAKER_COLORS.length]);
    }
  }
  return colors;
}

export function speakerLabel(speaker: string): string {
  return speaker.trim() || 'Unknown speaker';
}

/** Up to two initials, e.g. "Speaker 2" -> "S2"; "?" when the speaker is unknown. */
export function speakerInitials(speaker: string): string {
  const words = speaker.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  return words
    .map((word) => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}
