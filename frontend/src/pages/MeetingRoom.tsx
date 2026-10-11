import React, { useState, useEffect, useMemo } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { AlertCircle, FlaskConical, Loader2, MicOff, RotateCw, Square } from 'lucide-react';
import { Layout } from '../components/Layout';
import { LevelTrace } from '../components/LevelTrace';
import { SpeakerShare } from '../components/SpeakerShare';
import { StatusBadge } from '../components/StatusBadge';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useMeetingSocket, type UseMeetingSocketResult } from '../hooks/useMeetingSocket';
import { useMicrophone, type UseMicrophoneResult } from '../hooks/useMicrophone';
import { useRequest } from '../hooks/useRequest';
import { getMeeting, endMeeting } from '../services/api';
import { getApiErrorMessage, getErrorStatus } from '../services/errors';
import { formatClock } from '../utils/format';
import { summarizeSpeakers } from '../utils/speakers';
import './MeetingRoom.css';

const DEMO_MODE_EXPLANATION =
  'This server has no speech-to-text provider, so it plays a scripted sample meeting. ' +
  'Your microphone isn’t transcribed in this mode.';

/** Time since `since`, re-rendering only itself once per second. */
const ElapsedTime: React.FC<{ since: string }> = ({ since }) => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  return <>{formatClock((now - new Date(since).getTime()) / 1000, { padMinutes: true })}</>;
};

type MicState = 'off' | 'waiting' | 'recording' | 'paused' | 'error';

function describeMic(
  mic: Pick<UseMicrophoneResult, 'status' | 'error'>,
  stream: Pick<UseMeetingSocketResult, 'status' | 'sessionId' | 'streamComplete'>,
): { state: MicState; text: string } {
  switch (mic.status) {
    case 'requesting':
      return { state: 'waiting', text: 'Waiting for microphone permission…' };
    case 'active':
      if (stream.streamComplete) return { state: 'paused', text: 'Microphone on, transcription finished' };
      if (stream.sessionId !== null) return { state: 'recording', text: 'Recording' };
      if (stream.status === 'stopping') return { state: 'paused', text: 'Finishing the transcript…' };
      return { state: 'paused', text: 'Recording paused until the connection is back…' };
    case 'denied':
    case 'error':
    case 'unsupported':
      return { state: 'error', text: mic.error ?? 'The microphone isn’t available.' };
    case 'idle':
      return { state: 'off', text: 'Microphone off' };
  }
}

