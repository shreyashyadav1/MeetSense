import { apiConfig } from '../config';
import type {
  ClientMessage,
  ConnectionStatus,
  LiveSegment,
  StreamError,
  TranscriptionMode,
} from '../types';
import { parseServerMessage } from './protocol';
import { applySegment } from './transcript';

/** Delay before each reconnect attempt; the list length is the retry budget. */
export const RECONNECT_DELAYS_MS: readonly number[] = [1_000, 2_000, 4_000, 8_000, 16_000];
/** A connection that stays open this long is healthy and earns back the retry budget. */
export const STABLE_CONNECTION_MS = 10_000;
/** Ping interval. If nothing at all arrives between two pings the connection is presumed dead. */
export const HEARTBEAT_INTERVAL_MS = 15_000;
/** How long to wait for the server's "stopped" before closing anyway. */
export const STOP_TIMEOUT_MS = 5_000;

const NORMAL_CLOSURE = 1000;

const CONNECTION_LOST: StreamError = {
  code: 'connection_lost',
  message: 'Lost the connection to the transcription server.',
  retryable: true,
};

export interface ReconnectInfo {
  /** 1-based attempt number. */
  attempt: number;
  maxAttempts: number;
  delayMs: number;
}

export interface MeetingSocketSnapshot {
  status: ConnectionStatus;
  /** Transcription source reported by the server; kept across reconnects. */
  mode: TranscriptionMode | null;
  /** Identifies the current server session. Non-null exactly when audio may be sent. */
  sessionId: number | null;
  /** Final segments in sequence order, kept across reconnects. */
  segments: readonly LiveSegment[];
  interim: LiveSegment | null;
  /** The server's transcription source has finished for this session. */
  streamComplete: boolean;
  /** Latest problem worth showing; cleared once a session is established. */
  error: StreamError | null;
  /** Set while waiting to reconnect or while a reconnect attempt is in flight. */
  reconnect: ReconnectInfo | null;
}

const INITIAL_SNAPSHOT: MeetingSocketSnapshot = {
  status: 'idle',
  mode: null,
  sessionId: null,
  segments: [],
  interim: null,
  streamComplete: false,
  error: null,
  reconnect: null,
};

export function meetingStreamUrl(meetingId: string, wsBaseUrl = apiConfig.wsBaseUrl): string {
  return `${wsBaseUrl}/ws/meetings/${encodeURIComponent(meetingId)}/stream`;
}

/**
 * Client for a meeting's live transcription stream.
 *
 * Owns the connection lifecycle (heartbeat, reconnect with exponential
 * backoff, the stop handshake) and the transcript received so far. State is
 * exposed as immutable snapshots through subscribe/getSnapshot, so React can
 * read it with useSyncExternalStore.
 */
export class MeetingSocket {
  readonly url: string;

  private snapshot = INITIAL_SNAPSHOT;
  private readonly listeners = new Set<() => void>();

  private socket: WebSocket | null = null;
  /** Reconnect attempts made since the last healthy connection. */
  private attempts = 0;
  private sessionCount = 0;
  private stopping = false;
  private awaitingPong = false;
  private stopWaiters: Array<() => void> = [];

  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stableTimer: ReturnType<typeof setTimeout> | null = null;
  private stopTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  constructor(url: string) {
    this.url = url;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): MeetingSocketSnapshot => this.snapshot;

  /** Opens the stream, or re-opens it after a stop or failure, with a fresh retry budget. */
  connect = (): void => {
    if (this.socket || this.reconnectTimer) return;
    this.attempts = 0;
    this.update({ error: null, reconnect: null });
    this.open();
  };

  /** Sends an audio chunk if the server has confirmed the session; otherwise drops it. */
  sendAudio = (chunk: Blob): boolean => {
    if (this.snapshot.sessionId === null || !this.socket) return false;
    this.socket.send(chunk);
    return true;
  };

  /**
   * Asks the server to flush the transcript and end the session. Resolves once
   * the server confirms (or after STOP_TIMEOUT_MS). Never reconnects.
   */
  stop = (): Promise<void> => {
    this.cancelReconnect();

    if (this.socket?.readyState !== WebSocket.OPEN) {
      this.finishStop();
      return Promise.resolve();
    }

    const stopped = new Promise<void>((resolve) => this.stopWaiters.push(resolve));
    if (!this.stopping) {
      this.stopping = true;
      this.send({ type: 'stop' });
      this.update({ status: 'stopping', sessionId: null });
      this.stopTimer = setTimeout(() => this.finishStop(), STOP_TIMEOUT_MS);
    }
    return stopped;
  };

  /** Closes immediately without a stop handshake or reconnect (e.g. when leaving the page). */
  disconnect = (): void => {
    this.cancelReconnect();
    this.clearStopTimer();
    this.stopping = false;
    this.releaseSocket();
    this.update({ status: 'idle', sessionId: null, interim: null, reconnect: null });
    this.resolveStopWaiters();
  };

