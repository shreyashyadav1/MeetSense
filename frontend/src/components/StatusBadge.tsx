import React from 'react';
import type { ConnectionStatus } from '../types';

interface StatusBadgeProps {
  status: ConnectionStatus;
}

const STATUS_CONFIG: Record<
  ConnectionStatus,
  { label: string; className: string; pulse: boolean }
> = {
  connecting: {
    label: 'Connecting',
    className: 'status-badge status-badge--connecting',
    pulse: false,
  },
  connected: {
    label: 'Live',
    className: 'status-badge status-badge--connected',
    pulse: true,
  },
  disconnected: {
    label: 'Disconnected',
    className: 'status-badge status-badge--disconnected',
    pulse: false,
  },
  error: {
    label: 'Error',
    className: 'status-badge status-badge--error',
    pulse: false,
  },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const config = STATUS_CONFIG[status];

  return (
    <span className={config.className}>
      <span className={`status-dot ${config.pulse ? 'status-dot--pulse' : ''}`} />
      {config.label}
    </span>
  );
};

interface MeetingStatusBadgeProps {
  status: 'active' | 'ended';
}

export const MeetingStatusBadge: React.FC<MeetingStatusBadgeProps> = ({ status }) => {
  return (
    <span className={`meeting-badge meeting-badge--${status}`}>
      {status === 'active' ? 'Active' : 'Ended'}
    </span>
  );
};
