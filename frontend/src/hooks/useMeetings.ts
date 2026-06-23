import { useState, useEffect, useCallback } from 'react';
import { listMeetings, createMeeting as apiCreateMeeting } from '../services/api';
import type { Meeting } from '../types';

interface UseMeetingsResult {
  meetings: Meeting[];
  isLoading: boolean;
  error: string | null;
  createMeeting: (title: string) => Promise<Meeting>;
  refresh: () => void;
}

export function useMeetings(): UseMeetingsResult {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMeetings = useCallback(async () => {
    try {
      const data = await listMeetings();
      setMeetings(data);
      setError(null);
    } catch (err) {
      console.error('[useMeetings] Failed to fetch meetings:', err);
      setError('Failed to load meetings. Is the backend running?');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    void fetchMeetings();
  }, [fetchMeetings]);

  // Auto-refresh every 10s
  useEffect(() => {
    const timer = setInterval(() => {
      void fetchMeetings();
    }, 10_000);
    return () => clearInterval(timer);
  }, [fetchMeetings]);

  const createMeeting = useCallback(async (title: string): Promise<Meeting> => {
    const meeting = await apiCreateMeeting(title);
    setMeetings((prev) => [meeting, ...prev]);
    return meeting;
  }, []);

  return {
    meetings,
    isLoading,
    error,
    createMeeting,
    refresh: fetchMeetings,
  };
}
