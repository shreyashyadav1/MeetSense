import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../services/api';
import { apiHealthMonitor } from '../services/apiHealth';
import { mockHealth } from '../test/mockHealth';
import { OfflineBanner } from './OfflineBanner';

const MESSAGE = /server is offline right now/;
const originalAdapter = apiClient.defaults.adapter;

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  apiHealthMonitor.reset();
  vi.useRealTimers();
});

describe('OfflineBanner', () => {
  it('renders nothing while the API reports healthy', async () => {
    mockHealth(() => ({ data: { status: 'ok' } }));
    render(<OfflineBanner />);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText(MESSAGE)).not.toBeInTheDocument();
  });

  it('shows the banner on a network error', async () => {
    mockHealth(() => 'network-error');
    render(<OfflineBanner />);

    expect(await screen.findByText(MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'GitHub' })).toHaveAttribute(
      'href',
      'https://github.com/shreyashyadav1/MeetSense',
    );
  });

  it('shows the banner on a 503 (a dependency such as the database is down)', async () => {
    mockHealth(() => ({ status: 503, data: { status: 'error', database: 'down' } }));
    render(<OfflineBanner />);

    expect(await screen.findByText(MESSAGE)).toBeInTheDocument();
  });

  it('hides the banner again once a later check recovers', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let healthy = false;
    mockHealth(() => (healthy ? { data: { status: 'ok' } } : { status: 503 }));
    render(<OfflineBanner />);

    expect(await screen.findByText(MESSAGE)).toBeInTheDocument();

    healthy = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(screen.queryByText(MESSAGE)).not.toBeInTheDocument();
  });

  it('can be dismissed', async () => {
    mockHealth(() => ({ status: 503 }));
    const user = userEvent.setup();
    render(<OfflineBanner />);

    expect(await screen.findByText(MESSAGE)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText(MESSAGE)).not.toBeInTheDocument();
  });
});
