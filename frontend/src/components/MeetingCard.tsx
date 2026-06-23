import React from 'react';
import { useNavigate } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { Video, Clock, ArrowRight } from 'lucide-react';
import type { Meeting } from '../types';
import { MeetingStatusBadge } from './StatusBadge';

interface MeetingCardProps {
  meeting: Meeting;
}

function formatDuration(startedAt: string, endedAt?: string): string {
  const start = parseISO(startedAt);
  const end = endedAt ? parseISO(endedAt) : new Date();
  const diffMs = end.getTime() - start.getTime();
  const totalSeconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
  }
  return `${minutes}m ${seconds}s`;
}

export const MeetingCard: React.FC<MeetingCardProps> = ({ meeting }) => {
  const navigate = useNavigate();

  const handleView = () => {
    if (meeting.status === 'active') {
      navigate(`/meeting/${meeting.id}/live`);
    } else {
      navigate(`/meeting/${meeting.id}`);
    }
  };

  let formattedDate = '';
  try {
    formattedDate = format(parseISO(meeting.started_at), 'MMM d, yyyy · h:mm a');
  } catch {
    formattedDate = meeting.started_at;
  }

  return (
    <div className="meeting-card">
      <div className="meeting-card__icon">
        <Video size={20} />
      </div>
      <div className="meeting-card__body">
        <div className="meeting-card__header">
          <h3 className="meeting-card__title">{meeting.title}</h3>
          <MeetingStatusBadge status={meeting.status} />
        </div>
        <div className="meeting-card__meta">
          <span className="meeting-card__date">{formattedDate}</span>
          {meeting.status === 'ended' && (
            <span className="meeting-card__duration">
              <Clock size={12} />
              {formatDuration(meeting.started_at, meeting.ended_at)}
            </span>
          )}
        </div>
      </div>
      <button className="meeting-card__btn" onClick={handleView} aria-label="View meeting">
        {meeting.status === 'active' ? 'Join Live' : 'View'}
        <ArrowRight size={14} />
      </button>
    </div>
  );
};
