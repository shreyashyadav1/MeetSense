import React, { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';
import type { TranscriptSegment } from '../types';
import { durationAttribute, formatClock } from '../utils/format';
import { assignSpeakerColors, speakerLabel, UNKNOWN_SPEAKER_COLOR } from '../utils/speakers';
import './TranscriptPanel.css';

interface TranscriptPanelProps {
  segments: readonly TranscriptSegment[];
  interimSegment?: TranscriptSegment | null;
  /** The session is still running, so more lines may arrive. */
  isLive?: boolean;
  /**
   * "live" scrolls on its own and keeps the newest line in view while the
   * reader is at the bottom; "saved" is part of the page, like a document.
   */
  variant?: 'live' | 'saved';
  /** Audio is being transcribed but nobody is mid-sentence: show a quiet "Listening" line. */
  listening?: boolean;
  /** Shown when there is no transcript yet. */
  emptyMessage?: string;
}

/** Consecutive segments from the same speaker. */
interface SpeakerGroup {
  speaker: string;
  segments: TranscriptSegment[];
}

function groupBySpeaker(segments: readonly TranscriptSegment[]): SpeakerGroup[] {
  const groups: SpeakerGroup[] = [];
  for (const segment of segments) {
    const last = groups.at(-1);
    if (last && last.speaker === segment.speaker) {
      last.segments.push(segment);
    } else {
      groups.push({ speaker: segment.speaker, segments: [segment] });
    }
  }
  return groups;
}

const voiceStyle = (color: string) => ({ '--voice': color }) as React.CSSProperties;

interface TurnProps {
  group: SpeakerGroup;
  color: string;
  /** The utterance still being transcribed; its speaker may not be known yet. */
  interim?: boolean;
  as?: 'li' | 'div';
}

const Turn: React.FC<TurnProps> = ({ group, color, interim = false, as: Element = 'li' }) => {
  const startedAt = group.segments[0].timestamp;
  const label = interim && !group.speaker.trim() ? 'Transcribing' : speakerLabel(group.speaker);

  return (
    <Element className={`turn${interim ? ' turn--interim' : ''}`} style={voiceStyle(color)}>
      <div className="turn__who">
        <span className="turn__speaker">{label}</span>
        <time className="turn__time" dateTime={durationAttribute(startedAt)}>
          {formatClock(startedAt)}
        </time>
      </div>
      <div className="turn__words">
        {group.segments.map((segment) => (
          <p key={segment.id} className="turn__line" data-line={interim ? 'interim' : 'final'}>
            {segment.text}
          </p>
        ))}
      </div>
    </Element>
  );
};

/** How close to the end (in px) still counts as "reading the newest line". */
const FOLLOW_SLACK_PX = 48;

/**
 * Keeps a scroll container pinned to its newest content while the reader is
 * at the bottom, and leaves it alone as soon as they scroll back to re-read.
 */
function useFollowLatest(enabled: boolean, lineCount: number) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);
  const [following, setFollowing] = useState(true);
  const [linesWhenLeft, setLinesWhenLeft] = useState(0);

  const pin = useCallback(() => {
    const scroller = scrollerRef.current;
    if (scroller && followingRef.current) scroller.scrollTop = scroller.scrollHeight;
  }, []);

  // Any render can change the height of the transcript (a new line, a longer interim).
  useLayoutEffect(() => {
    if (enabled) pin();
  });

  // So can things outside React: fonts finishing loading, the window being resized.
  useEffect(() => {
    if (!enabled || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(pin);
    if (scrollerRef.current) observer.observe(scrollerRef.current);
    if (contentRef.current) observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, [enabled, pin]);

  const handleScroll = () => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const atEnd =
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= FOLLOW_SLACK_PX;
    if (atEnd === followingRef.current) return;
    followingRef.current = atEnd;
    setFollowing(atEnd);
    if (!atEnd) setLinesWhenLeft(lineCount);
  };

  const jumpToLatest = () => {
    followingRef.current = true;
    setFollowing(true);
    pin();
  };

  return {
    scrollerRef,
    contentRef,
    following,
    newLines: following ? 0 : Math.max(0, lineCount - linesWhenLeft),
    handleScroll,
    jumpToLatest,
  };
}

export const TranscriptPanel = memo(function TranscriptPanel({
  segments,
  interimSegment = null,
  isLive = false,
  variant = 'saved',
  listening = false,
  emptyMessage,
}: TranscriptPanelProps) {
  const live = variant === 'live';

  // Colours follow order of appearance; the interim speaker is included so it
  // keeps the same colour once the segment is finalised.
  const speakerColors = useMemo(() => {
    const speakers = segments.map((segment) => segment.speaker);
    if (interimSegment) speakers.push(interimSegment.speaker);
    return assignSpeakerColors(speakers);
  }, [segments, interimSegment]);

  const groups = useMemo(() => groupBySpeaker(segments), [segments]);
  const colorOf = (speaker: string) => speakerColors.get(speaker) ?? UNKNOWN_SPEAKER_COLOR;
  const { scrollerRef, contentRef, following, newLines, handleScroll, jumpToLatest } =
    useFollowLatest(live, segments.length);

  const isEmpty = segments.length === 0 && !interimSegment;
  const showListening = isLive && listening && !interimSegment;

  const body = isEmpty ? (
    <p className="transcript__empty">
      {emptyMessage ?? (isLive ? 'Listening for the first words…' : 'No transcript was recorded.')}
    </p>
  ) : (
    <>
      <ol
        className="transcript__lines"
        role={live ? 'log' : undefined}
        aria-live={live ? 'polite' : undefined}
      >
        {groups.map((group) => (
          <Turn key={group.segments[0].id} group={group} color={colorOf(group.speaker)} />
        ))}
      </ol>

      {interimSegment && (
        <Turn
          as="div"
          group={{ speaker: interimSegment.speaker, segments: [interimSegment] }}
          color={colorOf(interimSegment.speaker)}
          interim
        />
      )}
      {showListening && (
        <div className="turn turn--listening">
          <div className="turn__who" aria-hidden="true" />
          <p className="turn__words">Listening…</p>
        </div>
      )}
    </>
  );

  if (!live) {
    return <div className="transcript transcript--saved">{body}</div>;
  }

  return (
    <div className="transcript transcript--live">
      <div
        ref={scrollerRef}
        className="transcript__scroller"
        onScroll={handleScroll}
        tabIndex={0}
        role="region"
        aria-label="Transcript"
      >
        <div ref={contentRef} className="transcript__content">
          {body}
        </div>
      </div>

      {!following && !isEmpty && (
        <button type="button" className="transcript__jump" onClick={jumpToLatest}>
          <ArrowDown size={16} aria-hidden="true" />
          Jump to latest
          {newLines > 0 && (
            <span className="transcript__jump-count">
              <span className="visually-hidden">, </span>
              {newLines} new {newLines === 1 ? 'line' : 'lines'}
            </span>
          )}
        </button>
      )}
    </div>
  );
});
