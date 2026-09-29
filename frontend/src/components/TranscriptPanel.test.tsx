import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TranscriptSegment } from '../types';
import { assignSpeakerColors, SPEAKER_COLORS, UNKNOWN_SPEAKER_COLOR } from '../utils/speakers';
import { TranscriptPanel } from './TranscriptPanel';

let nextId = 0;
function segment(speaker: string, text = `Line ${String(++nextId)}`): TranscriptSegment {
  return {
    id: `seg-${String(++nextId)}`,
    meeting_id: 'm1',
    speaker,
    text,
    timestamp: nextId,
    confidence: 0.9,
    is_final: true,
  };
}

/** Colour of each rendered speaker label, in document order. */
function labelColors(): Array<[string, string]> {
  return Array.from(document.querySelectorAll<HTMLElement>('.transcript-group__speaker')).map(
    (label) => [label.textContent ?? '', label.style.color],
  );
}

/** Normalises a hex colour the way the DOM reports inline styles. */
function rgb(hex: string): string {
  const element = document.createElement('span');
  element.style.color = hex;
  return element.style.color;
}

describe('assignSpeakerColors', () => {
  it('assigns palette colours by order of first appearance and cycles', () => {
    const speakers = Array.from({ length: SPEAKER_COLORS.length + 1 }, (_, i) => `Speaker ${String(i + 1)}`);
    const colors = assignSpeakerColors(['Speaker 1', ...speakers, 'Speaker 2']);

    expect(colors.get('Speaker 1')).toBe(SPEAKER_COLORS[0]);
    expect(colors.get('Speaker 2')).toBe(SPEAKER_COLORS[1]);
    expect(colors.get(`Speaker ${String(SPEAKER_COLORS.length + 1)}`)).toBe(SPEAKER_COLORS[0]);
    expect(assignSpeakerColors(['', 'Bob']).get('Bob')).toBe(SPEAKER_COLORS[0]);
  });
});

describe('TranscriptPanel speaker colours', () => {
  it('gives Deepgram speaker labels distinct colours', () => {
    render(
      <TranscriptPanel
        segments={[
          segment('Speaker 1'),
          segment('Speaker 2'),
          segment('Speaker 3'),
          segment('Speaker 1'),
        ]}
      />,
    );

    expect(labelColors()).toEqual([
      ['Speaker 1', rgb(SPEAKER_COLORS[0])],
      ['Speaker 2', rgb(SPEAKER_COLORS[1])],
      ['Speaker 3', rgb(SPEAKER_COLORS[2])],
      ['Speaker 1', rgb(SPEAKER_COLORS[0])],
    ]);
    expect(screen.getAllByText('S1')[0]).toHaveStyle({ backgroundColor: SPEAKER_COLORS[0] });
  });

  it('colours by order of appearance, never by name, so labels cannot collide', () => {
    render(
      <TranscriptPanel segments={[segment('Speaker 1'), segment('Alice'), segment('David')]} />,
    );

    expect(labelColors()).toEqual([
      ['Speaker 1', rgb(SPEAKER_COLORS[0])],
      ['Alice', rgb(SPEAKER_COLORS[1])],
      ['David', rgb(SPEAKER_COLORS[2])],
    ]);
  });

  it('keeps the interim speaker colour stable and handles unknown speakers', () => {
    const { rerender } = render(
      <TranscriptPanel
        segments={[segment('Speaker 1')]}
        interimSegment={{ ...segment('Speaker 2', 'Still talk'), is_final: false }}
        isLive
      />,
    );
    expect(labelColors()[1]).toEqual(['Speaker 2', rgb(SPEAKER_COLORS[1])]);

    rerender(
      <TranscriptPanel
        segments={[segment('Speaker 1')]}
        interimSegment={{ ...segment('', 'Hello'), is_final: false }}
        isLive
      />,
    );
    expect(labelColors()[1]).toEqual(['Unknown speaker', rgb(UNKNOWN_SPEAKER_COLOR)]);
    expect(screen.getByText('?')).toBeInTheDocument();
  });
});
