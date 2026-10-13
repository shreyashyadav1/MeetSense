"""Samples the backend process's CPU% and RSS while a scenario runs.

Uses ``ps`` (BSD/macOS flavor) rather than a new dependency like psutil, since
this only ever runs on the developer's own machine for a one-off load test.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess


class ResourceMonitor:
    def __init__(self, pid: int, interval: float = 1.0) -> None:
        self.pid = pid
        self.interval = interval
        self.samples: list[tuple[float, float]] = []  # (cpu_percent, rss_mb)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="resource-monitor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._sample()
            if sample is not None:
                self.samples.append(sample)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), self.interval)

    def _sample(self) -> tuple[float, float] | None:
        try:
            output = subprocess.run(
                ["ps", "-o", "%cpu=,rss=", "-p", str(self.pid)],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if not output:
            return None
        cpu_str, rss_str = output.split()
        return float(cpu_str), float(rss_str) / 1024  # KB -> MB

    def summary(self) -> dict[str, float | int]:
        if not self.samples:
            return {"samples": 0}
        cpu = [s[0] for s in self.samples]
        rss = [s[1] for s in self.samples]
        return {
            "samples": len(self.samples),
            "cpu_percent_mean": round(sum(cpu) / len(cpu), 1),
            "cpu_percent_max": round(max(cpu), 1),
            "rss_mb_mean": round(sum(rss) / len(rss), 1),
            "rss_mb_max": round(max(rss), 1),
        }
