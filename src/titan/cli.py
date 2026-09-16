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
from titan.runtime import FailureConfig, StaticRuntime


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
        help="Execute a workload using the static multi-process runtime with failure injection.",
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
        help="Total number of unique jobs to submit. Default: 100.",
    )
    run_parser.add_argument(
        "--work-units",
        "-u",
        type=int,
        default=1000,
        help="Deterministic computation units per job. Default: 1000.",
    )
    run_parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts per job upon worker failure. Default: 3.",
    )
    run_parser.add_argument(
        "--kill-worker",
        type=str,
        default=None,
        help="Worker ID or index to terminate mid-execution (e.g. '2' or 'worker-2').",
    )
    run_parser.add_argument(
        "--kill-after-jobs",
        type=int,
        default=None,
        help="Job completion threshold on target worker before injecting failure.",
    )
    run_parser.add_argument(
        "--no-replace-workers",
        action="store_true",
        help="Disable automatic worker replacement after termination.",
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
            "milestone": "Milestone 3: Failure Injection + Recovery",
            "environment": config.environment,
            "log_level": config.log_level,
            "status": "ready",
        }
        print(json.dumps(data, indent=2))
    else:
        print("Titan Research Platform")
        print(f"  Version:     {__version__}")
        print("  Milestone:   3 (Failure Injection + Recovery)")
        print(f"  Environment: {config.environment}")
        print(f"  Log Level:   {config.log_level}")
        print("  State:       Operational (Failure Recovery Active)")

    return 0


def handle_run(
    workers: int,
    jobs_count: int,
    work_units: int,
    max_retries: int,
    kill_worker: str | None,
    kill_after_jobs: int | None,
    no_replace_workers: bool,
    timeout: float | None,
    json_output: bool,
) -> int:
    """Execute a workload batch and output verified performance and recovery metrics."""
    if workers < 1:
        print(f"Error: --workers must be at least 1, got {workers}", file=sys.stderr)
        return 1
    if jobs_count < 0:
        print(f"Error: --jobs cannot be negative, got {jobs_count}", file=sys.stderr)
        return 1
    if work_units < 1:
        print(f"Error: --work-units must be at least 1, got {work_units}", file=sys.stderr)
        return 1
    if max_retries < 1:
        print(f"Error: --max-retries must be at least 1, got {max_retries}", file=sys.stderr)
        return 1

    failure_config: FailureConfig | None = None
    if kill_worker is not None:
        target_id = kill_worker if kill_worker.startswith("worker-") else f"worker-{kill_worker}"
        threshold = kill_after_jobs if kill_after_jobs is not None else 0
        failure_config = FailureConfig(target_worker_id=target_id, kill_after_jobs=threshold)

    jobs = [
        Job.create(job_id=f"job-{i:06d}", work_units=work_units, max_retries=max_retries)
        for i in range(jobs_count)
    ]

    runtime = StaticRuntime(
        num_workers=workers,
        max_retries=max_retries,
        replace_failed_workers=not no_replace_workers,
        failure_config=failure_config,
    )
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
                "max_retries": max_retries,
                "kill_worker": failure_config.target_worker_id if failure_config else None,
                "kill_after_jobs": failure_config.kill_after_jobs if failure_config else None,
                "replace_workers": not no_replace_workers,
            },
            "metrics": metrics.to_dict(),
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 66)
        print("Titan Runtime Execution & Recovery Report")
        print("=" * 66)
        print(f"  Worker Processes:              {workers}")
        print(f"  Jobs Submitted (Unique):       {metrics.total_unique_submitted}")
        print(f"  Total Execution Attempts:      {metrics.total_execution_attempts}")
        print(f"  Jobs Completed (Unique):       {metrics.total_completed_unique}")
        print(f"  Jobs Failed (Unique):          {metrics.total_failed_unique}")
        print(f"  Total Retries Initiated:       {metrics.total_retries}")
        print(f"  Worker Failures Detected:      {metrics.worker_failures}")
        print(f"  Jobs Recovered:                {metrics.jobs_recovered}")
        print(f"  Jobs Permanently Failed:       {metrics.jobs_permanently_failed}")
        print(f"  Duplicate Results Ignored:     {metrics.duplicate_results_ignored}")
        print(f"  Recovery Duration:             {metrics.recovery_time_sec:.4f} s")
        print(f"  Wall-Clock Time:               {metrics.wall_clock_duration:.4f} s")
        print(f"  Primary Throughput:            {metrics.throughput:.2f} unique jobs/s")
        print(f"  Attempt Throughput:            {metrics.attempt_throughput:.2f} attempts/s")
        print(f"  Average Latency:               {metrics.avg_latency * 1000:.3f} ms")
        print(f"  p50 Latency:                   {metrics.p50_latency * 1000:.3f} ms")
        print(f"  p95 Latency:                   {metrics.p95_latency * 1000:.3f} ms")
        print(f"  p99 Latency:                   {metrics.p99_latency * 1000:.3f} ms")
        print(f"  Avg Worker Compute:            {metrics.avg_processing_time * 1000:.3f} ms")
        print("=" * 66)

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
            max_retries=args.max_retries,
            kill_worker=args.kill_worker,
            kill_after_jobs=args.kill_after_jobs,
            no_replace_workers=args.no_replace_workers,
            timeout=args.timeout,
            json_output=args.json,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
