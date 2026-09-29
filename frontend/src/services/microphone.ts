import type { MicrophoneStatus } from '../types';

/** MediaRecorder emits a chunk this often. */
export const TIMESLICE_MS = 250;
/** Refresh rate of the input level meter (the CSS transition smooths the steps). */
const LEVEL_INTERVAL_MS = 100;
/** Upper bound on waiting for MediaRecorder to deliver its final chunk. */
const FLUSH_TIMEOUT_MS = 1_000;

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
];

export interface MicrophoneSnapshot {
  status: MicrophoneStatus;
  /** What went wrong, phrased for the user; set for denied/error/unsupported. */
  error: string | null;
  /** Input level from 0 to 100 while active. */
  level: number;
}

export function isRecordingSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined'
  );
}

/** Maps getUserMedia failures to a status and an actionable message. */
export function describeMicrophoneError(error: unknown): {
  status: 'denied' | 'error';
  message: string;
} {
  const name = error instanceof Error || error instanceof DOMException ? error.name : '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return {
        status: 'denied',
        message:
          'Microphone access is blocked. Allow microphone access for this site in your browser settings, then try again.',
      };
    case 'NotFoundError':
    case 'OverconstrainedError':
      return { status: 'error', message: 'No microphone was found. Connect one and try again.' };
    case 'NotReadableError':
    case 'AbortError':
      return {
        status: 'error',
        message: 'The microphone could not be started. It may be in use by another application.',
      };
    default:
      return { status: 'error', message: 'Could not start the microphone. Please try again.' };
  }
}

const stopTracks = (stream: MediaStream) => stream.getTracks().forEach((track) => track.stop());

/**
 * Microphone capture for live transcription.
 *
 * The device is acquired once per recording, but every transcription session
 * gets its own MediaRecorder: only the first chunk of a recording carries the
 * WebM/Ogg header, so a server session that starts mid-recording could not
 * decode anything. State is exposed through subscribe/getSnapshot for
 * useSyncExternalStore.
 */
export class MicrophoneCapture {
  private snapshot: MicrophoneSnapshot;
  private readonly listeners = new Set<() => void>();

  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private sessionId: number | null = null;
  private sink: ((chunk: Blob) => void) | null = null;
  private audioContext: AudioContext | null = null;
  private levelTimer: ReturnType<typeof setInterval> | null = null;
  /** Bumped by stop() so that a permission request still in flight is discarded. */
  private generation = 0;

  constructor() {
    this.snapshot = isRecordingSupported()
      ? { status: 'idle', error: null, level: 0 }
      : {
          status: 'unsupported',
          error: 'Recording needs a browser with microphone support, served over HTTPS.',
          level: 0,
        };
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): MicrophoneSnapshot => this.snapshot;

  /** Asks for the microphone. Audio is recorded whenever a session is attached. */
  start = async (): Promise<void> => {
    const { status } = this.snapshot;
    if (status === 'unsupported' || status === 'requesting' || status === 'active') return;

    const generation = ++this.generation;
    this.update({ status: 'requesting', error: null });

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      if (generation === this.generation) {
        const { status: failure, message } = describeMicrophoneError(error);
        this.update({ status: failure, error: message });
      }
      return;
    }

    if (generation !== this.generation) {
      // stop() was called while the permission prompt was open.
      stopTracks(stream);
      return;
    }

    this.stream = stream;
    stream.getAudioTracks().forEach((track) => {
      track.addEventListener('ended', () => this.fail('The microphone was disconnected.'));
    });
    this.startLevelMeter(stream);
    this.update({ status: 'active' });
    this.startRecorder();
  };

  /**
   * Routes audio to a transcription session, or pauses capture when
   * `sessionId` is null. A new session id always starts a new recording.
   */
  setSession = (sessionId: number | null, sink: (chunk: Blob) => void): void => {
    this.sink = sink;
    if (sessionId === this.sessionId) return;
    this.sessionId = sessionId;
    this.discardRecorder();
    this.startRecorder();
  };

  /** Stops recording after delivering the final chunk, then releases the microphone. */
  stop = async (): Promise<void> => {
    this.generation += 1;
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder && recorder.state !== 'inactive') {
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(resolve, FLUSH_TIMEOUT_MS);
        // The last dataavailable event fires before "stop".
        const onStop = () => {
          clearTimeout(timeout);
          resolve();
        };
        recorder.addEventListener('stop', onStop, { once: true });
        recorder.stop();
      });
    }
    this.release();
    if (this.snapshot.status !== 'unsupported') {
      this.update({ status: 'idle', error: null, level: 0 });
    }
  };

  private startRecorder(): void {
    const stream = this.stream;
    if (!stream || this.sessionId === null || this.recorder) return;

    try {
      const mimeType = PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) this.sink?.(event.data);
      };
      recorder.onerror = () => this.fail('Recording stopped unexpectedly. Start it again to continue.');
      recorder.start(TIMESLICE_MS);
      this.recorder = recorder;
    } catch {
      this.fail('Recording could not be started in this browser.');
    }
  }

  /** Stops the current recorder without delivering its remaining audio. */
  private discardRecorder(): void {
    const recorder = this.recorder;
    this.recorder = null;
    if (!recorder) return;
    // Anything still buffered belongs to a session that has ended.
    recorder.ondataavailable = null;
    recorder.onerror = null;
    if (recorder.state !== 'inactive') recorder.stop();
  }

  private fail(message: string): void {
    this.generation += 1;
    this.release();
    this.update({ status: 'error', error: message, level: 0 });
  }

  private release(): void {
    this.discardRecorder();
    this.stopLevelMeter();
    if (this.stream) {
      stopTracks(this.stream);
      this.stream = null;
    }
  }

  private startLevelMeter(stream: MediaStream): void {
    if (typeof AudioContext === 'undefined') return;
    try {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.6;
      context.createMediaStreamSource(stream).connect(analyser);
      const bins = new Uint8Array(analyser.frequencyBinCount);

      this.audioContext = context;
      this.levelTimer = setInterval(() => {
        analyser.getByteFrequencyData(bins);
        let sumOfSquares = 0;
        for (const value of bins) sumOfSquares += value * value;
        const rms = Math.sqrt(sumOfSquares / bins.length);
        this.update({ level: Math.min(100, Math.round((rms / 128) * 100)) });
      }, LEVEL_INTERVAL_MS);
    } catch {
      // The level meter is cosmetic; recording works without it.
    }
  }

  private stopLevelMeter(): void {
    if (this.levelTimer !== null) clearInterval(this.levelTimer);
    this.levelTimer = null;
    this.audioContext?.close().catch(() => undefined);
    this.audioContext = null;
  }

  private update(patch: Partial<MicrophoneSnapshot>): void {
    const keys = Object.keys(patch) as Array<keyof MicrophoneSnapshot>;
    if (keys.every((key) => Object.is(this.snapshot[key], patch[key]))) return;
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }
}
