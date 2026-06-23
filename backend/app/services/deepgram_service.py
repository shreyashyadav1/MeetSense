import asyncio
import json
import uuid
import websockets
from typing import AsyncGenerator, Optional

from app.models.schemas import TranscriptSegment
from app.core.config import settings

DEEPGRAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en-US"
    "&encoding=opus"
    "&sample_rate=48000"
    "&channels=1"
    "&punctuate=true"
    "&interim_results=true"
    "&utterance_end_ms=1000"
    "&vad_events=true"
)


class DeepgramStreamer:
    """
    Bridges the FastAPI WebSocket (receiving audio from browser) to
    Deepgram's streaming WebSocket (sending audio, receiving transcripts).

    Usage:
        streamer = DeepgramStreamer(meeting_id)
        await streamer.connect()

        # In one task: feed audio
        await streamer.send_audio(chunk_bytes)

        # In another task: read transcripts
        async for segment in streamer.transcript_stream():
            ...

        await streamer.close()
    """

    def __init__(self, meeting_id: str):
        self.meeting_id = meeting_id
        self._dg_ws = None
        self._transcript_queue: asyncio.Queue[Optional[TranscriptSegment]] = asyncio.Queue()
        self._receiver_task: Optional[asyncio.Task] = None
        self._start_time: float = 0
        self._speaker_counter: dict[str, str] = {}  # channel/word_index -> speaker label
        self._segment_count = 0

    async def connect(self):
        headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
        self._dg_ws = await websockets.connect(DEEPGRAM_URL, extra_headers=headers)
        import time
        self._start_time = time.time()
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def send_audio(self, chunk: bytes):
        if self._dg_ws:
            await self._dg_ws.send(chunk)

    async def close(self):
        if self._dg_ws:
            try:
                # Send CloseStream message to Deepgram
                await self._dg_ws.send(json.dumps({"type": "CloseStream"}))
                await asyncio.sleep(0.5)
            except Exception:
                pass
            await self._dg_ws.close()
        if self._receiver_task:
            self._receiver_task.cancel()
        await self._transcript_queue.put(None)  # sentinel

    async def _receive_loop(self):
        import time
        try:
            async for raw in self._dg_ws:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "Results":
                    channel = msg.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if not alternatives:
                        continue

                    transcript = alternatives[0].get("transcript", "").strip()
                    if not transcript:
                        continue

                    is_final = msg.get("is_final", False)

                    # Only emit final results as segments (interim shown differently)
                    if is_final:
                        self._segment_count += 1
                        speaker = self._get_speaker(msg, self._segment_count)
                        confidence = alternatives[0].get("confidence", 0.95)

                        segment = TranscriptSegment(
                            id=str(uuid.uuid4()),
                            meeting_id=self.meeting_id,
                            speaker=speaker,
                            text=transcript,
                            timestamp=round(time.time() - self._start_time, 2),
                            confidence=round(confidence, 3),
                            is_final=True,
                        )
                        await self._transcript_queue.put(segment)
                    else:
                        # Emit interim result with is_final=False
                        confidence = alternatives[0].get("confidence", 0.0)
                        segment = TranscriptSegment(
                            id="interim-" + self.meeting_id,
                            meeting_id=self.meeting_id,
                            speaker="",
                            text=transcript,
                            timestamp=round(time.time() - self._start_time, 2),
                            confidence=round(confidence, 3),
                            is_final=False,
                        )
                        await self._transcript_queue.put(segment)

        except Exception as e:
            await self._transcript_queue.put(None)

    def _get_speaker(self, msg: dict, count: int) -> str:
        """Simple speaker labeling — uses Deepgram diarization if available."""
        names = ["Speaker 1", "Speaker 2", "Speaker 3", "Speaker 4"]
        try:
            words = msg["channel"]["alternatives"][0].get("words", [])
            if words and "speaker" in words[0]:
                idx = words[0]["speaker"]
                return names[idx % len(names)]
        except Exception:
            pass
        return names[(count - 1) % len(names)]

    async def transcript_stream(self) -> AsyncGenerator[TranscriptSegment, None]:
        while True:
            segment = await self._transcript_queue.get()
            if segment is None:
                break
            yield segment
