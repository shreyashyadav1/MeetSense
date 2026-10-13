const LOCAL_BACKEND_URL = 'http://localhost:8000';

export interface ApiConfig {
  /** Prefix for REST requests. An empty string means same-origin relative URLs. */
  apiBaseUrl: string;
  /** Origin for WebSocket connections, e.g. `wss://api.example.com`. */
  wsBaseUrl: string;
}

/**
 * Derives the REST and WebSocket base URLs from `VITE_API_URL`.
 *
 * - unset: talk to a backend on http://localhost:8000 (local development)
 * - `https://host`: REST on https://host, WebSocket on wss://host
 * - empty string: same origin, for deployments where a reverse proxy serves
 *   /api and /ws next to the app (the Docker image, or the Vite dev proxy).
 *   The WebSocket scheme follows the page: https pages use wss.
 */
export function resolveApiConfig(
  apiUrl: string | undefined,
  location: Pick<Location, 'protocol' | 'host'>,
): ApiConfig {
  const base = (apiUrl ?? LOCAL_BACKEND_URL).trim().replace(/\/+$/, '');

  if (base === '') {
    const wsScheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return { apiBaseUrl: '', wsBaseUrl: `${wsScheme}//${location.host}` };
  }

  return { apiBaseUrl: base, wsBaseUrl: base.replace(/^http/i, 'ws') };
}

export const apiConfig = resolveApiConfig(import.meta.env.VITE_API_URL, window.location);
