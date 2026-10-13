import React, { useEffect, useRef, useMemo } from 'react';
import type { TranscriptSegment } from '../types';
import { formatClock } from '../utils/format';
import {
  assignSpeakerColors,
  speakerInitials,
  speakerLabel,
  UNKNOWN_SPEAKER_COLOR,
} from '../utils/speakers';

interface TranscriptPanelProps {
  segments: readonly TranscriptSegment[];
  isLive?: boolean;
  interimSegment?: TranscriptSegment | null;
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

const ListeningDots: React.FC = () => (
  <div className="listening-indicator">
    <span className="listening-indicator__text">Listening</span>
    <span className="listening-dots">
      <span />
      <span />
      <span />
    </span>
  </div>
);

const InterimDots: React.FC = () => (
  <span className="interim-dots" aria-hidden="true">
    <span />
    <span />
    <span />
  </span>
);

interface SpeakerGroupRowProps {
  group: SpeakerGroup;
  color: string;
  /** Renders the in-progress (not yet final) utterance. */
  interim?: boolean;
}

const SpeakerGroupRow: React.FC<SpeakerGroupRowProps> = ({ group, color, interim = false }) => (
  <div className={`transcript-group transcript-group--enter${interim ? ' interim' : ''}`}>
    <div className="transcript-group__avatar" style={{ backgroundColor: color }} aria-hidden="true">
      {speakerInitials(group.speaker)}
    </div>
    <div className="transcript-group__content">
      <div className="transcript-group__header">
        <span className="transcript-group__speaker" style={{ color }}>
          {speakerLabel(group.speaker)}
        </span>
        <span className="transcript-group__time">{formatClock(group.segments[0].timestamp)}</span>
      </div>
      {group.segments.map((segment) => (
        <p key={segment.id} className="transcript-group__text">
          {segment.text}
          {interim && <InterimDots />}
        </p>
      ))}
    </div>
  </div>
);

export const TranscriptPanel: React.FC<TranscriptPanelProps> = ({
  segments,
  isLive = false,
  interimSegment = null,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Colours follow order of appearance; the interim speaker is included so it
  // keeps the same colour once the segment is finalised.
  const speakerColors = useMemo(() => {
    const speakers = segments.map((segment) => segment.speaker);
    if (interimSegment) speakers.push(interimSegment.speaker);
    return assignSpeakerColors(speakers);
  }, [segments, interimSegment]);

  const groups = useMemo(() => groupBySpeaker(segments), [segments]);
  const colorOf = (speaker: string) => speakerColors.get(speaker) ?? UNKNOWN_SPEAKER_COLOR;

  // Keep the newest text in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [segments.length, interimSegment]);

  if (segments.length === 0 && !interimSegment) {
    return (
      <div className="transcript-panel transcript-panel--empty">
        {isLive ? (
          <ListeningDots />
        ) : (
          <p className="transcript-panel__empty-text">No transcript available.</p>
        )}
      </div>
    );
  }

  return (
    <div className="transcript-panel">
      <div className="transcript-panel__inner">
        {groups.map((group) => (
          <SpeakerGroupRow key={group.segments[0].id} group={group} color={colorOf(group.speaker)} />
        ))}

        {interimSegment && (
          <SpeakerGroupRow
            group={{ speaker: interimSegment.speaker, segments: [interimSegment] }}
            color={colorOf(interimSegment.speaker)}
            interim
          />
        )}

        {isLive && segments.length > 0 && !interimSegment && (
          <div className="transcript-live-indicator">
            <span className="transcript-live-dot" />
            <span>Listening...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
