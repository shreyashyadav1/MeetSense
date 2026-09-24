import { vi } from 'vitest';

export class FakeMediaStreamTrack extends EventTarget {
  readonly kind = 'audio';
  readyState: 'live' | 'ended' = 'live';
  stop = vi.fn(() => {
    this.readyState = 'ended';
  });
}

export class FakeMediaStream {
  readonly tracks = [new FakeMediaStreamTrack()];
  getTracks() {
    return this.tracks;
  }
  getAudioTracks() {
    return this.tracks;
  }
}

/** MediaRecorder stand-in; tests push chunks with emit(). */
export class FakeMediaRecorder extends EventTarget {
  static instances: FakeMediaRecorder[] = [];
  static isTypeSupported = (type: string) => type === 'audio/webm;codecs=opus';

  readonly stream: FakeMediaStream;
  readonly mimeType: string;
  state: 'inactive' | 'recording' = 'inactive';
  timeslice: number | undefined;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(stream: FakeMediaStream, options?: { mimeType?: string }) {
    super();
    this.stream = stream;
    this.mimeType = options?.mimeType ?? '';
    FakeMediaRecorder.instances.push(this);
  }

  start(timeslice?: number) {
    this.state = 'recording';
    this.timeslice = timeslice;
  }

  /** Like the real thing: flushes a final chunk, then fires "stop", asynchronously. */
  stop() {
    this.state = 'inactive';
    queueMicrotask(() => {
      this.emit('final chunk');
      this.dispatchEvent(new Event('stop'));
    });
  }

  emit(content: string) {
    this.ondataavailable?.({ data: new Blob([content]) });
  }
}

/** Installs getUserMedia and MediaRecorder fakes for the current test. */
export function installFakeMedia() {
  FakeMediaRecorder.instances = [];
  const stream = new FakeMediaStream();
  const getUserMedia = vi.fn<(constraints: MediaStreamConstraints) => Promise<FakeMediaStream>>(
    () => Promise.resolve(stream),
  );
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
  return { stream, getUserMedia, recorders: FakeMediaRecorder.instances };
}

export function uninstallFakeMedia() {
  Reflect.deleteProperty(navigator, 'mediaDevices');
}