function describeEmptyTranscript(
  mic: Pick<UseMicrophoneResult, 'status'>,
  stream: Pick<UseMeetingSocketResult, 'status' | 'mode'>,
): string {
  if (stream.status === 'failed') return 'Nothing was transcribed. Reconnect to try again.';
  if (stream.mode === 'mock') return 'The sample meeting starts in a moment…';
  if (stream.status !== 'connected') return 'Connecting to the transcription server…';
  if (mic.status === 'active') return 'Listening. Lines appear here a moment after someone speaks.';
  if (mic.status === 'requesting') return 'Allow microphone access to start transcribing.';
  return 'Start recording, and the transcript appears here as people speak.';
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
  const speakers = useMemo(() => summarizeSpeakers(segments), [segments]);

  const isRecording = mic.status === 'active';
  const meetingTitle = meetingRequest.status === 'success' ? meetingRequest.data.title : null;
  useDocumentTitle(meetingTitle && isRecording ? `${meetingTitle} (recording)` : meetingTitle);

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
          getApiErrorMessage(error, { fallback: 'Couldn’t end the meeting. Try again in a moment.' }),
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
        <div className="page-state page-state--loading" role="status">
          <Loader2 size={20} className="spin" aria-hidden="true" />
          Loading the meeting…
        </div>
      </Layout>
    );
  }

  if (meetingRequest.status === 'error') {
    return (
      <Layout activeMeetingId={meetingId}>
        <div className="page-state">
          <h1>Couldn’t open this meeting</h1>
          <p>
            {getApiErrorMessage(meetingRequest.error, {
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

  const meeting = meetingRequest.data;
  const isDemo = stream.mode === 'mock';
  const micState = describeMic(mic, stream);
  const listening =
    connectionStatus === 'connected' &&
    !stream.streamComplete &&
    (isDemo || (isRecording && stream.sessionId !== null));

  return (
    <Layout activeMeetingId={meetingId} fill>
      <div className="room">
        <header className="room__head">
          <h1 className="room__title">{meeting.title}</h1>
          <div className="room__meta">
            <p className="room__clock">
              <span className="room__clock-label">Elapsed</span>{' '}
              <ElapsedTime since={meeting.started_at} />
            </p>
            {isDemo && (
              <span className="tag room__demo-tag">
                <FlaskConical size={14} aria-hidden="true" />
                Demo mode
              </span>
            )}
          </div>
          {isDemo && <p className="room__demo-note">{DEMO_MODE_EXPLANATION}</p>}
        </header>

        <aside className="room__rail" aria-label="Recording">
          <section className="rail-block rail-block--record">
            {mic.status === 'unsupported' ? (
              <div className="notice notice--warn">
                <MicOff size={18} aria-hidden="true" />
                <p className="notice__body">{mic.error}</p>
              </div>
            ) : (
              <>
                <p
                  className="mic-state"
                  data-state={micState.state}
                  role={micState.state === 'error' ? 'alert' : 'status'}
                >
                  <span className="mic-state__mark" aria-hidden="true" />
                  <span>{micState.text}</span>
                </p>
                {isRecording && <LevelTrace level={mic.level} />}
                <button
                  type="button"
                  className={`button button--block ${
                    isRecording ? 'button--secondary' : 'button--primary'
                  }`}
                  onClick={() => void handleMicToggle()}
                  disabled={connectionStatus === 'stopping' || isEnding}
                >
                  {isRecording ? (
                    <>
                      <Square size={14} fill="currentColor" aria-hidden="true" />
                      Stop recording
                    </>
                  ) : mic.status === 'requesting' ? (
                    'Cancel'
                  ) : (
                    <>
                      <span className="record-dot" aria-hidden="true" />
                      Start recording
                    </>
                  )}
                </button>
              </>
            )}
          </section>

          <section className="rail-block rail-block--stream">
            <p className="rail-row">
              <span className="rail-label">Transcript</span>
              <StatusBadge status={connectionStatus} complete={stream.streamComplete} />
            </p>
            <StreamNotice stream={stream} onViewMeeting={() => navigate(`/meeting/${meetingId}`)} />
          </section>

          {speakers.length > 0 && (
            <section className="rail-block rail-block--speakers" aria-labelledby="room-speakers">
              <h2 className="rail-label" id="room-speakers">
                Speakers
              </h2>
              <SpeakerShare speakers={speakers} />
            </section>
          )}

          <section className="rail-block rail-block--end">
            {endError && (
              <div className="notice notice--danger" role="alert">
                <AlertCircle size={18} aria-hidden="true" />
                <p className="notice__body">{endError}</p>
              </div>
            )}
            <button
              type="button"
              className="button button--secondary button--block"
              onClick={() => void handleEndMeeting()}
              disabled={isEnding}
              aria-describedby="end-meeting-hint"
            >
              {isEnding ? (
                <>
                  <Loader2 size={16} className="spin" aria-hidden="true" />
                  Ending…
                </>
              ) : (
                'End meeting'
              )}
            </button>
            <p className="rail-note" id="end-meeting-hint">
              Stops recording and saves the transcript.
            </p>
          </section>
        </aside>

        <div className="room__transcript">
          <TranscriptPanel
            variant="live"
            segments={segments}
            interimSegment={interim}
            isLive={!sessionOver && !stream.streamComplete}
            listening={listening}
            emptyMessage={describeEmptyTranscript(mic, stream)}
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

/** Connection problems and end-of-stream notes, next to the stream status. */
const StreamNotice: React.FC<StreamNoticeProps> = ({ stream, onViewMeeting }) => {
  if (stream.status === 'reconnecting') {
    const { reconnect } = stream;
    const attempt = reconnect ? `, attempt ${reconnect.attempt} of ${reconnect.maxAttempts}` : '';
    return (
      <div className="notice notice--warn" role="status">
        <RotateCw size={18} className="spin" aria-hidden="true" />
        <div className="notice__body">
          <p>
            {stream.error?.message ?? 'Connection lost.'} Reconnecting{attempt}…
          </p>
          <p className="notice__hint">Lines already transcribed stay here.</p>
        </div>
      </div>
    );
  }

  if (stream.status === 'failed') {
    return (
      <div className="notice notice--danger" role="alert">
        <AlertCircle size={18} aria-hidden="true" />
        <div className="notice__body">
          <p>{stream.error?.message ?? 'Lost the connection to the transcription server.'}</p>
          <div className="notice__actions">
            {stream.error?.code === 'meeting_ended' ? (
              <button type="button" className="button button--secondary button--small" onClick={onViewMeeting}>
                View meeting
              </button>
            ) : (
              <button type="button" className="button button--secondary button--small" onClick={stream.connect}>
                Reconnect
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (stream.streamComplete) {
    return (
      <p className="rail-note" role="status">
        {stream.mode === 'mock'
          ? 'The sample meeting has finished. End the meeting to see the saved transcript.'
          : 'Transcription finished. Start recording to continue in a new session.'}
      </p>
    );
  }

  return null;
};
