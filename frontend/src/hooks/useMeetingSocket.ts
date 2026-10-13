import { useEffect, useState, useSyncExternalStore } from 'react';
import { apiHealthMonitor } from '../services/apiHealth';
import { MeetingSocket, meetingStreamUrl, type MeetingSocketSnapshot } from '../services/websocket';

export interface UseMeetingSocketResult extends MeetingSocketSnapshot {
  /** Sends audio when a session is live; chunks are dropped otherwise. */
  sendAudio: (chunk: Blob) => void;
  /** Flushes and ends the server session; resolves when it has closed. */
  stop: () => Promise<void>;
  /** Starts a new session after a stop or failure (the Retry action). No-op while connected. */
  connect: () => void;
}

/**
 * Live transcription stream for a meeting. Connects on mount, follows the
 * reconnect policy in MeetingSocket and disconnects on unmount.
 */
export function useMeetingSocket(meetingId: string): UseMeetingSocketResult {
  const url = meetingStreamUrl(meetingId);
  const [socket, setSocket] = useState(() => new MeetingSocket(url));
  if (socket.url !== url) {
    // Switched meetings: start from a clean client rather than mixing transcripts.
    setSocket(new MeetingSocket(url));
  }

  const snapshot = useSyncExternalStore(socket.subscribe, socket.getSnapshot);

  useEffect(() => {
    socket.connect();
    return socket.disconnect;
  }, [socket]);

  // A stream that starts reconnecting or gives up entirely is a strong signal
  // that the server itself may be unreachable; recheck its health right away
  // instead of waiting for the next scheduled poll, so the offline banner can
  // explain what's going on rather than leaving the failure unexplained.
  const status = snapshot.status;
  useEffect(() => {
    if (status === 'reconnecting' || status === 'failed') {
      apiHealthMonitor.checkNow();
    }
  }, [status]);

  return {
    ...snapshot,
    sendAudio: socket.sendAudio,
    stop: socket.stop,
    connect: socket.connect,
  };
}
