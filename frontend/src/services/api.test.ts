import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { apiClient, summarizeMeeting } from './api';

let requests: InternalAxiosRequestConfig[];
const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  requests = [];
  const adapter: AxiosAdapter = (config) => {
    requests.push(config);
    return Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config });
  };
  apiClient.defaults.adapter = adapter;
});

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
});

describe('summarizeMeeting', () => {
  it('posts to the summarize endpoint', async () => {
    await summarizeMeeting('meeting-1');
    expect(requests[0]).toMatchObject({ method: 'post', url: '/api/meetings/meeting-1/summarize' });
    expect(apiClient.getUri(requests[0])).not.toContain('force');
  });

  it('asks the server to regenerate with force=true', async () => {
    await summarizeMeeting('meeting-1', { force: true });
    expect(apiClient.getUri(requests[0])).toMatch(/\/api\/meetings\/meeting-1\/summarize\?force=true$/);
  });
});
