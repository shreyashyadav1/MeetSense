import { describe, expect, it } from 'vitest';
import type { LiveSegment } from '../types';
import { applySegment, EMPTY_TRANSCRIPT, type TranscriptState } from './transcript';

function segment(sequence: number, overrides: Partial<LiveSegment> = {}): LiveSegment {
  return {
    id: `seg-${String(sequence)}`,
    meeting_id: 'm1',
    speaker: 'Speaker 1',
    text: `text ${String(sequence)}`,
    timestamp: sequence,
    confidence: 0.9,
    is_final: true,
    sequence,
    ...overrides,
  };
}

const interim = (sequence: number, text = `partial ${String(sequence)}`) =>
  segment(sequence, { id: 'interim-m1', is_final: false, text });

const apply = (...segments: LiveSegment[]): TranscriptState =>
  segments.reduce(applySegment, EMPTY_TRANSCRIPT);

describe('applySegment', () => {
  it('keeps final segments in sequence order when they arrive out of order', () => {
    const state = apply(segment(2), segment(5), segment(1), segment(4), segment(3));
    expect(state.segments.map((s) => s.sequence)).toEqual([1, 2, 3, 4, 5]);
  });

  it('drops duplicate finals by sequence or id and returns the same state', () => {
    const state = apply(segment(1), segment(2));
    expect(applySegment(state, segment(2))).toBe(state);
    expect(applySegment(state, segment(9, { id: 'seg-1' }))).toBe(state);
  });

  it('replaces the interim with newer interim results', () => {
    const state = apply(interim(3, 'Hel'), interim(4, 'Hello'));
    expect(state.interim?.text).toBe('Hello');
    expect(state.segments).toEqual([]);
  });

  it('accepts updated interim text that reuses the current sequence', () => {
    const state = apply(interim(3, 'Hel'), interim(3, 'Hello'));
    expect(state.interim?.text).toBe('Hello');
  });

  it('ignores interim results older than the current interim or the last final', () => {
    const withInterim = apply(interim(6));
    expect(applySegment(withInterim, interim(5))).toBe(withInterim);

    const withFinal = apply(segment(8));
    expect(applySegment(withFinal, interim(8))).toBe(withFinal);
    expect(applySegment(withFinal, interim(7))).toBe(withFinal);
  });

  it('clears the interim once a final at or after its sequence arrives', () => {
    expect(apply(interim(4), segment(4)).interim).toBeNull();
    expect(apply(interim(4), segment(5)).interim).toBeNull();
  });

  it('keeps a newer interim when a late final fills an earlier gap', () => {
    const state = apply(segment(1), segment(3), interim(4), segment(2));
    expect(state.interim?.sequence).toBe(4);
    expect(state.segments.map((s) => s.sequence)).toEqual([1, 2, 3]);
  });
});
