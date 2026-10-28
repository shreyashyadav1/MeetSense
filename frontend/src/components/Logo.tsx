import React from 'react';

/** The MeetSense mark: three lines of a conversation, each in its speaker's ink. */
export const LogoMark: React.FC<{ size?: number }> = ({ size = 24 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    strokeLinecap="round"
    strokeWidth={4}
    aria-hidden="true"
    focusable="false"
  >
    <path stroke="var(--voice-1)" d="M4 9h16" />
    <path stroke="var(--voice-2)" d="M12 16h16" />
    <path stroke="var(--voice-3)" d="M4 23h11" />
  </svg>
);
