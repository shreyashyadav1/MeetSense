import { useState, useEffect, useCallback, useRef } from 'react';
import { listMeetings, createMeeting as apiCreateMeeting } from '../services/api';
import { getApiErrorMessage } from '../services/errors';
import type { Meeting } from '../types';

const REFRESH_INTERVAL_MS = 10_000;

interface UseMeetingsResult {
  meetings: Meeting[];
  /** True until the first response (or failure) arrives. */
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  createMeeting: (title: string) => Promise<Meeting>;
  refresh: () => void;
}

/** The meeting list, refreshed every 10 seconds. */
export function useMeetings(): UseMeetingsResult {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  // Only the newest request may update state, so a slow poll can't overwrite fresher data.
  const load = useCallback((): Promise<void> => {
    const request = ++latestRequest.current;
    return listMeetings().then(
      (data) => {
        if (request !== latestRequest.current) return;
        setMeetings(data);
        setError(null);
        setHasLoaded(true);
      },
      (err: unknown) => {
        if (request !== latestRequest.current) return;
        setError(getApiErrorMessage(err, { fallback: 'Failed to load meetings. Please try again.' }));
        setHasLoaded(true);
      },
    );
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const refresh = useCallback(() => {
    setIsRefreshing(true);
    void load().finally(() => setIsRefreshing(false));
  }, [load]);

  const createMeeting = useCallback(async (title: string): Promise<Meeting> => {
    const meeting = await apiCreateMeeting(title);
    setMeetings((prev) => [meeting, ...prev.filter((m) => m.id !== meeting.id)]);
    return meeting;
  }, []);

  return {
    meetings,
    isLoading: !hasLoaded,
    isRefreshing,
    error,
    createMeeting,
    refresh,
  };
}
