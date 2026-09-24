import React from 'react';
import type { ConnectionStatus, MeetingStatus } from '../types';

interface StatusBadgeProps {
  status: ConnectionStatus;
}

type Tone = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

const STATUS_CONFIG: Record<ConnectionStatus, { label: string; tone: Tone; pulse?: boolean }> = {
  idle: { label: 'Connecting', tone: 'connecting' },
  connecting: { label: 'Connecting', tone: 'connecting' },
  connected: { label: 'Live', tone: 'connected', pulse: true },
  reconnecting: { label: 'Reconnecting', tone: 'disconnected' },
  stopping: { label: 'Finishing', tone: 'idle' },
  stopped: { label: 'Stopped', tone: 'idle' },
  failed: { label: 'Disconnected', tone: 'error' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const { label, tone, pulse } = STATUS_CONFIG[status];

  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span className={`status-dot ${pulse ? 'status-dot--pulse' : ''}`} />
      {label}
    </span>
  );
};

interface MeetingStatusBadgeProps {
  status: MeetingStatus;
}

export const MeetingStatusBadge: React.FC<MeetingStatusBadgeProps> = ({ status }) => {
  return (
    <span className={`meeting-badge meeting-badge--${status}`}>
      {status === 'active' ? 'Active' : 'Ended'}
    </span>
  );
};
