import React, { useState } from 'react';
import { X } from 'lucide-react';
import { useApiHealth } from '../hooks/useApiHealth';

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
    <div className="offline-banner">
      <div className="alert alert--info" role="status">
        <span>
          The live demo&rsquo;s server is offline right now, so meetings can&rsquo;t load and live
          transcription can&rsquo;t connect. The source code, tests and screenshots are on{' '}
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
          .
        </span>
        <button
          type="button"
          className="offline-banner__dismiss"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss offline notice"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};
