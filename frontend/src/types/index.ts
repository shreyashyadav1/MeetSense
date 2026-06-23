export interface Meeting {
  id: string;
  title: string;
  status: 'active' | 'ended';
  started_at: string;
  ended_at?: string;
}

export interface TranscriptSegment {
  id: string;
  meeting_id: string;
  speaker: string;
  text: string;
  timestamp: number;
  confidence: number;
}

export type WSMessage =
  | { type: 'transcript'; data: TranscriptSegment }
  | { type: 'status'; data: { status: string; meeting_id: string } }
  | { type: 'pong' }
  | { type: 'error'; data: { message: string } };

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';
