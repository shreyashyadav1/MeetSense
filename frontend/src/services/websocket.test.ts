import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeWebSocket, transcriptFrame } from '../test/fakeWebSocket';
import {
  HEARTBEAT_INTERVAL_MS,
  MeetingSocket,
  RECONNECT_DELAYS_MS,
  STABLE_CONNECTION_MS,
  STOP_TIMEOUT_MS,
  meetingStreamUrl,
} from './websocket';

const STREAM_URL = 'ws://backend.test/ws/meetings/meeting-1/stream';

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.install();
});

afterEach(() => {
  vi.useRealTimers();
});

function connect(): MeetingSocket {
  const socket = new MeetingSocket(STREAM_URL);
  socket.connect();
  return socket;
}

/** Drops the current connection abnormally and waits out the backoff delay. */
function dropAndWait(delayMs: number, code = 1006): void {
  FakeWebSocket.latest.serverClose(code);
  vi.advanceTimersByTime(delayMs);
}

describe('meetingStreamUrl', () => {
  it('appends the stream path to the WebSocket base', () => {
    expect(meetingStreamUrl('abc 1', 'wss://api.example.com')).toBe(
      'wss://api.example.com/ws/meetings/abc%201/stream',
    );
  });
});

describe('MeetingSocket session', () => {
  it('sends audio only after the server confirms the session, and records the mode', () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    const chunk = new Blob(['audio']);
    expect(ws.url).toBe(STREAM_URL);

    ws.open();
    expect(socket.getSnapshot().status).toBe('connecting');
    expect(socket.sendAudio(chunk)).toBe(false);

    ws.receive({ type: 'status', status: 'connected', mode: 'mock' });
    expect(socket.getSnapshot()).toMatchObject({ status: 'connected', mode: 'mock', sessionId: 1 });
    expect(socket.sendAudio(chunk)).toBe(true);
    expect(ws.sentAudio).toEqual([chunk]);
  });

  it('flags when the transcription source has finished', () => {
    const socket = connect();
    FakeWebSocket.latest.accept('mock');
    FakeWebSocket.latest.receive({ type: 'status', status: 'stream_complete' });
    expect(socket.getSnapshot()).toMatchObject({ status: 'connected', streamComplete: true });
  });

  it('notifies subscribers only when the snapshot changes', () => {
    const socket = connect();
    const listener = vi.fn();
    socket.subscribe(listener);
    const ws = FakeWebSocket.latest;

    ws.accept();
    expect(listener).toHaveBeenCalledTimes(1);
    ws.receive({ type: 'pong' });
    ws.receiveRaw('not json');
    ws.receive({ type: 'transcript', id: 'x', text: 'no sequence' });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('ignores socket events after disconnect', () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();
    socket.disconnect();

    expect(ws.closedByClient).toBe(1000);
    ws.serverClose(1006);
    vi.advanceTimersByTime(60_000);
    expect(socket.getSnapshot().status).toBe('idle');
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe('MeetingSocket reconnect policy', () => {
  it('backs off 1, 2, 4, 8 and 16 seconds, then gives up', () => {
    const socket = connect();

    RECONNECT_DELAYS_MS.forEach((delayMs, index) => {
      FakeWebSocket.latest.serverClose(1006);
      expect(socket.getSnapshot()).toMatchObject({
        status: 'reconnecting',
        reconnect: { attempt: index + 1, maxAttempts: 5, delayMs },
      });

      const created = FakeWebSocket.instances.length;
      vi.advanceTimersByTime(delayMs - 1);
      expect(FakeWebSocket.instances).toHaveLength(created);
      vi.advanceTimersByTime(1);
      expect(FakeWebSocket.instances).toHaveLength(created + 1);
    });
    expect(RECONNECT_DELAYS_MS).toEqual([1000, 2000, 4000, 8000, 16000]);

    FakeWebSocket.latest.serverClose(1006);
    expect(socket.getSnapshot()).toMatchObject({
      status: 'failed',
      reconnect: null,
      error: { code: 'connection_lost' },
    });
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(6);
  });

  it('does not refill the retry budget merely because a connection opened', () => {
    // A server that accepts and immediately drops the connection must not be retried forever.
    const socket = connect();
    for (const delayMs of RECONNECT_DELAYS_MS) {
      FakeWebSocket.latest.accept();
      dropAndWait(delayMs, 1011);
    }
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.serverClose(1011);

    expect(socket.getSnapshot().status).toBe('failed');
  });

  it('refills the retry budget once a connection stays open for 10 seconds', () => {
    const socket = connect();
    RECONNECT_DELAYS_MS.slice(0, 4).forEach((delayMs) => dropAndWait(delayMs));

    FakeWebSocket.latest.accept();
    vi.advanceTimersByTime(STABLE_CONNECTION_MS - 1);
    FakeWebSocket.latest.serverClose(1006);
    expect(socket.getSnapshot().reconnect).toMatchObject({ attempt: 5, delayMs: 16_000 });

    vi.advanceTimersByTime(16_000);
    FakeWebSocket.latest.accept();
    vi.advanceTimersByTime(STABLE_CONNECTION_MS);
    FakeWebSocket.latest.serverClose(1006);
    expect(socket.getSnapshot().reconnect).toMatchObject({ attempt: 1, delayMs: 1000 });
  });

  it('refills the retry budget when a transcript arrives', () => {
    const socket = connect();
    RECONNECT_DELAYS_MS.slice(0, 4).forEach((delayMs) => dropAndWait(delayMs));

    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.receive(transcriptFrame());
    FakeWebSocket.latest.serverClose(1006);
    expect(socket.getSnapshot().reconnect).toMatchObject({ attempt: 1 });
  });

  it('stops retrying after a non-retryable error and surfaces its message', () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();
    ws.receive({
      type: 'error',
      code: 'meeting_ended',
      message: 'This meeting has already ended.',
      retryable: false,
    });
    ws.serverClose(1008);

    expect(socket.getSnapshot()).toMatchObject({
      status: 'failed',
      sessionId: null,
      error: { code: 'meeting_ended', message: 'This meeting has already ended.', retryable: false },
    });
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('retries after a retryable error while showing its message', () => {
    const socket = connect();
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.receive({
      type: 'error',
      code: 'too_many_connections',
      message: 'Too many live sessions right now.',
      retryable: true,
    });

    expect(socket.getSnapshot()).toMatchObject({
      status: 'reconnecting',
      error: { message: 'Too many live sessions right now.' },
    });
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(2);

    FakeWebSocket.latest.accept();
    expect(socket.getSnapshot()).toMatchObject({ status: 'connected', error: null, sessionId: 2 });
  });

  it('treats a normal closure from the server as the end of the session', () => {
    const socket = connect();
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.serverClose(1000);

    expect(socket.getSnapshot().status).toBe('stopped');
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('starts over with a fresh budget when retried manually', () => {
    const socket = connect();
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.receive({
      type: 'error',
      code: 'session_time_limit',
      message: 'Demo sessions are limited to 10 minutes.',
      retryable: false,
    });
    expect(socket.getSnapshot().status).toBe('failed');

    socket.connect();
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(socket.getSnapshot()).toMatchObject({ status: 'connecting', error: null });
  });

  it('reconnects when the server stops answering pings', () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();

    vi.advanceTimersByTime(HEARTBEAT_INTERVAL_MS);
    expect(ws.sentMessages).toEqual([{ type: 'ping' }]);
    ws.receive({ type: 'pong' });
    vi.advanceTimersByTime(HEARTBEAT_INTERVAL_MS);
    expect(socket.getSnapshot().status).toBe('connected');

    vi.advanceTimersByTime(HEARTBEAT_INTERVAL_MS);
    expect(socket.getSnapshot().status).toBe('reconnecting');
    expect(ws.closedByClient).toBe(1000);
  });
});

describe('MeetingSocket stop', () => {
  it('sends stop, keeps flushed segments and resolves on "stopped" without reconnecting', async () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();

    const stopped = socket.stop();
    expect(ws.sentMessages).toEqual([{ type: 'stop' }]);
    expect(socket.getSnapshot()).toMatchObject({ status: 'stopping', sessionId: null });
    expect(socket.sendAudio(new Blob(['late']))).toBe(false);

    ws.receive(transcriptFrame({ sequence: 7, text: 'Last words.' }));
    ws.receive({ type: 'status', status: 'stopped' });
    await stopped;
    ws.serverClose(1000);

    expect(socket.getSnapshot().status).toBe('stopped');
    expect(socket.getSnapshot().segments.map((s) => s.text)).toEqual(['Last words.']);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('closes anyway if the server never acknowledges', async () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();

    const stopped = socket.stop();
    vi.advanceTimersByTime(STOP_TIMEOUT_MS);
    await stopped;

    expect(socket.getSnapshot().status).toBe('stopped');
    expect(ws.closedByClient).toBe(1000);
  });

  it('cancels a pending reconnect', async () => {
    const socket = connect();
    FakeWebSocket.latest.serverClose(1006);
    expect(socket.getSnapshot().status).toBe('reconnecting');

    await socket.stop();
    vi.advanceTimersByTime(60_000);
    expect(socket.getSnapshot().status).toBe('stopped');
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe('MeetingSocket transcript', () => {
  it('orders segments by sequence and drops replays after a reconnect', () => {
    const socket = connect();
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.receive(transcriptFrame({ sequence: 1 }));
    FakeWebSocket.latest.receive(transcriptFrame({ sequence: 3 }));
    FakeWebSocket.latest.receive(transcriptFrame({ sequence: 2 }));

    dropAndWait(RECONNECT_DELAYS_MS[0]);
    FakeWebSocket.latest.accept();
    FakeWebSocket.latest.receive(transcriptFrame({ sequence: 3 }));
    FakeWebSocket.latest.receive(transcriptFrame({ sequence: 4 }));

    const { segments, sessionId } = socket.getSnapshot();
    expect(segments.map((s) => s.sequence)).toEqual([1, 2, 3, 4]);
    expect(sessionId).toBe(2);
  });

  it('shows the latest interim result until a final supersedes it', () => {
    const socket = connect();
    const ws = FakeWebSocket.latest;
    ws.accept();
    const interim = { id: 'interim-meeting-1', speaker: '', is_final: false };

    ws.receive(transcriptFrame({ ...interim, sequence: 10, text: 'Hello' }));
    ws.receive(transcriptFrame({ ...interim, sequence: 11, text: 'Hello wor' }));
    expect(socket.getSnapshot().interim?.text).toBe('Hello wor');

    ws.receive(transcriptFrame({ sequence: 12, text: 'Hello world.' }));
    ws.receive(transcriptFrame({ ...interim, sequence: 11, text: 'Hello wor' }));
    expect(socket.getSnapshot().interim).toBeNull();
    expect(socket.getSnapshot().segments.map((s) => s.text)).toEqual(['Hello world.']);
  });
});
