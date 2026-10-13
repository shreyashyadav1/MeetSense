import { describe, expect, it } from 'vitest';
import { parseServerMessage } from './protocol';

const parse = (message: unknown) => parseServerMessage(JSON.stringify(message));

describe('parseServerMessage', () => {
  it('parses status frames', () => {
    expect(parse({ type: 'status', status: 'connected', mode: 'mock' })).toEqual({
      type: 'status',
      status: 'connected',
      mode: 'mock',
    });
    expect(parse({ type: 'status', status: 'connected', mode: 'whisper' })).toMatchObject({ mode: null });
    expect(parse({ type: 'status', status: 'stream_complete' })).toEqual({
      type: 'status',
      status: 'stream_complete',
    });
    expect(parse({ type: 'status', status: 'stopped' })).toEqual({ type: 'status', status: 'stopped' });
    expect(parse({ type: 'status', status: 'ended' })).toBeNull();
  });

  it('parses flat transcript frames and requires an integer sequence', () => {
    const frame = {
      type: 'transcript',
      id: 'seg-1',
      meeting_id: 'm1',
      speaker: 'Speaker 2',
      text: 'Hello.',
      timestamp: 3.2,
      confidence: 0.97,
      is_final: true,
      sequence: 4,
    };
    expect(parse(frame)).toEqual({
      type: 'transcript',
      segment: {
        id: 'seg-1',
        meeting_id: 'm1',
        speaker: 'Speaker 2',
        text: 'Hello.',
        timestamp: 3.2,
        confidence: 0.97,
        is_final: true,
        sequence: 4,
      },
    });
    expect(parse({ ...frame, sequence: undefined })).toBeNull();
    expect(parse({ ...frame, sequence: 1.5 })).toBeNull();
    expect(parse({ ...frame, is_final: false })).toMatchObject({ segment: { is_final: false } });
  });

  it('parses error frames and only retries when the server says so', () => {
    expect(
      parse({ type: 'error', code: 'internal_error', message: 'Boom', retryable: true }),
    ).toEqual({ type: 'error', error: { code: 'internal_error', message: 'Boom', retryable: true } });
    expect(parse({ type: 'error', code: 'internal_error' })).toMatchObject({
      error: { retryable: false, message: expect.any(String) as string },
    });
  });

  it('rejects frames it does not understand', () => {
    expect(parseServerMessage('{not json')).toBeNull();
    expect(parseServerMessage(new ArrayBuffer(4))).toBeNull();
    expect(parse([1, 2])).toBeNull();
    expect(parse({ type: 'something_new' })).toBeNull();
  });
});
