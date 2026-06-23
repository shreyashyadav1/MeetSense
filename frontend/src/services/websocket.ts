import type { WSMessage } from '../types';

const WS_BASE = 'ws://localhost:8000';
const MAX_RETRIES = 3;
const PING_INTERVAL_MS = 30_000;

export class MeetingSocket {
  private meetingId: string;
  private onMessage: (msg: WSMessage) => void;
  private socket: WebSocket | null = null;
  private retryCount = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;

  constructor(meetingId: string, onMessage: (msg: WSMessage) => void) {
    this.meetingId = meetingId;
    this.onMessage = onMessage;
  }

  connect(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return;
    }

    this.shouldReconnect = true;
    this._openSocket();
  }

  private _openSocket(): void {
    const url = `${WS_BASE}/ws/meetings/${this.meetingId}/stream`;

    try {
      this.socket = new WebSocket(url);
    } catch (err) {
      console.error('[MeetingSocket] Failed to create WebSocket:', err);
      this._scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      console.log('[MeetingSocket] Connected');
      this.retryCount = 0;
      this._startPing();
    };

    this.socket.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WSMessage;
        this.onMessage(msg);
      } catch (err) {
        console.error('[MeetingSocket] Failed to parse message:', err);
      }
    };

    this.socket.onerror = (event) => {
      console.error('[MeetingSocket] WebSocket error:', event);
    };

    this.socket.onclose = (event) => {
      console.log(`[MeetingSocket] Closed (code=${event.code})`);
      this._stopPing();

      if (this.shouldReconnect && this.retryCount < MAX_RETRIES) {
        this._scheduleReconnect();
      }
    };
  }

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) return;

    const delay = Math.pow(2, this.retryCount) * 1000; // 1s, 2s, 4s
    this.retryCount += 1;
    console.log(`[MeetingSocket] Reconnecting in ${delay}ms (attempt ${this.retryCount}/${MAX_RETRIES})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.shouldReconnect) {
        this._openSocket();
      }
    }, delay);
  }

  private _startPing(): void {
    this._stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: 'ping' });
    }, PING_INTERVAL_MS);
  }

  private _stopPing(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  send(msg: object): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(msg));
    }
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this._stopPing();

    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      this.socket.close(1000, 'Client disconnect');
      this.socket = null;
    }
  }

  get readyState(): number {
    return this.socket?.readyState ?? WebSocket.CLOSED;
  }
}
