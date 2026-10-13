import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { endMeeting, getMeeting } from '../services/api';
import { FakeWebSocket, transcriptFrame } from '../test/fakeWebSocket';
import type { Meeting } from '../types';
import { MeetingRoom } from './MeetingRoom';

vi.mock('../services/api', () => ({
  getMeeting: vi.fn(),
  endMeeting: vi.fn(),
}));

const meeting: Meeting = {
  id: 'm1',
  title: 'Design review',
  status: 'active',
  started_at: '2026-09-23T10:00:00+00:00',
  ended_at: null,
};

const DEMO_BADGE = 'Demo mode — simulated transcript';

beforeEach(() => {
  FakeWebSocket.install();
  vi.mocked(getMeeting).mockResolvedValue(meeting);
  vi.mocked(endMeeting).mockResolvedValue({ ...meeting, status: 'ended' });
});

async function renderRoom() {
  render(
    <MemoryRouter initialEntries={['/meeting/m1/live']}>
      <Routes>
        <Route path="/meeting/:id/live" element={<MeetingRoom />} />
        <Route path="/meeting/:id" element={<p>Meeting details</p>} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('heading', { name: 'Design review' });
  return FakeWebSocket.latest;
}

describe('MeetingRoom', () => {
  it('shows the demo-mode badge when the server streams a simulated transcript', async () => {
    const ws = await renderRoom();
    expect(screen.queryByText(DEMO_BADGE)).not.toBeInTheDocument();

    act(() => {
      ws.accept('mock');
      ws.receive(transcriptFrame({ speaker: 'Alice', text: 'Good morning everyone.' }));
    });

    expect(screen.getByText(DEMO_BADGE)).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('Good morning everyone.')).toBeInTheDocument();
  });

  it('does not show the badge for real transcription', async () => {
    const ws = await renderRoom();
    act(() => ws.accept('deepgram'));

    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.queryByText(DEMO_BADGE)).not.toBeInTheDocument();
  });

  it('shows the server error and a Retry button once the stream gives up', async () => {
    const ws = await renderRoom();
    act(() => {
      ws.accept();
      ws.receive({
        type: 'error',
        code: 'session_time_limit',
        message: 'Live sessions are limited to 15 minutes.',
        retryable: false,
      });
    });

    expect(screen.getByRole('alert')).toHaveTextContent('Live sessions are limited to 15 minutes.');
    expect(screen.getByText('Disconnected')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(screen.getByText('Connecting')).toBeInTheDocument();
  });

  it('sends stop and waits for the flush before ending the meeting', async () => {
    const ws = await renderRoom();
    act(() => ws.accept());

    await userEvent.click(screen.getByRole('button', { name: 'End Meeting' }));
    expect(ws.sentMessages).toContainEqual({ type: 'stop' });
    expect(endMeeting).not.toHaveBeenCalled();

    act(() => ws.receive({ type: 'status', status: 'stopped' }));

    await waitFor(() => expect(endMeeting).toHaveBeenCalledWith('m1'));
    expect(await screen.findByText('Meeting details')).toBeInTheDocument();
  });
});
