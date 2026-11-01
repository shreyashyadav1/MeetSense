"""CLI entry point. Run from the ``loadtest/`` directory, for example:

    ../backend/.venv/bin/python -m wsload.run ramp --server-pid 12345
    ../backend/.venv/bin/python -m wsload.run fanout --server-pid 12345 --viewers 10

See ``loadtest/README.md`` for the full scenario descriptions and setup steps.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from . import scenarios
from .metrics import Recorder, format_summary, summarize
from .monitor import ResourceMonitor

RESULTS_DIR = Path("results")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MeetSense WebSocket load generator")
    parser.add_argument("scenario", choices=["ramp", "fanout"])
    parser.add_argument("--http-base", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8000")
    parser.add_argument(
        "--server-pid", type=int, default=None, help="backend PID, to sample CPU/RSS with ps"
    )
    parser.add_argument(
        "--out", default=None, help="output JSON path (default: results/<auto>.json)"
    )
    parser.add_argument(
        "--stages", default="10,50,100,200", help="ramp: comma-separated meeting counts"
    )
    parser.add_argument(
        "--stage-hold", type=float, default=20.0, help="ramp: seconds held per stage"
    )
    parser.add_argument("--meetings", type=int, default=15, help="fanout: concurrent meetings")
    parser.add_argument("--viewers", type=int, default=8, help="fanout: viewer sockets per meeting")
    parser.add_argument("--fanout-hold", type=float, default=30.0, help="fanout: seconds held")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict:
    recorder = Recorder()
    monitor = ResourceMonitor(args.server_pid) if args.server_pid else None
    if monitor:
        monitor.start()

    started_at = time.time()
    if args.scenario == "ramp":
        stages = [int(value) for value in args.stages.split(",")]
        await scenarios.run_ramp(
            recorder,
            http_base=args.http_base,
            ws_base=args.ws_base,
            stages=stages,
            stage_hold=args.stage_hold,
        )
    else:
        await scenarios.run_fanout(
            recorder,
            http_base=args.http_base,
            ws_base=args.ws_base,
            meetings=args.meetings,
            viewers=args.viewers,
            hold=args.fanout_hold,
        )
    finished_at = time.time()

    resource_usage = None
    if monitor:
        await monitor.stop()
        resource_usage = monitor.summary()

    return summarize(
        recorder, resource_usage, started_at=started_at, finished_at=finished_at, args=vars(args)
    )


def main() -> None:
    args = _parse_args()
    report = asyncio.run(_run(args))
    print()
    print(format_summary(report))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = (
        Path(args.out) if args.out else RESULTS_DIR / f"{args.scenario}-{int(time.time())}.json"
    )
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nRaw data written to {out_path}")


if __name__ == "__main__":
    main()
