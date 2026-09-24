import { vi } from 'vitest';

/**
 * Minimal stand-in for the browser WebSocket. Tests drive the "server" side
 * explicitly: open(), receive(), and serverClose().
 */
export class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  /** Installs the fake as the global WebSocket for the current test. */
  static install(): void {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  }

  static get latest(): FakeWebSocket {
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) throw new Error('No WebSocket has been created');
    return socket;
  }

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  binaryType: BinaryType = 'blob';
  readonly sent: unknown[] = [];
  closedByClient: number | null = null;

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: unknown): void {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new DOMException('WebSocket is not open', 'InvalidStateError');
    }
    this.sent.push(data);
  }

  close(code = 1000): void {
    if (this.readyState >= FakeWebSocket.CLOSING) return;
    this.closedByClient = code;
    this.readyState = FakeWebSocket.CLOSING;
  }

  /** JSON control messages sent by the client (audio frames excluded). */
  get sentMessages(): unknown[] {
    return this.sent.filter((data) => typeof data === 'string').map((data) => JSON.parse(data as string));
  }

  get sentAudio(): unknown[] {
    return this.sent.filter((data) => typeof data !== 'string');
  }

  // --- server side ---

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  receive(message: object): void {
    this.receiveRaw(JSON.stringify(message));
  }

  receiveRaw(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  /** Accepts the connection and sends the protocol's initial status frame. */
  accept(mode: 'deepgram' | 'mock' = 'deepgram'): void {
    this.open();
    this.receive({ type: 'status', status: 'connected', mode });
  }

  serverClose(code = 1006): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, wasClean: code === 1000 }));
  }
}

let nextSequence = 1;

/** Builds a wire-format transcript frame. */
export function transcriptFrame(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const sequence = overrides.sequence ?? nextSequence++;
  return {
    type: 'transcript',
    id: `segment-${String(sequence)}`,
    meeting_id: 'meeting-1',
    speaker: 'Speaker 1',
    text: `Sentence ${String(sequence)}`,
    timestamp: 1.5,
    confidence: 0.9,
    is_final: true,
    sequence,
    ...overrides,
  };
}
