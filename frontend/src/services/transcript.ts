import type { LiveSegment } from '../types';

export interface TranscriptState {
  /** Final segments in sequence order. */
  readonly segments: readonly LiveSegment[];
  /** The utterance currently being transcribed, if any. */
  readonly interim: LiveSegment | null;
}

export const EMPTY_TRANSCRIPT: TranscriptState = { segments: [], interim: null };

/**
 * Folds a live segment into the transcript.
 *
 * Sequence numbers are monotonic per meeting, even across reconnects, so they
 * decide ordering, drop finals that were already received (replays after a
 * reconnect) and discard interim results that a newer segment has superseded.
 * Returns `state` itself when the segment changes nothing.
 */
export function applySegment(state: TranscriptState, segment: LiveSegment): TranscriptState {
  const { segments, interim } = state;

  if (!segment.is_final) {
    const lastFinal = segments.at(-1)?.sequence ?? -Infinity;
    const superseded =
      segment.sequence <= lastFinal || (interim !== null && segment.sequence < interim.sequence);
    return superseded ? state : { segments, interim: segment };
  }

  if (segments.some((s) => s.sequence === segment.sequence || s.id === segment.id)) {
    return state;
  }

  // Segments almost always arrive in order, so search from the end.
  let index = segments.length;
  while (index > 0 && segments[index - 1].sequence > segment.sequence) index -= 1;

  return {
    segments: [...segments.slice(0, index), segment, ...segments.slice(index)],
    interim: interim !== null && interim.sequence <= segment.sequence ? null : interim,
  };
}
