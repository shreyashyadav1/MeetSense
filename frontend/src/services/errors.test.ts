import { AxiosError } from 'axios';
import { describe, expect, it } from 'vitest';
import { apiError, networkError } from '../test/apiError';
import { getApiErrorMessage, getErrorStatus } from './errors';

const messages = { fallback: 'Something went wrong.' };

describe('getApiErrorMessage', () => {
  it('uses the server detail for 400 and 404', () => {
    expect(getApiErrorMessage(apiError(400, 'No transcript available.'), messages)).toBe(
      'No transcript available.',
    );
    expect(getApiErrorMessage(apiError(404), messages)).toBe('Something went wrong.');
  });

  it('explains validation errors in either detail format', () => {
    expect(getApiErrorMessage(apiError(422, 'Title is too long.'), messages)).toBe(
      'Please check your input: Title is too long.',
    );
    const fastApiDetail = [{ loc: ['body', 'title'], msg: 'String should have at most 120 characters' }];
    expect(getApiErrorMessage(apiError(422, fastApiDetail), messages)).toBe(
      'Please check your input: String should have at most 120 characters',
    );
  });

  it('has friendly defaults for rate limiting and upstream failures', () => {
    expect(getApiErrorMessage(apiError(429, 'Rate limit exceeded: 5 per 1 minute'), messages)).toMatch(
      /wait a minute/,
    );
    expect(getApiErrorMessage(apiError(502, 'AI service error: boom'), messages)).toMatch(
      /temporarily unavailable/,
    );
    expect(getApiErrorMessage(apiError(503), messages)).toMatch(/temporarily unavailable/);
  });

  it('lets callers word specific statuses', () => {
    const custom = { ...messages, byStatus: { 503: 'Insights are not configured.' } };
    expect(getApiErrorMessage(apiError(503), custom)).toBe('Insights are not configured.');
  });

  it('distinguishes unreachable servers and timeouts', () => {
    expect(getApiErrorMessage(networkError(), messages)).toMatch(/can't reach/i);
    expect(getApiErrorMessage(networkError(AxiosError.ECONNABORTED), messages)).toMatch(/too long/);
  });

  it('falls back for non-HTTP errors', () => {
    expect(getApiErrorMessage(new Error('boom'), messages)).toBe('Something went wrong.');
    expect(getErrorStatus(new Error('boom'))).toBeNull();
    expect(getErrorStatus(apiError(409))).toBe(409);
  });
});
