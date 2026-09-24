import axios from 'axios';
import { apiConfig } from '../config';
import type { Meeting, TranscriptSegment, MeetingInsights } from '../types';

export const apiClient = axios.create({
  baseURL: apiConfig.apiBaseUrl,
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

const meetingPath = (id: string) => `/api/meetings/${encodeURIComponent(id)}`;

export async function createMeeting(title: string): Promise<Meeting> {
  const response = await apiClient.post<Meeting>('/api/meetings', { title });
  return response.data;
}

export async function listMeetings(): Promise<Meeting[]> {
  const response = await apiClient.get<Meeting[]>('/api/meetings');
  return response.data;
}

export async function getMeeting(id: string): Promise<Meeting> {
  const response = await apiClient.get<Meeting>(meetingPath(id));
  return response.data;
}

export async function endMeeting(id: string): Promise<Meeting> {
  const response = await apiClient.post<Meeting>(`${meetingPath(id)}/end`);
  return response.data;
}

export async function getTranscript(id: string): Promise<TranscriptSegment[]> {
  const response = await apiClient.get<TranscriptSegment[]>(`${meetingPath(id)}/transcript`);
  return response.data;
}

/** Generates insights; `force` regenerates them even if saved ones exist. */
export async function summarizeMeeting(
  id: string,
  { force = false }: { force?: boolean } = {},
): Promise<MeetingInsights> {
  const response = await apiClient.post<MeetingInsights>(`${meetingPath(id)}/summarize`, undefined, {
    params: force ? { force: true } : undefined,
  });
  return response.data;
}

export async function getInsights(id: string): Promise<MeetingInsights> {
  const response = await apiClient.get<MeetingInsights>(`${meetingPath(id)}/insights`);
  return response.data;
}