  private open(): void {
    this.stopping = false;
    this.awaitingPong = false;

    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch {
      // Only a malformed URL or a forbidden port throws here, so retrying can't help.
      this.fail({
        code: 'invalid_url',
        message: 'The transcription server address is invalid.',
        retryable: false,
      });
      return;
    }

    this.socket = socket;
    socket.onopen = () => this.handleOpen();
    socket.onmessage = (event: MessageEvent) => this.handleMessage(event);
    socket.onclose = (event: CloseEvent) => this.handleSocketGone(event.code === NORMAL_CLOSURE);
    this.update({ status: this.attempts > 0 ? 'reconnecting' : 'connecting', sessionId: null });
  }

  private handleOpen(): void {
    this.heartbeatTimer = setInterval(() => this.heartbeat(), HEARTBEAT_INTERVAL_MS);
    this.stableTimer = setTimeout(() => this.markHealthy(), STABLE_CONNECTION_MS);
  }

  private handleMessage(event: MessageEvent): void {
    this.awaitingPong = false;
    const message = parseServerMessage(event.data);
    if (!message) return;

    switch (message.type) {
      case 'status':
        if (message.status === 'connected') {
          if (this.stopping) return;
          this.sessionCount += 1;
          this.update({
            status: 'connected',
            mode: message.mode ?? this.snapshot.mode,
            sessionId: this.sessionCount,
            streamComplete: false,
            error: null,
            reconnect: null,
          });
        } else if (message.status === 'stream_complete') {
          this.update({ streamComplete: true, interim: null });
        } else {
          // "stopped": the server has flushed everything in response to our stop.
          this.finishStop();
        }
        return;

      case 'transcript':
        this.markHealthy();
        this.applyTranscript(message.segment);
        return;

      case 'error':
        this.handleServerError(message.error);
        return;

      case 'pong':
        return;
    }
  }

  /** The server closes the socket right after an error frame; act on the error itself. */
  private handleServerError(error: StreamError): void {
    this.releaseSocket();
    if (this.stopping) {
      this.update({ error });
      this.finishStop();
    } else if (error.retryable) {
      this.scheduleReconnect(error);
    } else {
      this.fail(error);
    }
  }

  private handleSocketGone(normalClosure: boolean): void {
    this.releaseSocket();
    if (this.stopping) {
      this.finishStop();
    } else if (normalClosure) {
      // The server ended the session on purpose; nothing to recover.
      this.update({ status: 'stopped', sessionId: null, interim: null, reconnect: null });
    } else {
      this.scheduleReconnect(null);
    }
  }

  private heartbeat(): void {
    if (this.awaitingPong) {
      // Not even a pong for a whole interval: the link is dead even if the browser hasn't noticed.
      this.handleSocketGone(false);
      return;
    }
    this.awaitingPong = true;
    this.send({ type: 'ping' });
  }

  private scheduleReconnect(error: StreamError | null): void {
    if (this.attempts >= RECONNECT_DELAYS_MS.length) {
      this.fail(error ?? CONNECTION_LOST);
      return;
    }

    const delayMs = RECONNECT_DELAYS_MS[this.attempts];
    this.attempts += 1;
    this.update({
      status: 'reconnecting',
      sessionId: null,
      interim: null,
      error,
      reconnect: { attempt: this.attempts, maxAttempts: RECONNECT_DELAYS_MS.length, delayMs },
    });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delayMs);
  }

  private fail(error: StreamError): void {
    this.update({ status: 'failed', sessionId: null, interim: null, error, reconnect: null });
  }

  private finishStop(): void {
    this.clearStopTimer();
    this.stopping = false;
    this.releaseSocket();
    this.update({ status: 'stopped', sessionId: null, interim: null, reconnect: null });
    this.resolveStopWaiters();
  }

  /** The connection has proven itself, so the retry budget starts over. */
  private markHealthy(): void {
    this.attempts = 0;
    if (this.stableTimer !== null) {
      clearTimeout(this.stableTimer);
      this.stableTimer = null;
    }
  }

  private applyTranscript(segment: LiveSegment): void {
    const current = { segments: this.snapshot.segments, interim: this.snapshot.interim };
    const next = applySegment(current, segment);
    if (next !== current) this.update(next);
  }

  private send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  /** Detaches from the current socket (closing it if needed) so its late events are ignored. */
  private releaseSocket(): void {
    if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
    if (this.stableTimer !== null) clearTimeout(this.stableTimer);
    this.heartbeatTimer = null;
    this.stableTimer = null;

    const socket = this.socket;
    if (!socket) return;
    this.socket = null;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) {
      socket.close(NORMAL_CLOSURE);
    }
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearStopTimer(): void {
    if (this.stopTimer !== null) {
      clearTimeout(this.stopTimer);
      this.stopTimer = null;
    }
  }

  private resolveStopWaiters(): void {
    const waiters = this.stopWaiters;
    this.stopWaiters = [];
    waiters.forEach((resolve) => resolve());
  }

  private update(patch: Partial<MeetingSocketSnapshot>): void {
    const keys = Object.keys(patch) as Array<keyof MeetingSocketSnapshot>;
    if (keys.every((key) => Object.is(this.snapshot[key], patch[key]))) return;
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }
}
