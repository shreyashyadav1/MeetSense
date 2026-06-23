import React, { useEffect, useRef, useMemo } from 'react';
import type { TranscriptSegment } from '../types';

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
  isLive?: boolean;
  interimSegment?: TranscriptSegment | null;
}

// Consistent color palette per speaker
const SPEAKER_COLORS: Record<string, string> = {
  Alice: '#6366f1',
  Bob: '#10b981',
  Carol: '#f59e0b',
  David: '#ef4444',
};

const FALLBACK_COLORS = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#f97316',
  '#ec4899',
];

function getSpeakerColor(speaker: string, index: number): string {
  if (SPEAKER_COLORS[speaker]) return SPEAKER_COLORS[speaker];
  return FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// Group consecutive segments from the same speaker
interface SpeakerGroup {
  speaker: string;
  color: string;
  initials: string;
  segments: TranscriptSegment[];
}

function groupSegments(
  segments: TranscriptSegment[],
  speakerColorMap: Map<string, string>
): SpeakerGroup[] {
  const groups: SpeakerGroup[] = [];

  for (const seg of segments) {
    const color = speakerColorMap.get(seg.speaker) ?? '#6366f1';
    const last = groups[groups.length - 1];

    if (last && last.speaker === seg.speaker) {
      last.segments.push(seg);
    } else {
      const initials = seg.speaker
        .split(' ')
        .map((w) => w[0])
        .join('')
        .toUpperCase()
        .slice(0, 2);
      groups.push({ speaker: seg.speaker, color, initials, segments: [seg] });
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

export const TranscriptPanel: React.FC<TranscriptPanelProps> = ({
  segments,
  isLive = false,
  interimSegment = null,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Build speaker -> color map (stable across renders)
  // Include the interim speaker so their color is consistent
  const speakerColorMap = useMemo(() => {
    const map = new Map<string, string>();
    let colorIdx = 0;
    const allSegments = interimSegment
      ? [...segments, interimSegment]
      : segments;
    for (const seg of allSegments) {
      if (!map.has(seg.speaker)) {
        map.set(seg.speaker, getSpeakerColor(seg.speaker, colorIdx));
        colorIdx++;
      }
    }
    return map;
  }, [segments, interimSegment]);

  const groups = useMemo(
    () => groupSegments(segments, speakerColorMap),
    [segments, speakerColorMap]
  );

  // Auto-scroll to bottom whenever segments or interim change
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
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

  // Build interim group if we have an interim segment
  const interimGroup: SpeakerGroup | null = interimSegment
    ? (() => {
        const color = speakerColorMap.get(interimSegment.speaker) ?? '#6366f1';
        const initials = interimSegment.speaker
          .split(' ')
          .map((w) => w[0])
          .join('')
          .toUpperCase()
          .slice(0, 2);
        return { speaker: interimSegment.speaker, color, initials, segments: [interimSegment] };
      })()
    : null;

  return (
    <div className="transcript-panel" ref={containerRef}>
      <div className="transcript-panel__inner">
        {groups.map((group, groupIdx) => (
          <div
            key={`${group.speaker}-${groupIdx}`}
            className="transcript-group transcript-group--enter"
          >
            <div className="transcript-group__avatar" style={{ backgroundColor: group.color }}>
              {group.initials}
            </div>
            <div className="transcript-group__content">
              <div className="transcript-group__header">
                <span className="transcript-group__speaker" style={{ color: group.color }}>
                  {group.speaker}
                </span>
                <span className="transcript-group__time">
                  {formatTimestamp(group.segments[0].timestamp)}
                </span>
              </div>
              {group.segments.map((seg) => (
                <p key={seg.id} className="transcript-group__text">
                  {seg.text}
                </p>
              ))}
            </div>
          </div>
        ))}

        {/* Interim (ghost) segment */}
        {interimGroup && (
          <div className="transcript-group transcript-group--enter interim">
            <div
              className="transcript-group__avatar"
              style={{ backgroundColor: interimGroup.color }}
            >
              {interimGroup.initials}
            </div>
            <div className="transcript-group__content">
              <div className="transcript-group__header">
                <span
                  className="transcript-group__speaker"
                  style={{ color: interimGroup.color }}
                >
                  {interimGroup.speaker}
                </span>
                <span className="transcript-group__time">
                  {formatTimestamp(interimGroup.segments[0].timestamp)}
                </span>
              </div>
              {interimGroup.segments.map((seg) => (
                <p key={seg.id} className="transcript-group__text">
                  {seg.text}
                  <InterimDots />
                </p>
              ))}
            </div>
          </div>
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
