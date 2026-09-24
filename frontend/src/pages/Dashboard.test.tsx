import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMeeting, listMeetings } from '../services/api';
import { apiError } from '../test/apiError';
import type { Meeting } from '../types';
import { Dashboard } from './Dashboard';

vi.mock('../services/api', () => ({
  listMeetings: vi.fn(),
  createMeeting: vi.fn(),
}));

const meeting: Meeting = {
  id: 'm1',
  title: 'Weekly sync',
  status: 'active',
  started_at: '2026-09-23T10:00:00+00:00',
  ended_at: null,
};

beforeEach(() => {
  vi.mocked(listMeetings).mockResolvedValue([]);
  vi.mocked(createMeeting).mockResolvedValue(meeting);
});

async function openNewMeetingForm() {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/meeting/:id/live" element={<p>Live room</p>} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText('No meetings yet');
  await user.click(screen.getByRole('button', { name: 'New Meeting' }));
  return {
    user,
    input: screen.getByLabelText('Meeting Title'),
    submit: screen.getByRole('button', { name: 'Start Meeting' }),
  };
}

describe('New meeting form', () => {
  it('only accepts titles of 1 to 120 characters after trimming', async () => {
    const { user, input, submit } = await openNewMeetingForm();
    expect(submit).toBeDisabled();

    await user.type(input, '   ');
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a title for the meeting.');
    expect(submit).toBeDisabled();

    await user.clear(input);
    await user.click(input);
    await user.paste('a'.repeat(121));
    expect(screen.getByRole('alert')).toHaveTextContent('120 characters or fewer');
    expect(screen.getByText('121/120')).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(submit).toBeDisabled();

    await user.clear(input);
    await user.type(input, '  Weekly sync  ');
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(createMeeting).toHaveBeenCalledWith('Weekly sync');
    expect(await screen.findByText('Live room')).toBeInTheDocument();
  });

  it.each([
    [apiError(429, 'Rate limit exceeded'), "You're creating meetings too quickly"],
    [apiError(422, 'Title must not be blank.'), 'Please check your input: Title must not be blank.'],
    [apiError(503), 'temporarily unavailable'],
  ])('explains failures (%#)', async (error, message) => {
    vi.mocked(createMeeting).mockRejectedValueOnce(error);
    const { user, input, submit } = await openNewMeetingForm();

    await user.type(input, 'Retro');
    await user.click(submit);

    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
    expect(screen.queryByText('Live room')).not.toBeInTheDocument();
  });
});
