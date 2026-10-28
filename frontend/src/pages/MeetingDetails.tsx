import React, { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { InsightsPanel } from '../components/InsightsPanel';
import { Layout } from '../components/Layout';
import { SpeakerShare } from '../components/SpeakerShare';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useRequest } from '../hooks/useRequest';
import { getMeeting, getTranscript } from '../services/api';
import { getApiErrorMessage } from '../services/errors';
import { formatDuration, formatLongDateTime } from '../utils/format';
import { summarizeSpeakers } from '../utils/speakers';
import './MeetingDetails.css';

const loadMeetingDetails = (meetingId: string) =>
  Promise.all([getMeeting(meetingId), getTranscript(meetingId)]);

export const MeetingDetails: React.FC = () => {
  const { id = '' } = useParams<{ id: string }>();
  // Keyed so that every piece of per-meeting state starts fresh when the id changes.
  return <MeetingDetailsView key={id} meetingId={id} />;
};

const MeetingDetailsView: React.FC<{ meetingId: string }> = ({ meetingId }) => {
  const details = useRequest(meetingId, loadMeetingDetails);
  const segments = details.status === 'success' ? details.data[1] : null;
  const speakers = useMemo(() => (segments ? summarizeSpeakers(segments) : []), [segments]);
  useDocumentTitle(details.status === 'success' ? details.data[0].title : 'Meeting');

  if (details.status === 'loading') {
    return (
      <Layout>
        <div className="page-state page-state--loading" role="status">
          <Loader2 size={20} className="spin" aria-hidden="true" />
          Loading the meeting…
        </div>
      </Layout>
    );
  }

  if (details.status === 'error') {
    return (
      <Layout>
        <div className="page-state">
          <h1>Couldn’t open this meeting</h1>
          <p>
            {getApiErrorMessage(details.error, {
              fallback: 'The meeting didn’t load. Check your connection and try again.',
              byStatus: { 404: 'This meeting doesn’t exist. It may have been opened from an old link.' },
            })}
          </p>
          <Link className="button button--primary" to="/">
            Back to meetings
          </Link>
        </div>
      </Layout>
    );
  }

  const [meeting, transcript] = details.data;
  const active = meeting.status === 'active';

  return (
    <Layout activeMeetingId={active ? meeting.id : undefined}>
      <div className="record">
        <div className="record__top">
          <Link className="back-link" to="/">
            <ArrowLeft size={16} aria-hidden="true" />
            All meetings
          </Link>
          <h1>{meeting.title}</h1>
        </div>

        <aside className="record__facts" aria-label="About this meeting">
          <dl className="facts">
            <div className="facts__item">
              <dt>Started</dt>
              <dd>
                <time dateTime={meeting.started_at}>{formatLongDateTime(meeting.started_at)}</time>
              </dd>
            </div>
            <div className="facts__item">
              <dt>Length</dt>
              <dd>{active ? 'Still in progress' : formatDuration(meeting.started_at, meeting.ended_at)}</dd>
            </div>
            <div className="facts__item">
              <dt>Transcript</dt>
              <dd>
                {transcript.length} {transcript.length === 1 ? 'line' : 'lines'}
              </dd>
            </div>
          </dl>

          {speakers.length > 0 && (
            <section className="record__speakers" aria-labelledby="record-speakers">
              <h2 className="rail-label" id="record-speakers">
                Speakers
              </h2>
              <SpeakerShare speakers={speakers} />
            </section>
          )}

          {active && (
            <Link className="button button--primary button--block" to={`/meeting/${meeting.id}/live`}>
              Open the live meeting
            </Link>
          )}
        </aside>

        <div className="record__main">
          <section className="record__section" aria-labelledby="insights-heading">
            <h2 id="insights-heading">Insights</h2>
            <InsightsPanel
              meetingId={meeting.id}
              meetingStatus={meeting.status}
              hasTranscript={transcript.length > 0}
            />
          </section>

          <section className="record__section" aria-labelledby="transcript-heading">
            <h2 id="transcript-heading">Transcript</h2>
            <TranscriptPanel
              segments={transcript}
              emptyMessage="Nothing was transcribed in this meeting."
            />
          </section>
        </div>
      </div>
    </Layout>
  );
};
