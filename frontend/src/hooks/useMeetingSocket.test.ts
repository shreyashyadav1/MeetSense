import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { FakeWebSocket, transcriptFrame } from '../test/fakeWebSocket';
import { useMeetingSocket } from './useMeetingSocket';

beforeEach(() => {
  FakeWebSocket.install();
});

describe('useMeetingSocket', () => {
  it('connects on mount, mirrors the stream state and disconnects on unmount', () => {
    const { result, unmount } = renderHook(() => useMeetingSocket('meeting-1'));
    const ws = FakeWebSocket.latest;
    expect(ws.url).toMatch(/\/ws\/meetings\/meeting-1\/stream$/);
    expect(result.current.status).toBe('connecting');

    act(() => {
      ws.accept('deepgram');
      ws.receive(transcriptFrame({ sequence: 1, text: 'Hi there.' }));
    });
    expect(result.current).toMatchObject({ status: 'connected', mode: 'deepgram', sessionId: 1 });
    expect(result.current.segments.map((s) => s.text)).toEqual(['Hi there.']);

    unmount();
    expect(ws.closedByClient).toBe(1000);
  });

  it('starts a fresh stream when the meeting changes', () => {
    const { result, rerender } = renderHook(({ id }) => useMeetingSocket(id), {
      initialProps: { id: 'meeting-1' },
    });
    act(() => {
      FakeWebSocket.latest.accept();
      FakeWebSocket.latest.receive(transcriptFrame({ sequence: 1 }));
    });
    const first = FakeWebSocket.latest;

    rerender({ id: 'meeting-2' });
    expect(first.closedByClient).toBe(1000);
    expect(FakeWebSocket.latest.url).toMatch(/meeting-2/);
    expect(result.current.segments).toEqual([]);
  });
});
