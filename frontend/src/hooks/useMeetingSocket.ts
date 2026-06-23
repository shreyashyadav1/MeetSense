import { useEffect, useRef, useState, useCallback } from 'react';
import { MeetingSocket } from '../services/websocket';
import type { TranscriptSegment, WSMessage, ConnectionStatus } from '../types';

interface UseMeetingSocketResult {
  segments: TranscriptSegment[];
  interimSegment: TranscriptSegment | null;
  isConnected: boolean;
  connectionStatus: ConnectionStatus;
  sendAudio: (chunk: Blob) => void;
}

export function useMeetingSocket(meetingId: string): UseMeetingSocketResult {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [interimSegment, setInterimSegment] = useState<TranscriptSegment | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const socketRef = useRef<MeetingSocket | null>(null);

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'transcript': {
        setConnectionStatus('connected');
        const seg = msg.data;

        if (seg.is_final === false) {
          // Interim result — update the in-progress ghost entry
          setInterimSegment(seg);
        } else {
          // Final (or legacy without the flag) — commit to the segment list
          setSegments((prev) => {
            if (prev.some((s) => s.id === seg.id)) return prev;
            return [...prev, seg];
          });
          setInterimSegment(null);
        }
        break;
      }

      case 'status':
        if (msg.data.status === 'connected') {
          setConnectionStatus('connected');
        } else if (msg.data.status === 'ended') {
          setConnectionStatus('disconnected');
        }
        break;

      case 'pong':
        setConnectionStatus('connected');
        break;

      case 'error':
        console.error('[useMeetingSocket] Server error:', msg.data.message);
        setConnectionStatus('error');
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    if (!meetingId) return;

    setConnectionStatus('connecting');
    setSegments([]);
    setInterimSegment(null);

    const socket = new MeetingSocket(meetingId, handleMessage);
    socketRef.current = socket;
    socket.connect();

    // Poll native WebSocket readyState to detect open/close transitions
    const pollTimer = setInterval(() => {
      if (!socketRef.current) return;
      const state = socketRef.current.readyState;
      if (state === WebSocket.OPEN) {
        setConnectionStatus((prev) => (prev === 'connecting' ? 'connected' : prev));
      } else if (state === WebSocket.CLOSED) {
        setConnectionStatus((prev) => (prev === 'connected' ? 'disconnected' : prev));
      }
    }, 500);

    return () => {
      clearInterval(pollTimer);
      socket.disconnect();
      socketRef.current = null;
    };
  }, [meetingId, handleMessage]);

  const sendAudio = useCallback((chunk: Blob) => {
    socketRef.current?.sendBinary(chunk);
  }, []);

  return {
    segments,
    interimSegment,
    isConnected: connectionStatus === 'connected',
    connectionStatus,
    sendAudio,
  };
}
