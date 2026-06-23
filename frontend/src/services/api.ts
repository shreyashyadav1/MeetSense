import axios from 'axios';
import type { Meeting, TranscriptSegment } from '../types';

const client = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

export async function createMeeting(title: string): Promise<Meeting> {
  const response = await client.post<Meeting>('/api/meetings', { title });
  return response.data;
}

export async function listMeetings(): Promise<Meeting[]> {
  const response = await client.get<Meeting[]>('/api/meetings');
  return response.data;
}

export async function getMeeting(id: string): Promise<Meeting> {
  const response = await client.get<Meeting>(`/api/meetings/${id}`);
  return response.data;
}

export async function endMeeting(id: string): Promise<Meeting> {
  const response = await client.post<Meeting>(`/api/meetings/${id}/end`);
  return response.data;
}

export async function getTranscript(id: string): Promise<TranscriptSegment[]> {
  const response = await client.get<TranscriptSegment[]>(`/api/meetings/${id}/transcript`);
  return response.data;
}
