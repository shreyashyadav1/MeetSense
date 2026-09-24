export type MeetingStatus = 'active' | 'ended';

export interface Meeting {
  id: string;
  title: string;
  status: MeetingStatus;
  started_at: string;
  ended_at?: string | null;
}

export interface TranscriptSegment {
  id: string;
  meeting_id: string;
  speaker: string;
  text: string;
  /** Seconds from the start of the meeting. */
  timestamp: number;
  confidence: number;
  is_final?: boolean;
  /** Position in the meeting's live stream (present on WebSocket segments). */
  sequence?: number;
}

export type MicrophoneStatus = 'idle' | 'requesting' | 'active' | 'denied' | 'error' | 'unsupported';

export interface MeetingInsights {
  id: string;
  meeting_id: string;
  summary: string;
  action_items: string[];
  decisions: string[];
  questions_raised: string[];
  follow_up_email: string;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Live stream protocol: /ws/meetings/{id}/stream
// ---------------------------------------------------------------------------

/** Which transcription source the server is using for the session. */
export type TranscriptionMode = 'deepgram' | 'mock';

/** A transcript segment received over the live stream. */
export interface LiveSegment extends TranscriptSegment {
  /** Monotonic per meeting, including across reconnects. */
  sequence: number;
  is_final: boolean;
}

export interface StreamError {
  /**
   * Server codes: meeting_not_found, meeting_ended, origin_not_allowed,
   * session_time_limit (not retryable); too_many_connections,
   * transcription_unavailable, internal_error (retryable).
   */
  code: string;
  message: string;
  retryable: boolean;
}

/** A server frame after parsing and validation. */
export type ServerMessage =
  | { type: 'status'; status: 'connected'; mode: TranscriptionMode | null }
  | { type: 'status'; status: 'stream_complete' | 'stopped' }
  | { type: 'transcript'; segment: LiveSegment }
  | { type: 'error'; error: StreamError }
  | { type: 'pong' };

export type ClientMessage = { type: 'ping' } | { type: 'stop' };

/**
 * idle: not started · connecting/reconnecting: waiting for the server's
 * "connected" · connected: audio may flow · stopping: stop sent, waiting for
 * the flush · stopped: session over, no retry · failed: gave up.
 */
export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'stopping'
  | 'stopped'
  | 'failed';
