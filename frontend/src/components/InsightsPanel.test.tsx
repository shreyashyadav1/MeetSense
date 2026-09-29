import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getInsights, summarizeMeeting } from '../services/api';
import { apiError } from '../test/apiError';
import type { MeetingInsights, MeetingStatus } from '../types';
import { InsightsPanel } from './InsightsPanel';

vi.mock('../services/api', () => ({
  getInsights: vi.fn(),
  summarizeMeeting: vi.fn(),
}));

function insights(summary: string): MeetingInsights {
  return {
    id: 'i1',
    meeting_id: 'm1',
    summary,
    action_items: ['Ship the beta'],
    decisions: [],
    questions_raised: [],
    follow_up_email: 'Hi team,',
    generated_at: '2026-09-23T11:00:00+00:00',
  };
}

beforeEach(() => {
  vi.mocked(getInsights).mockRejectedValue(apiError(404, 'No insights found.'));
  vi.mocked(summarizeMeeting).mockResolvedValue(insights('Fresh summary.'));
});

function renderPanel(meetingStatus: MeetingStatus = 'ended', hasTranscript = true) {
  render(<InsightsPanel meetingId="m1" meetingStatus={meetingStatus} hasTranscript={hasTranscript} />);
  return userEvent.setup();
}

describe('InsightsPanel', () => {
  it('generates insights on request without forcing regeneration', async () => {
    const user = renderPanel();

    await user.click(await screen.findByRole('button', { name: 'Generate AI Insights' }));

    expect(summarizeMeeting).toHaveBeenCalledWith('m1', { force: false });
    expect(await screen.findByText('Fresh summary.')).toBeInTheDocument();
  });

  it('regenerates saved insights with force=true', async () => {
    vi.mocked(getInsights).mockResolvedValue(insights('Old summary.'));
    const user = renderPanel();

    expect(await screen.findByText('Old summary.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Regenerate' }));

    expect(summarizeMeeting).toHaveBeenCalledWith('m1', { force: true });
    expect(await screen.findByText('Fresh summary.')).toBeInTheDocument();
    expect(screen.queryByText('Old summary.')).not.toBeInTheDocument();
  });

  it('uses the meeting status, not just the transcript, to allow generation', async () => {
    renderPanel('active', true);

    const button = await screen.findByRole('button', { name: 'Generate AI Insights' });
    expect(button).toBeDisabled();
    expect(screen.getByText('End the meeting first to generate insights.')).toBeInTheDocument();
  });

  it('explains when there is nothing to summarize', async () => {
    renderPanel('ended', false);

    expect(await screen.findByRole('button', { name: 'Generate AI Insights' })).toBeDisabled();
    expect(screen.getByText('This meeting has no transcript to summarize.')).toBeInTheDocument();
  });

  it.each([
    [400, 'No transcript available to summarize.', 'No transcript available to summarize.'],
    [429, 'Rate limit exceeded: 5 per 1 minute', 'a few times per minute'],
    [502, 'AI service error: upstream timeout', 'AI provider failed'],
    [503, 'AI service not configured.', 'not configured on this server'],
  ])('shows a friendly message for a %i from summarize', async (status, detail, message) => {
    vi.mocked(summarizeMeeting).mockRejectedValueOnce(apiError(status, detail));
    const user = renderPanel();

    await user.click(await screen.findByRole('button', { name: 'Generate AI Insights' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Generate AI Insights' })).toBeEnabled();
  });

  it('keeps the current insights visible when regeneration fails', async () => {
    vi.mocked(getInsights).mockResolvedValue(insights('Old summary.'));
    vi.mocked(summarizeMeeting).mockRejectedValueOnce(apiError(502));
    const user = renderPanel();

    await user.click(await screen.findByRole('button', { name: 'Regenerate' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('AI provider failed');
    expect(screen.getByText('Old summary.')).toBeInTheDocument();
  });

  it('reports a failure to load saved insights but still offers generation', async () => {
    vi.mocked(getInsights).mockRejectedValue(apiError(500));
    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load saved insights.');
    expect(screen.getByRole('button', { name: 'Generate AI Insights' })).toBeEnabled();
  });
});
