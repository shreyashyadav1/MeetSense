import axios from 'axios';

export interface ErrorMessages {
  /** Used when nothing more specific applies. */
  fallback: string;
  /** Wording for particular HTTP statuses in this context. */
  byStatus?: Partial<Record<number, string>>;
}

/** HTTP status of a failed API call, or null for network errors and non-HTTP failures. */
export function getErrorStatus(error: unknown): number | null {
  return axios.isAxiosError(error) ? (error.response?.status ?? null) : null;
}

/**
 * Reads FastAPI's error body. The API returns {"detail": "..."}; FastAPI's
 * default validation errors use a list of {msg} objects instead.
 */
function readDetail(data: unknown): string | null {
  if (typeof data !== 'object' || data === null || !('detail' in data)) return null;
  const { detail } = data;
  if (typeof detail === 'string') return detail || null;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: unknown) =>
        typeof issue === 'object' && issue !== null && 'msg' in issue ? String(issue.msg) : null,
      )
      .filter((message): message is string => Boolean(message));
    return messages.length > 0 ? messages.join('; ') : null;
  }
  return null;
}

/** Turns a failed API call into a message fit for the UI. */
export function getApiErrorMessage(error: unknown, { fallback, byStatus = {} }: ErrorMessages): string {
  if (!axios.isAxiosError(error)) return fallback;

  if (!error.response) {
    return error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
      ? 'The server took too long to respond. Please try again.'
      : "Can't reach the MeetSense server. Check your connection and try again.";
  }

  const { status, data } = error.response;
  const specific = byStatus[status];
  if (specific) return specific;

  const detail = readDetail(data);
  switch (status) {
    case 400:
    case 404:
      return detail ?? fallback;
    case 422:
      return detail ? `Please check your input: ${detail}` : 'Please check your input and try again.';
    case 429:
      return 'Too many requests. Please wait a minute and try again.';
    case 502:
    case 503:
    case 504:
      return 'The server is temporarily unavailable. Please try again in a moment.';
    default:
      return fallback;
  }
}
