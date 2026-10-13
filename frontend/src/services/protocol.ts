import type { LiveSegment, ServerMessage, StreamError } from '../types';

type JsonObject = Record<string, unknown>;

const isObject = (value: unknown): value is JsonObject =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

/**
 * Parses a text frame from the meeting stream. Anything malformed or of an
 * unknown type yields null so the caller can ignore it.
 */
export function parseServerMessage(data: unknown): ServerMessage | null {
  if (typeof data !== 'string') return null;

  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isObject(raw)) return null;

  switch (raw.type) {
    case 'status':
      return parseStatus(raw);
    case 'transcript': {
      const segment = parseSegment(raw);
      return segment ? { type: 'transcript', segment } : null;
    }
    case 'error':
      return { type: 'error', error: parseError(raw) };
    case 'pong':
      return { type: 'pong' };
    default:
      return null;
  }
}

function parseStatus(raw: JsonObject): ServerMessage | null {
  switch (raw.status) {
    case 'connected':
      return {
        type: 'status',
        status: 'connected',
        mode: raw.mode === 'deepgram' || raw.mode === 'mock' ? raw.mode : null,
      };
    case 'stream_complete':
    case 'stopped':
      return { type: 'status', status: raw.status };
    default:
      return null;
  }
}

function parseSegment(raw: JsonObject): LiveSegment | null {
  if (typeof raw.id !== 'string' || typeof raw.text !== 'string') return null;
  if (typeof raw.sequence !== 'number' || !Number.isInteger(raw.sequence)) return null;

  return {
    id: raw.id,
    meeting_id: asString(raw.meeting_id),
    speaker: asString(raw.speaker),
    text: raw.text,
    timestamp: asNumber(raw.timestamp),
    confidence: asNumber(raw.confidence),
    is_final: raw.is_final !== false,
    sequence: raw.sequence,
  };
}

function parseError(raw: JsonObject): StreamError {
  return {
    code: asString(raw.code, 'unknown_error'),
    message: asString(raw.message) || 'The transcription server reported an error.',
    // Only retry when the server explicitly says it is safe to.
    retryable: raw.retryable === true,
  };
}
