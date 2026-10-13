import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Square, Clock, Loader2, AlertCircle, Mic, MicOff, FlaskConical } from 'lucide-react';
import { Layout } from '../components/Layout';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { StatusBadge } from '../components/StatusBadge';
import { useMeetingSocket, type UseMeetingSocketResult } from '../hooks/useMeetingSocket';
import { useMicrophone, type UseMicrophoneResult } from '../hooks/useMicrophone';
import { useRequest } from '../hooks/useRequest';
import { getMeeting, endMeeting } from '../services/api';
import { getApiErrorMessage, getErrorStatus } from '../services/errors';
import { formatClock } from '../utils/format';

const DEMO_MODE_EXPLANATION =
  'The server has no speech-to-text provider configured, so it streams a scripted sample ' +
  'meeting. Microphone audio is not transcribed in this mode.';

/** Time since `since`, re-rendering only itself once per second. */
const ElapsedTime: React.FC<{ since: string }> = ({ since }) => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  return <>{formatClock((now - new Date(since).getTime()) / 1000, { padMinutes: true })}</>;
};

function describeMicState(
  mic: Pick<UseMicrophoneResult, 'status' | 'error'>,
  stream: Pick<UseMeetingSocketResult, 'status' | 'sessionId'>,
): string {
  switch (mic.status) {
    case 'requesting':
      return 'Waiting for microphone permission...';
    case 'active':
      if (stream.sessionId !== null) return 'Recording...';
      if (stream.status === 'stopping') return 'Finishing transcript...';
      return 'Recording paused, waiting for the connection...';
    case 'denied':
    case 'error':
    case 'unsupported':
      return mic.error ?? 'Microphone unavailable.';
    case 'idle':
      return 'Click to start recording';
  }
}

export const MeetingRoom: React.FC = () => {
  const { id = '' } = useParams<{ id: string }>();
  // Keyed so the stream, microphone and transcript start fresh for each meeting.
  return <MeetingRoomView key={id} meetingId={id} />;
};

