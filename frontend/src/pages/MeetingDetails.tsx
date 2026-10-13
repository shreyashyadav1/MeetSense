import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Calendar, Clock, MessageSquare, Sparkles, Loader2, AlertCircle } from 'lucide-react';
import { Layout } from '../components/Layout';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { MeetingStatusBadge } from '../components/StatusBadge';
import { InsightsPanel } from '../components/InsightsPanel';
import { useRequest } from '../hooks/useRequest';
import { getMeeting, getTranscript } from '../services/api';
import { getApiErrorMessage } from '../services/errors';
import { formatDateTime, formatDuration } from '../utils/format';

const loadMeetingDetails = (meetingId: string) =>
  Promise.all([getMeeting(meetingId), getTranscript(meetingId)]);

export const MeetingDetails: React.FC = () => {
  const { id = '' } = useParams<{ id: string }>();
  // Keyed so that every piece of per-meeting state starts fresh when the id changes.
  return <MeetingDetailsView key={id} meetingId={id} />;
};

const MeetingDetailsView: React.FC<{ meetingId: string }> = ({ meetingId }) => {
  const navigate = useNavigate();
  const details = useRequest(meetingId, loadMeetingDetails);

  if (details.status === 'loading') {
    return (
      <Layout>
        <div className="loading-state loading-state--page">
          <Loader2 size={32} className="spin" />
          <span>Loading meeting details...</span>
        </div>
      </Layout>
    );
  }

  if (details.status === 'error') {
    return (
      <Layout>
        <div className="error-state">
          <AlertCircle size={32} />
          <h2>Could not load meeting</h2>
          <p>
            {getApiErrorMessage(details.error, {
              fallback: 'Could not load meeting details. Please try again.',
              byStatus: { 404: 'This meeting does not exist.' },
            })}
          </p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Back to Dashboard
          </button>
        </div>
      </Layout>
    );
  }

  const [meeting, segments] = details.data;
  const formattedDate = formatDateTime(meeting.started_at, 'EEEE, MMMM d, yyyy · h:mm a');
  const duration = formatDuration(meeting.started_at, meeting.ended_at);

  return (
    <Layout>
      <div className="meeting-details">
        {/* Back button */}
        <button className="back-btn" onClick={() => navigate('/')}>
          <ArrowLeft size={16} />
          Back to Dashboard
        </button>

        {/* Meeting header */}
        <div className="meeting-details__header">
          <div className="meeting-details__title-row">
            <h1 className="meeting-details__title">{meeting.title}</h1>
            <MeetingStatusBadge status={meeting.status} />
          </div>
          <div className="meeting-details__meta">
            <span className="meta-item">
              <Calendar size={14} />
              {formattedDate}
            </span>
            <span className="meta-item">
              <Clock size={14} />
              {duration}
            </span>
            <span className="meta-item">
              <MessageSquare size={14} />
              {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
            </span>
          </div>
        </div>

        <div className="meeting-details__content">
          {/* Transcript */}
          <div className="meeting-details__transcript-section">
            <h2 className="section-title">Transcript</h2>
            <div className="meeting-details__transcript-wrapper">
              <TranscriptPanel segments={segments} isLive={false} />
            </div>
          </div>

          {/* AI Insights */}
          <aside className="meeting-details__insights">
            <div className="insights-card">
              <div className="insights-card__header">
                <Sparkles size={18} />
                <h3 className="insights-card__title">AI Insights</h3>
              </div>
              <div className="insights-card__body">
                <InsightsPanel
                  meetingId={meeting.id}
                  meetingStatus={meeting.status}
                  hasTranscript={segments.length > 0}
                />
              </div>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
};
