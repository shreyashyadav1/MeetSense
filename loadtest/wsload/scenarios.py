"""The two load scenarios, run against a locally running backend in mock mode."""

from __future__ import annotations

import asyncio
import random
import time

import httpx

from .client import run_connection
from .metrics import Recorder
from .rest import create_meeting

FANOUT_JOIN_JITTER_SECONDS = 2.0


def _ws_url(ws_base: str, meeting_id: str) -> str:
    return f"{ws_base}/ws/meetings/{meeting_id}/stream"


async def run_ramp(
    recorder: Recorder,
    *,
    http_base: str,
    ws_base: str,
    stages: list[int],
    stage_hold: float,
) -> None:
    """One streaming socket per meeting; ramp the concurrent meeting count through ``stages``.

    Sockets opened at an earlier stage stay open through later stages (this
    models load ramping up, not cycling), so the total held-open duration is
    ``stage_hold * len(stages)`` and every socket shares one end-of-run deadline.
    """
    deadline = time.perf_counter() + stage_hold * len(stages)
    tasks: list[asyncio.Task[None]] = []
    opened = 0
    async with httpx.AsyncClient(base_url=http_base, timeout=10) as http:
        for stage_size in stages:
            recorder.set_stage(str(stage_size))
            to_add = stage_size - opened
            meeting_ids = await asyncio.gather(
                *(
                    create_meeting(http, f"Load ramp meeting {opened + i + 1}")
                    for i in range(to_add)
                )
            )
            for meeting_id in meeting_ids:
                url = _ws_url(ws_base, meeting_id)
                tasks.append(
                    asyncio.create_task(
                        run_connection(recorder, url, role="streamer", deadline=deadline)
                    )
                )
            opened = stage_size
            print(f"[ramp] reached {stage_size} concurrent meetings; holding {stage_hold:.0f}s")
            await asyncio.sleep(stage_hold)
    await asyncio.gather(*tasks)


async def run_fanout(
    recorder: Recorder,
    *,
    http_base: str,
    ws_base: str,
    meetings: int,
    viewers: int,
    hold: float,
) -> None:
    """``meetings`` meetings at once, each with one streamer and ``viewers`` viewer sockets."""
    recorder.set_stage(f"fanout-{viewers}v")
    deadline = time.perf_counter() + hold + FANOUT_JOIN_JITTER_SECONDS
    tasks: list[asyncio.Task[None]] = []
    async with httpx.AsyncClient(base_url=http_base, timeout=10) as http:
        for i in range(meetings):
            meeting_id = await create_meeting(http, f"Load fanout meeting {i + 1}")
            url = _ws_url(ws_base, meeting_id)
            tasks.append(
                asyncio.create_task(
                    run_connection(recorder, url, role="streamer", deadline=deadline)
                )
            )
            tasks.extend(
                asyncio.create_task(_delayed_viewer(recorder, url, deadline))
                for _ in range(viewers)
            )
    print(f"[fanout] {meetings}x{viewers} viewers ({len(tasks)} sockets); holding {hold:.0f}s")
    await asyncio.gather(*tasks)


async def _delayed_viewer(recorder: Recorder, url: str, deadline: float) -> None:
    """A viewer that trickles in over a few seconds instead of everyone joining at once."""
    await asyncio.sleep(random.uniform(0, FANOUT_JOIN_JITTER_SECONDS))
    await run_connection(recorder, url, role="viewer", deadline=deadline)
