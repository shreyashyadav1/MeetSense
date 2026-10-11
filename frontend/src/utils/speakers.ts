import type { TranscriptSegment } from '../types';

/**
 * Speaker voices, handed out in order of first appearance. Each entry is a CSS
 * color that points at a design token (see index.css), so the palette is
 * defined once, in OKLCH, next to the rest of the colors.
 */
export const SPEAKER_COLORS = [
  'var(--voice-1)',
  'var(--voice-2)',
  'var(--voice-3)',
  'var(--voice-4)',
  'var(--voice-5)',
  'var(--voice-6)',
  'var(--voice-7)',
  'var(--voice-8)',
] as const;

/** For segments whose speaker isn't known (yet). */
export const UNKNOWN_SPEAKER_COLOR = 'var(--voice-unknown)';

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

export interface SpeakerSummary {
  speaker: string;
  label: string;
  color: string;
  words: number;
  /** Fraction of all transcribed words, from 0 to 1. */
  share: number;
}

const countWords = (text: string) => text.split(/\s+/).filter(Boolean).length;

/** Who spoke, in order of first appearance, with how much of the conversation each one had. */
export function summarizeSpeakers(segments: readonly TranscriptSegment[]): SpeakerSummary[] {
  const colors = assignSpeakerColors(segments.map((segment) => segment.speaker));
  const words = new Map<string, number>();
  for (const segment of segments) {
    words.set(segment.speaker, (words.get(segment.speaker) ?? 0) + countWords(segment.text));
  }

  const total = [...words.values()].reduce((sum, count) => sum + count, 0);
  return [...words.entries()].map(([speaker, count]) => ({
    speaker,
    label: speakerLabel(speaker),
    color: colors.get(speaker) ?? UNKNOWN_SPEAKER_COLOR,
    words: count,
    share: total > 0 ? count / total : 0,
  }));
}
