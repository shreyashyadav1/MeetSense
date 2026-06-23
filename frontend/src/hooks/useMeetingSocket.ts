import { useEffect, useRef, useState, useCallback } from 'react';
import { MeetingSocket } from '../services/websocket';
import type { TranscriptSegment, WSMessage, ConnectionStatus } from '../types';

interface UseMeetingSocketResult {
  segments: TranscriptSegment[];
  isConnected: boolean;
  connectionStatus: ConnectionStatus;
}

export function useMeetingSocket(meetingId: string): UseMeetingSocketResult {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const socketRef = useRef<MeetingSocket | null>(null);

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'transcript':
        setConnectionStatus('connected');
        setSegments((prev) => {
          if (prev.some((s) => s.id === msg.data.id)) return prev;
          return [...prev, msg.data];
        });
        break;

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

  return {
    segments,
    isConnected: connectionStatus === 'connected',
    connectionStatus,
  };
}
