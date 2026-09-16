"""Command-line interface entry point for Titan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

# Enable direct execution via 'python src/titan/cli.py'
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from titan import __version__
from titan.config import TitanConfig
from titan.job import Job
from titan.runtime import StaticRuntime


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="titan",
        description="Titan: Experimental distributed-systems research platform.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show Titan version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 'status' subcommand
    status_parser = subparsers.add_parser(
        "status",
        help="Display the current project milestone and runtime configuration.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status information as JSON.",
    )

    # 'run' subcommand
    run_parser = subparsers.add_parser(
        "run",
        help="Execute a workload using the static baseline multi-process runtime.",
    )
    run_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=2,
        help="Number of worker processes to spawn (e.g. 1, 2, 4, 8). Default: 2.",
    )
    run_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=100,
        help="Total number of jobs to submit. Default: 100.",
    )
    run_parser.add_argument(
        "--work-units",
        "-u",
        type=int,
        default=1000,
        help="Deterministic computation units per job. Default: 1000.",
    )
    run_parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=None,
        help="Optional timeout in seconds for workload completion.",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output metrics formatted as JSON.",
    )

    return parser


def handle_status(json_output: bool = False) -> int:
    """Print the current system status and active configuration."""
    config = TitanConfig.from_env()

    if json_output:
        data = {
            "name": "Titan",
            "version": __version__,
            "milestone": "Milestone 2: Static Baseline Runtime",
            "environment": config.environment,
            "log_level": config.log_level,
            "status": "ready",
        }
        print(json.dumps(data, indent=2))
    else:
        print("Titan Research Platform")
        print(f"  Version:     {__version__}")
        print("  Milestone:   2 (Static Baseline Runtime)")
        print(f"  Environment: {config.environment}")
        print(f"  Log Level:   {config.log_level}")
        print("  State:       Operational (Static Runtime Ready)")

    return 0


def handle_run(
    workers: int,
    jobs_count: int,
    work_units: int,
    timeout: float | None,
    json_output: bool,
) -> int:
    """Execute a workload batch and output performance metrics."""
    if workers < 1:
        print(f"Error: --workers must be at least 1, got {workers}", file=sys.stderr)
        return 1
    if jobs_count < 1:
        print(f"Error: --jobs must be at least 1, got {jobs_count}", file=sys.stderr)
        return 1
    if work_units < 1:
        print(f"Error: --work-units must be at least 1, got {work_units}", file=sys.stderr)
        return 1

    jobs = [
        Job.create(job_id=f"job-{i:06d}", work_units=work_units)
        for i in range(jobs_count)
    ]

    runtime = StaticRuntime(num_workers=workers)
    try:
        metrics, _ = runtime.run_workload(jobs, timeout=timeout)
    finally:
        runtime.stop()

    if json_output:
        payload = {
            "config": {
                "workers": workers,
                "jobs": jobs_count,
                "work_units": work_units,
            },
            "metrics": metrics.to_dict(),
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 60)
        print("Titan Static Baseline Runtime Execution")
        print("=" * 60)
        print(f"  Worker Processes:       {workers}")
        print(f"  Jobs Submitted:         {metrics.total_submitted}")
        print(f"  Jobs Completed:         {metrics.total_completed}")
        print(f"  Jobs Failed:            {metrics.total_failed}")
        print(f"  Wall-Clock Time:        {metrics.wall_clock_duration:.4f} s")
        print(f"  Throughput:             {metrics.throughput:.2f} jobs/s")
        print(f"  Average Latency:        {metrics.avg_latency * 1000:.3f} ms")
        print(f"  p50 Latency:            {metrics.p50_latency * 1000:.3f} ms")
        print(f"  p95 Latency:            {metrics.p95_latency * 1000:.3f} ms")
        print(f"  p99 Latency:            {metrics.p99_latency * 1000:.3f} ms")
        print(f"  Avg Worker Compute:     {metrics.avg_processing_time * 1000:.3f} ms")
        print("=" * 60)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main execution entry point."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if args.command == "status":
        return handle_status(json_output=args.json)

    if args.command == "run":
        return handle_run(
            workers=args.workers,
            jobs_count=args.jobs,
            work_units=args.work_units,
            timeout=args.timeout,
            json_output=args.json,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
