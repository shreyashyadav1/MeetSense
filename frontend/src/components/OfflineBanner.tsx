import React, { useState } from 'react';
import { CloudOff, X } from 'lucide-react';
import { useApiHealth } from '../hooks/useApiHealth';
import './OfflineBanner.css';

const REPO_URL = 'https://github.com/shreyashyadav1/MeetSense';

/**
 * Site-wide notice shown while the public demo's backend is unreachable.
 * Wording covers both a plain data load and a live meeting stream, since a
 * stream failure while this banner is up is usually the same root cause.
 * Pages keep their own error and stream-reconnect states for everything else.
 */
export const OfflineBanner: React.FC = () => {
  const offline = useApiHealth();
  const [dismissed, setDismissed] = useState(false);
  // Tracks whether `dismissed` still applies to the current outage. Updating
  // state during render (rather than in an effect) is the recommended way to
  // reset it the moment a new outage starts: https://react.dev/learn/you-might-not-need-an-effect
  const [wasOffline, setWasOffline] = useState(offline);
  if (offline !== wasOffline) {
    setWasOffline(offline);
    if (offline) setDismissed(false);
  }

  if (!offline || dismissed) return null;

  return (
    <div className="offline-banner" role="status">
      <div className="offline-banner__inner">
        <CloudOff size={18} aria-hidden="true" />
        <p className="offline-banner__text">
          The demo server is offline right now, so meetings can&rsquo;t load and live transcripts
          can&rsquo;t connect. The code, tests and screenshots are on{' '}
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
          .
        </p>
        <button
          type="button"
          className="offline-banner__dismiss"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss offline notice"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};
