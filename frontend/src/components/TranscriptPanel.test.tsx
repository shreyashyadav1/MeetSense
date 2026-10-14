import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { TranscriptSegment } from '../types';
import {
  assignSpeakerColors,
  SPEAKER_COLORS,
  summarizeSpeakers,
  UNKNOWN_SPEAKER_COLOR,
} from '../utils/speakers';
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

/** The voice colour a line of text is set in (its turn's --voice). */
function voiceOf(element: Element | null): string {
  return element?.closest<HTMLElement>('.turn')?.style.getPropertyValue('--voice') ?? '';
}

/** Each rendered speaker label with its voice colour, in document order. */
function labelColors(): Array<[string, string]> {
  return Array.from(document.querySelectorAll<HTMLElement>('.turn__speaker')).map((label) => [
    label.textContent ?? '',
    voiceOf(label),
  ]);
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

describe('summarizeSpeakers', () => {
  it('counts each speaker’s share of the words in order of appearance', () => {
    const summary = summarizeSpeakers([
      segment('Alice', 'one two three'),
      segment('Bob', 'four'),
      segment('Alice', 'five six  seven  eight'),
    ]);

    expect(summary).toEqual([
      { speaker: 'Alice', label: 'Alice', color: SPEAKER_COLORS[0], words: 7, share: 7 / 8 },
      { speaker: 'Bob', label: 'Bob', color: SPEAKER_COLORS[1], words: 1, share: 1 / 8 },
    ]);
    expect(summarizeSpeakers([])).toEqual([]);
  });
});

describe('TranscriptPanel speaker colours', () => {
  it('gives Deepgram speaker labels distinct colours', () => {
    render(
      <TranscriptPanel
        segments={[
          segment('Speaker 1', 'Morning, all.'),
          segment('Speaker 2'),
          segment('Speaker 3'),
          segment('Speaker 1'),
        ]}
      />,
    );

    expect(labelColors()).toEqual([
      ['Speaker 1', SPEAKER_COLORS[0]],
      ['Speaker 2', SPEAKER_COLORS[1]],
      ['Speaker 3', SPEAKER_COLORS[2]],
      ['Speaker 1', SPEAKER_COLORS[0]],
    ]);
    // The words themselves are set in the speaker's ink, not just the label.
    expect(voiceOf(screen.getByText('Morning, all.'))).toBe(SPEAKER_COLORS[0]);
  });

  it('colours by order of appearance, never by name, so labels cannot collide', () => {
    render(
      <TranscriptPanel segments={[segment('Speaker 1'), segment('Alice'), segment('David')]} />,
    );

    expect(labelColors()).toEqual([
      ['Speaker 1', SPEAKER_COLORS[0]],
      ['Alice', SPEAKER_COLORS[1]],
      ['David', SPEAKER_COLORS[2]],
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
    expect(labelColors()[1]).toEqual(['Speaker 2', SPEAKER_COLORS[1]]);
    expect(screen.getByText('Still talk')).toHaveAttribute('data-line', 'interim');

    rerender(
      <TranscriptPanel
        segments={[segment('Speaker 1')]}
        interimSegment={{ ...segment('', 'Hello'), is_final: false }}
        isLive
      />,
    );
    // Not knowing the speaker yet is expected while a line is still being transcribed.
    expect(labelColors()[1]).toEqual(['Transcribing', UNKNOWN_SPEAKER_COLOR]);
    expect(screen.getByText('Hello')).toHaveAttribute('data-line', 'interim');
  });

  it('labels final lines without a speaker as unknown', () => {
    render(<TranscriptPanel segments={[segment('', 'Who said this?')]} />);

    expect(labelColors()).toEqual([['Unknown speaker', UNKNOWN_SPEAKER_COLOR]]);
    expect(screen.getByText('Who said this?')).toHaveAttribute('data-line', 'final');
  });
});

describe('TranscriptPanel live view', () => {
  /** jsdom has no layout, so give the scroller a fixed viewport over a tall transcript. */
  function fakeScrollGeometry(scroller: HTMLElement, contentHeight: () => number) {
    let top = 0;
    Object.defineProperties(scroller, {
      clientHeight: { configurable: true, get: () => 400 },
      scrollHeight: { configurable: true, get: contentHeight },
      scrollTop: {
        configurable: true,
        get: () => top,
        set: (value: number) => {
          top = Math.max(0, Math.min(value, contentHeight() - 400));
        },
      },
    });
  }

  it('follows new lines at the bottom but never moves a reader who scrolled back', async () => {
    const lines = [segment('Alice'), segment('Bob'), segment('Alice')];
    const { rerender } = render(<TranscriptPanel variant="live" isLive segments={lines} />);
    const scroller = screen.getByRole('region', { name: 'Transcript' });
    let height = 1000;
    fakeScrollGeometry(scroller, () => height);

    // At the bottom: a new line keeps the newest text in view.
    height = 1100;
    rerender(<TranscriptPanel variant="live" isLive segments={[...lines, segment('Bob')]} />);
    expect(scroller.scrollTop).toBe(700);
    expect(screen.queryByRole('button', { name: /jump to latest/i })).not.toBeInTheDocument();

    // The reader scrolls up to re-read something.
    act(() => {
      scroller.scrollTop = 200;
    });
    fireEvent.scroll(scroller);
    height = 1200;
    rerender(
      <TranscriptPanel variant="live" isLive segments={[...lines, segment('Bob'), segment('Carol')]} />,
    );
    expect(scroller.scrollTop).toBe(200);

    const jump = screen.getByRole('button', { name: /jump to latest/i });
    expect(jump).toHaveTextContent('1 new line');

    await userEvent.click(jump);
    expect(scroller.scrollTop).toBe(800);
    expect(screen.queryByRole('button', { name: /jump to latest/i })).not.toBeInTheDocument();
  });

  it('announces final lines politely and keeps the line in progress out of the log', () => {
    render(
      <TranscriptPanel
        variant="live"
        isLive
        segments={[segment('Alice', 'Final words.')]}
        interimSegment={{ ...segment('', 'Half a sent'), is_final: false }}
      />,
    );

    const log = screen.getByRole('log');
    expect(log).toHaveAttribute('aria-live', 'polite');
    expect(log).toHaveTextContent('Final words.');
    expect(log).not.toHaveTextContent('Half a sent');
    expect(screen.getByText('Half a sent')).toBeInTheDocument();
  });
});
