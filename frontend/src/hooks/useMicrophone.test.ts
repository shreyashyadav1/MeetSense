import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TIMESLICE_MS } from '../services/microphone';
import { installFakeMedia, uninstallFakeMedia } from '../test/fakeMedia';
import { useMicrophone } from './useMicrophone';

let media: ReturnType<typeof installFakeMedia>;

beforeEach(() => {
  media = installFakeMedia();
});

afterEach(() => {
  uninstallFakeMedia();
});

function renderMicrophone(sessionId: number | null = null) {
  const onChunk = vi.fn<(chunk: Blob) => void>();
  const hook = renderHook((props: { sessionId: number | null }) => useMicrophone({ ...props, onChunk }), {
    initialProps: { sessionId },
  });
  return { ...hook, onChunk };
}

const chunkText = (onChunk: ReturnType<typeof vi.fn>) =>
  Promise.all(onChunk.mock.calls.map(([chunk]) => (chunk as Blob).text()));

describe('useMicrophone', () => {
  it('records only while a session is attached, with a fresh MediaRecorder per session', async () => {
    const { result, rerender, onChunk } = renderMicrophone(null);

    await act(() => result.current.start());
    expect(result.current.status).toBe('active');
    expect(media.recorders).toHaveLength(0);

    rerender({ sessionId: 1 });
    const [first] = media.recorders;
    expect(first.state).toBe('recording');
    expect(first.timeslice).toBe(TIMESLICE_MS);
    expect(first.mimeType).toBe('audio/webm;codecs=opus');
    first.emit('session 1 header');

    // Connection lost: the old recording stops and its leftovers are dropped.
    rerender({ sessionId: null });
    await act(() => Promise.resolve());
    expect(first.state).toBe('inactive');
    first.emit('stale audio');

    rerender({ sessionId: 2 });
    const second = media.recorders[1];
    expect(second).not.toBe(first);
    expect(second.state).toBe('recording');
    second.emit('session 2 header');

    // A session can also be replaced directly.
    rerender({ sessionId: 3 });
    expect(second.state).toBe('inactive');
    expect(media.recorders[2].state).toBe('recording');

    expect(await chunkText(onChunk)).toEqual(['session 1 header', 'session 2 header']);
    expect(media.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('delivers the final chunk on stop and releases the microphone', async () => {
    const { result, onChunk } = renderMicrophone(1);
    await act(() => result.current.start());
    const [recorder] = media.recorders;

    await act(() => result.current.stop());

    expect(recorder.state).toBe('inactive');
    expect(await chunkText(onChunk)).toEqual(['final chunk']);
    expect(media.stream.tracks[0].stop).toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it.each([
    ['NotAllowedError', 'denied', /allow microphone access/i],
    ['NotFoundError', 'error', /no microphone was found/i],
    ['NotReadableError', 'error', /in use by another application/i],
  ])('explains a %s from getUserMedia', async (name, status, message) => {
    media.getUserMedia.mockRejectedValueOnce(new DOMException('failed', name));
    const { result } = renderMicrophone(1);

    await act(() => result.current.start());

    expect(result.current.status).toBe(status);
    expect(result.current.error).toMatch(message);
    expect(media.recorders).toHaveLength(0);
  });

  it('can retry after the user grants access', async () => {
    media.getUserMedia.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'));
    const { result } = renderMicrophone(1);

    await act(() => result.current.start());
    expect(result.current.status).toBe('denied');

    await act(() => result.current.start());
    expect(result.current).toMatchObject({ status: 'active', error: null });
    expect(media.recorders).toHaveLength(1);
  });

  it('discards a microphone granted after recording was cancelled', async () => {
    let grant: () => void = () => undefined;
    media.getUserMedia.mockImplementationOnce(
      () => new Promise((resolve) => (grant = () => resolve(media.stream))),
    );
    const { result } = renderMicrophone(1);

    let starting: Promise<void> = Promise.resolve();
    act(() => {
      starting = result.current.start();
    });
    expect(result.current.status).toBe('requesting');
    await act(() => result.current.stop());
    await act(async () => {
      grant();
      await starting;
    });

    expect(result.current.status).toBe('idle');
    expect(media.stream.tracks[0].stop).toHaveBeenCalled();
    expect(media.recorders).toHaveLength(0);
  });

  it('reports browsers without recording support', () => {
    uninstallFakeMedia();
    const { result } = renderMicrophone(1);
    expect(result.current.status).toBe('unsupported');
    expect(result.current.error).toMatch(/https/i);
  });

  it('releases the microphone on unmount', async () => {
    const { result, unmount } = renderMicrophone(1);
    await act(() => result.current.start());

    unmount();
    await act(() => Promise.resolve());
    expect(media.recorders[0].state).toBe('inactive');
    expect(media.stream.tracks[0].stop).toHaveBeenCalled();
  });
});
