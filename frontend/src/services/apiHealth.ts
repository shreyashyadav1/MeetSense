import { apiClient } from './api';
import { getErrorStatus } from './errors';

const CHECK_INTERVAL_MS = 60_000;
const CHECK_TIMEOUT_MS = 5_000;

export interface ApiHealthSnapshot {
  /** True once a check has failed; cleared as soon as a later one succeeds. */
  offline: boolean;
}

const INITIAL_SNAPSHOT: ApiHealthSnapshot = { offline: false };

/**
 * Polls GET /health and exposes whether the API looks reachable, following
 * the same subscribe/getSnapshot shape as MeetingSocket so React can read it
 * with useSyncExternalStore.
 *
 * A network error, a timeout, or a 5xx response all count as offline. Polling
 * starts lazily on the first subscriber (i.e. once the offline banner
 * mounts) and `checkNow` lets another part of the app - the live meeting
 * stream, when it loses its connection - ask for an immediate recheck
 * instead of waiting for the next scheduled one.
 */
class ApiHealthMonitor {
  private snapshot: ApiHealthSnapshot = INITIAL_SNAPSHOT;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight: Promise<void> | null = null;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    this.ensureStarted();
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): ApiHealthSnapshot => this.snapshot;

  /** Requests an immediate check without waiting for the next scheduled poll. */
  checkNow = (): void => {
    void this.check();
  };

  /** Test-only: stops polling and clears state so the next test starts clean. */
  reset(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.inFlight = null;
    this.snapshot = INITIAL_SNAPSHOT;
    this.listeners.clear();
  }

  private ensureStarted(): void {
    if (this.timer !== null) return;
    this.checkNow();
    this.timer = setInterval(() => this.checkNow(), CHECK_INTERVAL_MS);
  }

  /** Coalesces overlapping calls, e.g. a manual checkNow() racing the scheduled poll. */
  private check(): Promise<void> {
    if (!this.inFlight) {
      this.inFlight = this.run().finally(() => {
        this.inFlight = null;
      });
    }
    return this.inFlight;
  }

  private async run(): Promise<void> {
    try {
      await apiClient.get('/health', { timeout: CHECK_TIMEOUT_MS });
      this.update(false);
    } catch (error) {
      const status = getErrorStatus(error);
      this.update(status === null || status >= 500);
    }
  }

  private update(offline: boolean): void {
    if (this.snapshot.offline === offline) return;
    this.snapshot = { offline };
    this.listeners.forEach((listener) => listener());
  }
}

export const apiHealthMonitor = new ApiHealthMonitor();
