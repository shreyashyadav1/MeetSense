import React from 'react';
import type { SpeakerSummary } from '../utils/speakers';
import './SpeakerShare.css';

interface SpeakerShareProps {
  speakers: readonly SpeakerSummary[];
}

/**
 * The meeting's speakers in their voice colors, with each one's share of the
 * words spoken. Doubles as the color key for the transcript.
 */
export const SpeakerShare: React.FC<SpeakerShareProps> = ({ speakers }) => (
  <ul className="speaker-share">
    {speakers.map((speaker) => {
      const percent = Math.round(speaker.share * 100);
      return (
        <li
          key={speaker.speaker || 'unknown'}
          className="speaker-share__item"
          style={{ '--voice': speaker.color } as React.CSSProperties}
        >
          <span className="speaker-share__name">{speaker.label}</span>
          <span className="speaker-share__bar" aria-hidden="true">
            <span style={{ transform: `scaleX(${speaker.share})` }} />
          </span>
          <span className="speaker-share__value">
            {percent}%<span className="visually-hidden"> of words</span>
          </span>
        </li>
      );
    })}
  </ul>
);
