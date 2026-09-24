import { useEffect, useState, useSyncExternalStore } from 'react';
import { MicrophoneCapture, type MicrophoneSnapshot } from '../services/microphone';

interface UseMicrophoneOptions {
  /**
   * The live transcription session audio should go to, or null while there is
   * none. Each new id starts a fresh MediaRecorder on the same microphone.
   */
  sessionId: number | null;
  onChunk: (chunk: Blob) => void;
}

export interface UseMicrophoneResult extends MicrophoneSnapshot {
  start: () => Promise<void>;
  /** Delivers the final chunk to the current session, then releases the microphone. */
  stop: () => Promise<void>;
}

export function useMicrophone({ sessionId, onChunk }: UseMicrophoneOptions): UseMicrophoneResult {
  const [capture] = useState(() => new MicrophoneCapture());
  const snapshot = useSyncExternalStore(capture.subscribe, capture.getSnapshot);

  useEffect(() => {
    capture.setSession(sessionId, onChunk);
  }, [capture, sessionId, onChunk]);

  useEffect(() => {
    return () => {
      void capture.stop();
    };
  }, [capture]);

  return { ...snapshot, start: capture.start, stop: capture.stop };
}
