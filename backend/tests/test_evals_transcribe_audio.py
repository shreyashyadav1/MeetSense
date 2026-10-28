from __future__ import annotations

from pathlib import Path

import pytest

from evals import transcribe_audio
from tests.fakes import FakeDeepgram


@pytest.fixture
def fake_deepgram(monkeypatch: pytest.MonkeyPatch) -> type[FakeDeepgram]:
    FakeDeepgram.reset()
    monkeypatch.setattr(transcribe_audio, "DeepgramStreamer", FakeDeepgram)
    monkeypatch.setattr(transcribe_audio, "CHUNK_PACE_SECONDS", 0.0)
    return FakeDeepgram


async def test_transcribe_bytes_streams_chunks_and_collects_final_text(
    fake_deepgram: type[FakeDeepgram],
) -> None:
    # Bigger than CHUNK_BYTES, so it's sent as more than one chunk.
    data = b"\x00" * (transcribe_audio.CHUNK_BYTES * 2 + 100)

    transcript = await transcribe_audio.transcribe_bytes(data, "fake-key")

    (streamer,) = fake_deepgram.instances
    assert len(streamer.audio) == 3  # two full chunks + the remainder
    assert streamer.finished
    # FakeDeepgram.finish() queues one final result naming the frame count.
    assert transcript == f"final words after {len(streamer.audio)} frames"


async def test_transcribe_bytes_ignores_interim_results(
    fake_deepgram: type[FakeDeepgram],
) -> None:
    data = b"\x00" * 10  # smaller than one chunk

    transcript = await transcribe_audio.transcribe_bytes(data, "fake-key")

    # Only one chunk was sent, so only one interim ("heard 1") plus the final;
    # the interim text must not leak into the returned transcript.
    assert "heard" not in transcript
    assert transcript == "final words after 1 frames"


def test_main_skips_cleanly_without_deepgram_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["transcribe_audio", str(tmp_path / "clip.webm")])

    with pytest.raises(SystemExit) as excinfo:
        transcribe_audio.main()

    assert excinfo.value.code == 0
    assert "DEEPGRAM_API_KEY" in capsys.readouterr().err
