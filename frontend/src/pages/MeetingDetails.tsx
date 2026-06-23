import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Calendar, Clock, MessageSquare, Sparkles, Loader2, AlertCircle } from 'lucide-react';
import { format, parseISO, differenceInSeconds } from 'date-fns';
import { Layout } from '../components/Layout';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { MeetingStatusBadge } from '../components/StatusBadge';
import { getMeeting, getTranscript } from '../services/api';
import type { Meeting, TranscriptSegment } from '../types';

function formatDuration(startedAt: string, endedAt?: string): string {
  const start = parseISO(startedAt);
  const end = endedAt ? parseISO(endedAt) : new Date();
  const totalSeconds = differenceInSeconds(end, start);

  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;

  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export const MeetingDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const meetingId = id ?? '';

  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!meetingId) return;

    setIsLoading(true);
    Promise.all([getMeeting(meetingId), getTranscript(meetingId)])
      .then(([meetingData, transcriptData]) => {
        setMeeting(meetingData);
        setSegments(transcriptData);
        setError(null);
      })
      .catch((err) => {
        console.error('[MeetingDetails] Failed to load:', err);
        setError('Could not load meeting details. Check that the backend is running.');
      })
      .finally(() => setIsLoading(false));
  }, [meetingId]);

  if (isLoading) {
    return (
      <Layout>
        <div className="loading-state loading-state--page">
          <Loader2 size={32} className="spin" />
          <span>Loading meeting details...</span>
        </div>
      </Layout>
    );
  }

  if (error || !meeting) {
    return (
      <Layout>
        <div className="error-state">
          <AlertCircle size={32} />
          <h2>Could not load meeting</h2>
          <p>{error ?? 'Meeting not found.'}</p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Back to Dashboard
          </button>
        </div>
      </Layout>
    );
  }

  let formattedDate = '';
  try {
    formattedDate = format(parseISO(meeting.started_at), 'EEEE, MMMM d, yyyy · h:mm a');
  } catch {
    formattedDate = meeting.started_at;
  }

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

          {/* AI Insights placeholder */}
          <aside className="meeting-details__insights">
            <div className="insights-card">
              <div className="insights-card__header">
                <Sparkles size={18} />
                <h3 className="insights-card__title">AI Insights</h3>
              </div>
              <div className="insights-card__placeholder">
                <div className="insights-card__badge">Phase 3</div>
                <p className="insights-card__desc">
                  AI-generated summaries, action items, and key decisions will appear here
                  once Phase 3 is complete.
                </p>
                <div className="insights-card__preview">
                  <div className="insights-skeleton" />
                  <div className="insights-skeleton insights-skeleton--short" />
                  <div className="insights-skeleton" />
                  <div className="insights-skeleton insights-skeleton--shorter" />
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
};
