import React from 'react';
import { Link } from 'react-router-dom';
import type { Meeting } from '../types';
import { formatDuration, formatTime } from '../utils/format';

interface MeetingListItemProps {
  meeting: Meeting;
}

/** One meeting in the list: opens the live room while it runs, the saved meeting after. */
export const MeetingListItem: React.FC<MeetingListItemProps> = ({ meeting }) => {
  const active = meeting.status === 'active';
  const href = active ? `/meeting/${meeting.id}/live` : `/meeting/${meeting.id}`;

  return (
    <li>
      <Link className={`meeting-row${active ? ' meeting-row--active' : ''}`} to={href}>
        <span className="meeting-row__title">{meeting.title}</span>
        <span className="meeting-row__time">
          <span className="visually-hidden">Started at </span>
          <time dateTime={meeting.started_at}>{formatTime(meeting.started_at)}</time>
        </span>
        {active ? (
          <span className="meeting-row__status">
            <span className="meeting-row__live-mark" aria-hidden="true" />
            Rejoin
          </span>
        ) : (
          <span className="meeting-row__length">
            <span className="visually-hidden">, lasted </span>
            {formatDuration(meeting.started_at, meeting.ended_at)}
          </span>
        )}
      </Link>
    </li>
  );
};
