"""Turn a local audio file into a hypothesis transcript via Deepgram, for WER.

Reuses ``DeepgramStreamer`` (``app/services/deepgram_service.py``) exactly as
the live backend does, so the transcript this produces reflects what a real
meeting stream would have heard - it just feeds the file's bytes instead of
a browser's MediaRecorder. Needs ``DEEPGRAM_API_KEY``; skips cleanly (a clear
message, exit code 0) when it's unset. No audio or datasets ship with this
repo - point it at your own file.

Usage (see backend/evals/README.md)::

    DEEPGRAM_API_KEY=... python -m evals.transcribe_audio meeting.webm > hypothesis.txt
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from app.services.deepgram_service import DeepgramStreamer
from app.services.transcription import TranscriptionUnavailableError

# Any small chunk size works; Deepgram reads the container/codec from the
# first frame, same as the live WebSocket endpoint does.
CHUNK_BYTES = 32_000
CHUNK_PACE_SECONDS = 0.1


async def transcribe_bytes(data: bytes, api_key: str) -> str:
    """Feed ``data`` to Deepgram in chunks and return the joined final text.

    Takes bytes rather than a path so this coroutine never blocks the event
    loop on file I/O; ``main()`` reads the file synchronously beforehand.
    """
    streamer = DeepgramStreamer(api_key)
    await streamer.connect()
    final_lines: list[str] = []

    async def consume() -> None:
        try:
            async for result in streamer.results():
                if result.is_final and result.text:
                    final_lines.append(result.text)
        except TranscriptionUnavailableError as error:
            print(f"Deepgram stream ended early: {error}", file=sys.stderr)

    consumer = asyncio.create_task(consume())
    try:
        for offset in range(0, len(data), CHUNK_BYTES):
            await streamer.send_audio(data[offset : offset + CHUNK_BYTES])
            await asyncio.sleep(CHUNK_PACE_SECONDS)
        await streamer.finish()
        await consumer
    finally:
        await streamer.aclose()
    return " ".join(final_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_file", type=Path, help="a local audio file (webm/ogg/wav/etc.)")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        print(
            "DEEPGRAM_API_KEY is not set; skipping. Set it to transcribe real audio through "
            "Deepgram, or write a hypothesis transcript by hand from any ASR output and run "
            "evals.wer directly.",
            file=sys.stderr,
        )
        sys.exit(0)
    if not args.audio_file.exists():
        print(f"No such file: {args.audio_file}", file=sys.stderr)
        sys.exit(1)

    try:
        transcript = asyncio.run(transcribe_bytes(args.audio_file.read_bytes(), api_key))
    except TranscriptionUnavailableError as error:
        print(f"Could not transcribe via Deepgram: {error}", file=sys.stderr)
        sys.exit(1)
    print(transcript)


if __name__ == "__main__":
    main()