const MeetingRoomView: React.FC<{ meetingId: string }> = ({ meetingId }) => {
  const navigate = useNavigate();
  const meetingRequest = useRequest(meetingId, getMeeting);
  const [isEnding, setIsEnding] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  const stream = useMeetingSocket(meetingId);
  const { segments, interim, status: connectionStatus } = stream;
  const mic = useMicrophone({ sessionId: stream.sessionId, onChunk: stream.sendAudio });

  // Release the microphone once the session can no longer take audio.
  const sessionOver = connectionStatus === 'stopped' || connectionStatus === 'failed';
  const stopMic = mic.stop;
  useEffect(() => {
    if (sessionOver) void stopMic();
  }, [sessionOver, stopMic]);

  const handleEndMeeting = async () => {
    if (isEnding) return;
    setIsEnding(true);
    setEndError(null);

    // Deliver the last audio chunk, then let the server flush the transcript.
    await mic.stop();
    await stream.stop();
    try {
      await endMeeting(meetingId);
    } catch (error) {
      // 409 means it was already ended (e.g. from another tab), which is fine.
      if (getErrorStatus(error) !== 409) {
        setEndError(
          getApiErrorMessage(error, { fallback: 'Could not end the meeting. Please try again.' }),
        );
        setIsEnding(false);
        return;
      }
    }
    navigate(`/meeting/${meetingId}`);
  };

  const handleMicToggle = async () => {
    if (mic.status === 'active' || mic.status === 'requesting') {
      await mic.stop();
      await stream.stop();
      return;
    }
    if (stream.streamComplete) {
      // This session's transcription source has finished; new audio needs a new session.
      await stream.stop();
    }
    stream.connect();
    await mic.start();
  };

  if (meetingRequest.status === 'loading') {
    return (
      <Layout activeMeetingId={meetingId}>
        <div className="loading-state loading-state--page">
          <Loader2 size={32} className="spin" />
          <span>Loading meeting...</span>
        </div>
      </Layout>
    );
  }

  if (meetingRequest.status === 'error') {
    return (
      <Layout activeMeetingId={meetingId}>
        <div className="error-state">
          <AlertCircle size={32} />
          <h2>Could not load meeting</h2>
          <p>
            {getApiErrorMessage(meetingRequest.error, {
              fallback: 'Could not load the meeting. Please try again.',
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

  const meeting = meetingRequest.data;
  const isRecording = mic.status === 'active';
  const micStatusText = describeMicState(mic, stream);

  return (
    <Layout activeMeetingId={meetingId}>
      <div className="meeting-room">
        {/* Top bar */}
        <div className="meeting-room__topbar">
          <div className="meeting-room__info">
            <h1 className="meeting-room__title">{meeting.title}</h1>
            <div className="meeting-room__meta">
              <span className="meeting-room__timer">
                <Clock size={14} />
                <ElapsedTime since={meeting.started_at} />
              </span>
              <StatusBadge status={connectionStatus} />
              {stream.mode === 'mock' && (
                <span className="demo-badge" title={DEMO_MODE_EXPLANATION}>
                  <FlaskConical size={12} aria-hidden="true" />
                  Demo mode — simulated transcript
                </span>
              )}
            </div>
          </div>

          <div className="meeting-room__controls">
            <span className="meeting-room__segment-count">
              {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
            </span>
            <button
              className="btn btn--danger"
              onClick={() => void handleEndMeeting()}
              disabled={isEnding}
            >
              {isEnding ? (
                <>
                  <Loader2 size={15} className="spin" />
                  Ending...
                </>
              ) : (
                <>
                  <Square size={14} />
                  End Meeting
                </>
              )}
            </button>
          </div>
        </div>

        {endError && (
          <div className="alert alert--error" role="alert">
            <AlertCircle size={16} />
            {endError}
          </div>
        )}

        {/* Microphone control section */}
        <div className="mic-section">
          {mic.status === 'unsupported' ? (
            <div className="alert alert--warning">
              <MicOff size={16} />
              {mic.error}
            </div>
          ) : (
            <div className="mic-controls">
              <button
                className={`mic-btn${isRecording ? ' recording' : ''}`}
                onClick={() => void handleMicToggle()}
                disabled={connectionStatus === 'stopping' || isEnding}
                aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                title={micStatusText}
              >
                {isRecording ? <MicOff size={22} /> : <Mic size={22} />}
              </button>

              <div className="mic-info">
                <div className="audio-level-bar">
                  <div className="audio-level-fill" style={{ width: `${mic.level}%` }} />
                </div>
                <span
                  className={`mic-status-text${mic.error ? ' mic-status-text--error' : ''}`}
                  role={mic.error ? 'alert' : undefined}
                >
                  {micStatusText}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Transcript area */}
        <div className="meeting-room__transcript-wrapper">
          <div className="meeting-room__transcript-header">
            <h2 className="meeting-room__transcript-title">Live Transcript</h2>
            <StreamNotice stream={stream} onViewMeeting={() => navigate(`/meeting/${meetingId}`)} />
          </div>
          <TranscriptPanel
            segments={segments}
            isLive={!sessionOver && !stream.streamComplete}
            interimSegment={interim}
          />
        </div>
      </div>
    </Layout>
  );
};

interface StreamNoticeProps {
  stream: UseMeetingSocketResult;
  onViewMeeting: () => void;
}

/** Connection problems and end-of-stream notes shown above the transcript. */
const StreamNotice: React.FC<StreamNoticeProps> = ({ stream, onViewMeeting }) => {
  if (stream.status === 'reconnecting') {
    const { reconnect } = stream;
    const attempt = reconnect ? ` (attempt ${reconnect.attempt} of ${reconnect.maxAttempts})` : '';
    return (
      <div className="alert alert--warning alert--inline" role="status">
        {stream.error?.message ?? 'Connection lost.'} Reconnecting{attempt}...
      </div>
    );
  }

  if (stream.status === 'failed') {
    return (
      <div className="alert alert--error alert--inline" role="alert">
        {stream.error?.message ?? 'Lost the connection to the transcription server.'}
        {stream.error?.code === 'meeting_ended' ? (
          <button className="btn btn--ghost btn--sm" onClick={onViewMeeting}>
            View meeting
          </button>
        ) : (
          <button className="btn btn--ghost btn--sm" onClick={stream.connect}>
            Retry
          </button>
        )}
      </div>
    );
  }

  if (stream.streamComplete) {
    return (
      <span className="meeting-room__stream-note" role="status">
        {stream.mode === 'mock'
          ? 'Simulated transcript complete.'
          : 'Transcription finished. Start recording to begin a new session.'}
      </span>
    );
  }

  return null;
};
