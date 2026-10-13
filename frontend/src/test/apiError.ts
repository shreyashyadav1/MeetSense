import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';

/** An AxiosError for an HTTP error response with a FastAPI-style body. */
export function apiError(status: number, detail?: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  return new AxiosError(`Request failed with status code ${String(status)}`, 'ERR_BAD_RESPONSE', config, {}, {
    status,
    statusText: '',
    headers: {},
    config,
    data: detail === undefined ? {} : { detail },
  });
}

/** An AxiosError without a response, as produced by network failures and timeouts. */
export function networkError(code: string = AxiosError.ERR_NETWORK): AxiosError {
  return new AxiosError('Network Error', code);
}
