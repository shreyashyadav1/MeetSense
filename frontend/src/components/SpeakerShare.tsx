import React from 'react';
import type { SpeakerSummary } from '../utils/speakers';
import './SpeakerShare.css';

const percent = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 0 });

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
            {percent.format(speaker.share)}
            <span className="visually-hidden"> of words</span>
          </span>
        </li>
      );
    })}
  </ul>
);
