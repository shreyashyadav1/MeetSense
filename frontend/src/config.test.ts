import { describe, expect, it } from 'vitest';
import { resolveApiConfig } from './config';

const httpPage = { protocol: 'http:', host: 'localhost:8080' };
const httpsPage = { protocol: 'https:', host: 'meet.example.com' };

describe('resolveApiConfig', () => {
  it('defaults to the local backend when VITE_API_URL is unset', () => {
    expect(resolveApiConfig(undefined, httpsPage)).toEqual({
      apiBaseUrl: 'http://localhost:8000',
      wsBaseUrl: 'ws://localhost:8000',
    });
  });

  it('derives ws/wss from an explicit http(s) origin and drops trailing slashes', () => {
    expect(resolveApiConfig('https://api.example.com/', httpPage)).toEqual({
      apiBaseUrl: 'https://api.example.com',
      wsBaseUrl: 'wss://api.example.com',
    });
    expect(resolveApiConfig('http://10.0.0.5:8000', httpPage).wsBaseUrl).toBe('ws://10.0.0.5:8000');
  });

  it('uses same-origin URLs when VITE_API_URL is empty', () => {
    expect(resolveApiConfig('', httpPage)).toEqual({
      apiBaseUrl: '',
      wsBaseUrl: 'ws://localhost:8080',
    });
    expect(resolveApiConfig('  ', httpsPage)).toEqual({
      apiBaseUrl: '',
      wsBaseUrl: 'wss://meet.example.com',
    });
  });
});
