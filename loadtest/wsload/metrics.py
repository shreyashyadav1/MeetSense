"""Records raw samples during a run and summarizes them into a report."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile, ``p`` in [0, 1]. NaN for an empty list."""
    if not values:
        return float("nan")
    data = sorted(values)
    k = (len(data) - 1) * p
    lower, upper = math.floor(k), math.ceil(k)
    if lower == upper:
        return data[int(k)]
    return data[lower] + (data[upper] - data[lower]) * (k - lower)


@dataclass
class Recorder:
    """Shared, append-only sink every simulated connection writes samples into.

    Not thread-safe, but every caller runs on the same asyncio event loop, so
    plain list appends need no lock. Samples are tagged with ``current_stage``
    as of the moment they're recorded (not when the connection was opened), so
    a long-lived connection's later samples count toward a later stage.
    """

    current_stage: str = "unstaged"
    connects: list[dict[str, Any]] = field(default_factory=list)
    connecteds: list[dict[str, Any]] = field(default_factory=list)
    closes: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    ping_rtts: list[dict[str, Any]] = field(default_factory=list)
    transcript_latencies: list[dict[str, Any]] = field(default_factory=list)
    sequence_summaries: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[dict[str, Any]] = field(default_factory=list)

    def set_stage(self, name: str) -> None:
        self.current_stage = name

    def _append(self, bucket: list[dict[str, Any]], role: str, **fields: Any) -> None:
        bucket.append({"stage": self.current_stage, "role": role, **fields})

    def connect(self, role: str, ms: float) -> None:
        self._append(self.connects, role, ms=ms)

    def connected(self, role: str, ms: float) -> None:
        self._append(self.connecteds, role, ms=ms)

    def close(self, role: str, code: int | None, reason: str) -> None:
        self._append(self.closes, role, code=code, reason=reason)

    def error(self, role: str, code: str) -> None:
        self._append(self.errors, role, code=code)

    def ping_rtt(self, role: str, ms: float) -> None:
        self._append(self.ping_rtts, role, ms=ms)

    def transcript_latency(self, role: str, ms: float) -> None:
        self._append(self.transcript_latencies, role, ms=ms)

    def sequence_summary(self, role: str, *, finals: int, gaps: int, duplicates: int) -> None:
        self._append(self.sequence_summaries, role, finals=finals, gaps=gaps, duplicates=duplicates)

    def exception(self, role: str, text: str) -> None:
        self._append(self.exceptions, role, text=text)


def _stage_groups(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["stage"], []).append(record)
    return groups


def _timing_stats(records: list[dict[str, Any]]) -> dict[str, float | int]:
    values = [r["ms"] for r in records]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "p50": round(percentile(values, 0.50), 2),
        "p95": round(percentile(values, 0.95), 2),
        "p99": round(percentile(values, 0.99), 2),
        "max": round(max(values), 2),
        "mean": round(statistics.fmean(values), 2),
    }


def _stage_sort_key(stage: str) -> tuple[int, str]:
    digits = "".join(ch for ch in stage if ch.isdigit())
    return (int(digits) if digits else -1, stage)


def summarize(
    recorder: Recorder,
    resource_usage: dict[str, float | int] | None,
    *,
    started_at: float,
    finished_at: float,
    args: dict[str, Any],
) -> dict[str, Any]:
    connects_by_stage = _stage_groups(recorder.connects)
    connecteds_by_stage = _stage_groups(recorder.connecteds)
    ping_by_stage = _stage_groups(recorder.ping_rtts)
    latency_by_stage = _stage_groups(recorder.transcript_latencies)
    stages = sorted(
        {*connects_by_stage, *connecteds_by_stage, *ping_by_stage, *latency_by_stage},
        key=_stage_sort_key,
    )

    by_stage = {
        stage: {
            "connect_ms": _timing_stats(connects_by_stage.get(stage, [])),
            "connected_ms": _timing_stats(connecteds_by_stage.get(stage, [])),
            "ping_rtt_ms": _timing_stats(ping_by_stage.get(stage, [])),
            "transcript_latency_ms": _timing_stats(latency_by_stage.get(stage, [])),
        }
        for stage in stages
    }

    close_codes = Counter(
        f"{r['code']} {r['reason']}".strip() if r["reason"] else str(r["code"])
        for r in recorder.closes
    )
    error_codes = Counter(r["code"] for r in recorder.errors)
    total_finals = sum(r["finals"] for r in recorder.sequence_summaries)
    total_gaps = sum(r["gaps"] for r in recorder.sequence_summaries)
    total_dupes = sum(r["duplicates"] for r in recorder.sequence_summaries)

    return {
        "started_at": datetime.fromtimestamp(started_at, tz=UTC).isoformat(),
        "finished_at": datetime.fromtimestamp(finished_at, tz=UTC).isoformat(),
        "duration_seconds": round(finished_at - started_at, 1),
        "args": args,
        "connections_opened": len(recorder.connects),
        "connections_failed_to_open": len(recorder.exceptions),
        "stages": by_stage,
        "close_codes": dict(close_codes),
        "error_codes": dict(error_codes),
        "exceptions": [e["text"] for e in recorder.exceptions][:50],
        "sequence_totals": {
            "finals_received": total_finals,
            "gaps": total_gaps,
            "duplicates": total_dupes,
        },
        "resource_usage": resource_usage,
    }


def format_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Run {report['started_at']} -> {report['finished_at']} "
        f"({report['duration_seconds']}s, {report['connections_opened']} connections opened, "
        f"{report['connections_failed_to_open']} failed to open)",
        "",
    ]
    header = (
        f"{'stage':<14}{'metric':<22}{'n':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}{'mean':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for stage, metrics in report["stages"].items():
        for name, stats in metrics.items():
            if not stats.get("count"):
                continue
            lines.append(
                f"{stage:<14}{name:<22}{stats['count']:>6}{stats['p50']:>9}{stats['p95']:>9}"
                f"{stats['p99']:>9}{stats['max']:>9}{stats['mean']:>9}"
            )
    lines.append("")
    lines.append(f"Close codes: {report['close_codes']}")
    lines.append(f"Error codes: {report['error_codes']}")
    lines.append(f"Sequences:   {report['sequence_totals']}")
    if report["exceptions"]:
        lines.append(f"Exceptions ({len(report['exceptions'])}): {report['exceptions'][:5]}")
    if report["resource_usage"]:
        lines.append(f"Backend resource usage: {report['resource_usage']}")
    return "\n".join(lines)
