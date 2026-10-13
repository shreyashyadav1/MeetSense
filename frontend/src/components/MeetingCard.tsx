import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Video, Clock, ArrowRight } from 'lucide-react';
import type { Meeting } from '../types';
import { formatDateTime, formatDuration } from '../utils/format';
import { MeetingStatusBadge } from './StatusBadge';

interface MeetingCardProps {
  meeting: Meeting;
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

  const formattedDate = formatDateTime(meeting.started_at, 'MMM d, yyyy · h:mm a');

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
