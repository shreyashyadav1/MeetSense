import React from 'react';
import type { ConnectionStatus } from '../types';

interface StatusBadgeProps {
  status: ConnectionStatus;
  /** The transcription source has finished, even though the socket is still open. */
  complete?: boolean;
}

type Tone = 'pending' | 'live' | 'warn' | 'off' | 'error';

const STATUS_CONFIG: Record<ConnectionStatus, { label: string; tone: Tone }> = {
  idle: { label: 'Connecting…', tone: 'pending' },
  connecting: { label: 'Connecting…', tone: 'pending' },
  connected: { label: 'Live', tone: 'live' },
  reconnecting: { label: 'Reconnecting…', tone: 'warn' },
  stopping: { label: 'Finishing…', tone: 'pending' },
  stopped: { label: 'Stopped', tone: 'off' },
  failed: { label: 'Disconnected', tone: 'error' },
};

/** State of the live transcript stream: a small shape plus a word, never color alone. */
export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, complete = false }) => {
  const { label, tone } =
    complete && status === 'connected' ? { label: 'Finished', tone: 'off' } : STATUS_CONFIG[status];

  return (
    <span className="connection-status" data-tone={tone}>
      <span className="connection-status__mark" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
};
