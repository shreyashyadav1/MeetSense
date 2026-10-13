import type { AxiosAdapter } from 'axios';
import { apiClient } from '../services/api';
import { apiError, networkError } from './apiError';

export type HealthReply = { status?: number; data?: unknown } | 'network-error';

/**
 * Swaps in a fake adapter so GET /health resolves however the test wants,
 * without reaching a real server. `reply` is invoked for every check, so a
 * test can close over a mutable value to script an outage that later
 * recovers. Any other request is rejected loudly. Callers restore
 * `apiClient.defaults.adapter` themselves (see api.test.ts).
 */
export function mockHealth(reply: () => HealthReply): void {
  const adapter: AxiosAdapter = (config) => {
    if (config.url !== '/health') {
      return Promise.reject(
        new Error(`Unexpected request in test: ${String(config.method)} ${String(config.url)}`),
      );
    }

    const result = reply();
    if (result === 'network-error') return Promise.reject(networkError());

    const { status = 200, data = {} } = result;
    if (status >= 400) return Promise.reject(apiError(status, data));
    return Promise.resolve({ data, status, statusText: 'OK', headers: {}, config });
  };
  apiClient.defaults.adapter = adapter;
}
