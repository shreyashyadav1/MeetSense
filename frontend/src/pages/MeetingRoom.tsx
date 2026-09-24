import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Square, Clock, Loader2, AlertCircle, Mic, MicOff } from 'lucide-react';
import { Layout } from '../components/Layout';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { StatusBadge } from '../components/StatusBadge';
import { useMeetingSocket, type UseMeetingSocketResult } from '../hooks/useMeetingSocket';
import { useMicrophone, type UseMicrophoneResult } from '../hooks/useMicrophone';
import { getMeeting, endMeeting } from '../services/api';
import type { Meeting } from '../types';
import { formatClock } from '../utils/format';

function useTimer(startedAt: string | undefined): string {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;

    const update = () => {
      const diff = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
      setElapsed(Math.max(0, diff));
    };

    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  return formatClock(elapsed, { padMinutes: true });
}

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
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const meetingId = id ?? '';

  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [isLoadingMeeting, setIsLoadingMeeting] = useState(true);
  const [meetingError, setMeetingError] = useState<string | null>(null);
  const [isEnding, setIsEnding] = useState(false);

  const stream = useMeetingSocket(meetingId);
  const { segments, interim, status: connectionStatus } = stream;
  const mic = useMicrophone({ sessionId: stream.sessionId, onChunk: stream.sendAudio });
  const micStatus = mic.status;

  // Release the microphone once the session can no longer take audio.
  const sessionOver = connectionStatus === 'stopped' || connectionStatus === 'failed';
  const stopMic = mic.stop;
  useEffect(() => {
    if (sessionOver) void stopMic();
  }, [sessionOver, stopMic]);

  const duration = useTimer(meeting?.started_at);

  // Fetch meeting metadata
  useEffect(() => {
    if (!meetingId) return;

    setIsLoadingMeeting(true);
    getMeeting(meetingId)
      .then((data) => {
        setMeeting(data);
        setMeetingError(null);
      })
      .catch((err) => {
        console.error('[MeetingRoom] Failed to load meeting:', err);
        setMeetingError('Could not load meeting. Check that the backend is running.');
      })
      .finally(() => setIsLoadingMeeting(false));
  }, [meetingId]);

  const handleEndMeeting = useCallback(async () => {
    if (!meetingId || isEnding) return;

    setIsEnding(true);
    // Deliver the last audio chunk, then let the server flush the transcript.
    await mic.stop();
    await stream.stop();
    try {
      await endMeeting(meetingId);
      navigate(`/meeting/${meetingId}`);
    } catch (err) {
      console.error('[MeetingRoom] Failed to end meeting:', err);
      setIsEnding(false);
    }
  }, [meetingId, isEnding, navigate, mic, stream]);

  const handleMicToggle = useCallback(async () => {
    if (micStatus === 'active' || micStatus === 'requesting') {
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
  }, [micStatus, mic, stream]);

  if (isLoadingMeeting) {
    return (
      <Layout activeMeetingId={meetingId}>
        <div className="loading-state loading-state--page">
          <Loader2 size={32} className="spin" />
          <span>Loading meeting...</span>
        </div>
      </Layout>
    );
  }

  if (meetingError || !meeting) {
    return (
      <Layout activeMeetingId={meetingId}>
        <div className="error-state">
          <AlertCircle size={32} />
          <h2>Could not load meeting</h2>
          <p>{meetingError ?? 'Meeting not found.'}</p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Back to Dashboard
          </button>
        </div>
      </Layout>
    );
  }

  const isRecording = micStatus === 'active';
  const micUnsupported = micStatus === 'unsupported';
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
                {duration}
              </span>
              <StatusBadge status={connectionStatus} />
            </div>
          </div>

          <div className="meeting-room__controls">
            <span className="meeting-room__segment-count">
              {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
            </span>
            <button
              className="btn btn--danger"
              onClick={handleEndMeeting}
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

        {/* Microphone control section */}
        <div className="mic-section">
          {micUnsupported ? (
            <div className="alert alert--warning">
              <MicOff size={16} />
              {mic.error}
            </div>
          ) : (
            <div className="mic-controls">
              <button
                className={`mic-btn${isRecording ? ' recording' : ''}`}
                onClick={handleMicToggle}
                disabled={connectionStatus === 'stopping'}
                aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                title={micStatusText}
              >
                {isRecording ? <MicOff size={22} /> : <Mic size={22} />}
              </button>

              <div className="mic-info">
                <div className="audio-level-bar">
                  <div
                    className="audio-level-fill"
                    style={{ width: `${mic.level}%` }}
                  />
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
            {connectionStatus === 'reconnecting' && (
              <div className="alert alert--warning alert--inline">
                {stream.error?.message ?? 'Connection lost.'} Reconnecting...
              </div>
            )}
            {connectionStatus === 'failed' && (
              <div className="alert alert--error alert--inline">
                {stream.error?.message ?? 'Lost the connection to the transcription server.'}
                <button className="btn btn--ghost btn--sm" onClick={stream.connect}>
                  Retry
                </button>
              </div>
            )}
          </div>
          <TranscriptPanel segments={segments} isLive={true} interimSegment={interim} />
        </div>
      </div>
    </Layout>
  );
};
