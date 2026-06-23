import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Square, Clock, Loader2, AlertCircle, Mic, MicOff } from 'lucide-react';
import { Layout } from '../components/Layout';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { StatusBadge } from '../components/StatusBadge';
import { useMeetingSocket } from '../hooks/useMeetingSocket';
import { useMicrophone } from '../hooks/useMicrophone';
import { getMeeting, endMeeting } from '../services/api';
import type { Meeting } from '../types';

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

  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;

  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export const MeetingRoom: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const meetingId = id ?? '';

  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [isLoadingMeeting, setIsLoadingMeeting] = useState(true);
  const [meetingError, setMeetingError] = useState<string | null>(null);
  const [isEnding, setIsEnding] = useState(false);

  const { segments, interimSegment, connectionStatus, sendAudio } = useMeetingSocket(meetingId);
  const { status: micStatus, startRecording, stopRecording, audioLevel } = useMicrophone({
    onChunk: sendAudio,
  });

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
    stopRecording();
    try {
      await endMeeting(meetingId);
      navigate(`/meeting/${meetingId}`);
    } catch (err) {
      console.error('[MeetingRoom] Failed to end meeting:', err);
      setIsEnding(false);
    }
  }, [meetingId, isEnding, navigate, stopRecording]);

  const handleMicToggle = useCallback(() => {
    if (micStatus === 'active') {
      stopRecording();
    } else if (micStatus === 'idle' || micStatus === 'error') {
      startRecording();
    }
  }, [micStatus, startRecording, stopRecording]);

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

  let micStatusText = 'Click to start recording';
  if (micStatus === 'requesting') micStatusText = 'Requesting microphone...';
  else if (micStatus === 'active') micStatusText = 'Recording...';
  else if (micStatus === 'error') micStatusText = 'Microphone error — click to retry';
  else if (micStatus === 'unsupported') micStatusText = 'Microphone not supported in this browser';

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
              Microphone not supported in this browser
            </div>
          ) : (
            <div className="mic-controls">
              <button
                className={`mic-btn${isRecording ? ' recording' : ''}`}
                onClick={handleMicToggle}
                disabled={micStatus === 'requesting'}
                aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                title={micStatusText}
              >
                {isRecording ? <MicOff size={22} /> : <Mic size={22} />}
              </button>

              <div className="mic-info">
                <div className="audio-level-bar">
                  <div
                    className="audio-level-fill"
                    style={{ width: `${audioLevel}%` }}
                  />
                </div>
                <span className="mic-status-text">{micStatusText}</span>
              </div>
            </div>
          )}
        </div>

        {/* Transcript area */}
        <div className="meeting-room__transcript-wrapper">
          <div className="meeting-room__transcript-header">
            <h2 className="meeting-room__transcript-title">Live Transcript</h2>
            {connectionStatus === 'error' && (
              <div className="alert alert--error alert--inline">
                WebSocket connection error. Attempting to reconnect...
              </div>
            )}
          </div>
          <TranscriptPanel segments={segments} isLive={true} interimSegment={interimSegment} />
        </div>
      </div>
    </Layout>
  );
};
