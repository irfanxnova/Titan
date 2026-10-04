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
from titan.scenario import (
    PREDEFINED_SCENARIOS,
    FaultConfig,
    Scenario,
    get_scenario,
    run_scenario,
)


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
        "--scenario",
        "-s",
        type=str,
        default=None,
        help="Named deterministic scenario to run (e.g. 'baseline', 'worker-crash', 'stress-recovery').",
    )
    run_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        help="Number of worker processes to spawn (e.g. 1, 2, 4, 8). Default: 2.",
    )
    run_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=None,
        help="Total number of unique jobs to submit. Default: 100.",
    )
    run_parser.add_argument(
        "--work-units",
        "-u",
        type=int,
        default=None,
        help="Deterministic computation units per job. Default: 1000.",
    )
    run_parser.add_argument(
        "--pattern",
        type=str,
        default="uniform",
        choices=["uniform", "linear", "bimodal"],
        help="Workload distribution pattern ('uniform', 'linear', 'bimodal'). Default: uniform.",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic random seed for workload generation. Default: 42.",
    )
    run_parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
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
    run_parser.add_argument(
        "--trace",
        action="store_true",
        help="Display the structured execution trace events in sequential order.",
    )
    run_parser.add_argument(
        "--trace-file",
        type=str,
        default=None,
        help="Export the structured execution trace to a JSON file.",
    )

    # 'replay' subcommand
    replay_parser = subparsers.add_parser(
        "replay",
        help="Replay and validate a structured execution trace file.",
    )
    replay_parser.add_argument(
        "trace_file",
        type=str,
        help="Path to JSON execution trace file.",
    )
    replay_parser.add_argument(
        "--json",
        action="store_true",
        help="Output replay validation result formatted as JSON.",
    )

    return parser


def handle_status(json_output: bool = False) -> int:
    """Print the current system status and active configuration."""
    config = TitanConfig.from_env()

    if json_output:
        data = {
            "name": "Titan",
            "version": __version__,
            "milestone": "Milestone 5: Deterministic Replay Engine",
            "environment": config.environment,
            "log_level": config.log_level,
            "status": "ready",
            "scenarios": list(PREDEFINED_SCENARIOS.keys()),
        }
        print(json.dumps(data, indent=2))
    else:
        print("Titan Research Platform")
        print(f"  Version:     {__version__}")
        print("  Milestone:   5 (Deterministic Replay Engine)")
        print(f"  Environment: {config.environment}")
        print(f"  Log Level:   {config.log_level}")
        print("  State:       Operational (Deterministic Replay Active)")
        print(f"  Scenarios:   {', '.join(sorted(PREDEFINED_SCENARIOS.keys()))}")

    return 0


def handle_run(
    workers: int | None,
    jobs_count: int | None,
    work_units: int | None,
    max_retries: int | None,
    kill_worker: str | None,
    kill_after_jobs: int | None,
    no_replace_workers: bool,
    timeout: float | None,
    json_output: bool,
    scenario_name: str | None = None,
    pattern: str = "uniform",
    seed: int = 42,
    show_trace: bool = False,
    trace_file: str | None = None,
) -> int:
    """Execute a workload batch and output verified performance and recovery metrics."""
    # Resolve scenario preset if specified
    preset: Scenario | None = None
    if scenario_name is not None:
        try:
            preset = get_scenario(scenario_name)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    # Effective parameter resolution (CLI explicit flags override scenario defaults)
    effective_workers = workers if workers is not None else (preset.num_workers if preset else 2)
    effective_jobs = jobs_count if jobs_count is not None else (preset.num_jobs if preset else 100)
    effective_work_units = work_units if work_units is not None else (preset.work_units if preset else 1000)
    effective_max_retries = max_retries if max_retries is not None else (preset.max_retries if preset else 3)
    effective_timeout = timeout if timeout is not None else (preset.timeout if preset else None)

    # Basic parameter validation
    if effective_workers < 1:
        print(f"Error: --workers must be at least 1, got {effective_workers}", file=sys.stderr)
        return 1
    if effective_jobs < 0:
        print(f"Error: --jobs cannot be negative, got {effective_jobs}", file=sys.stderr)
        return 1
    if effective_work_units < 1:
        print(f"Error: --work-units must be at least 1, got {effective_work_units}", file=sys.stderr)
        return 1
    if effective_max_retries < 1:
        print(f"Error: --max-retries must be at least 1, got {effective_max_retries}", file=sys.stderr)
        return 1
    if kill_after_jobs is not None and kill_after_jobs < 0:
        print(f"Error: --kill-after-jobs cannot be negative, got {kill_after_jobs}", file=sys.stderr)
        return 1
    if kill_after_jobs is not None and kill_worker is None:
        print("Error: --kill-after-jobs requires --kill-worker to be specified", file=sys.stderr)
        return 1

    # Fault configuration resolution
    fault_config: FaultConfig | None = None
    if kill_worker is not None:
        threshold = kill_after_jobs if kill_after_jobs is not None else 0
        fault_config = FaultConfig(target_worker_id=kill_worker, kill_after_jobs=threshold)
    elif preset and preset.fault_config:
        fault_config = preset.fault_config

    try:
        scenario = Scenario(
            name=scenario_name or (preset.name if preset else "custom"),
            num_workers=effective_workers,
            num_jobs=effective_jobs,
            work_units=effective_work_units,
            pattern=pattern or (preset.pattern if preset else "uniform"),
            seed=seed,
            max_retries=effective_max_retries,
            replace_failed_workers=not no_replace_workers,
            fault_config=fault_config,
            timeout=effective_timeout,
        )
        scenario.validate()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    scenario_result = run_scenario(scenario)
    metrics = scenario_result.metrics

    if trace_file and scenario_result.trace:
        scenario_result.trace.save_to_file(trace_file)

    if json_output:
        payload = {
            "scenario": scenario_result.to_dict()["scenario"],
            "config": {
                "workers": scenario.num_workers,
                "jobs": scenario.num_jobs,
                "work_units": scenario.work_units,
                "max_retries": scenario.max_retries,
                "kill_worker": scenario.fault_config.target_worker_id if scenario.fault_config else None,
                "kill_after_jobs": scenario.fault_config.kill_after_jobs if scenario.fault_config else None,
                "replace_workers": scenario.replace_failed_workers,
            },
            "metrics": metrics.to_dict(),
            "trace": scenario_result.trace.to_list() if scenario_result.trace else [],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 66)
        print("Titan Runtime Execution & Recovery Report")
        print("=" * 66)
        print(f"  Scenario:                      {scenario.name}")
        if scenario.fault_config:
            print(f"  Fault Injection:               Active ({scenario.fault_config.target_worker_id} killed after {scenario.fault_config.kill_after_jobs} jobs)")
        else:
            print("  Fault Injection:               Disabled")
        print(f"  Worker Processes:              {scenario.num_workers}")
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

        if show_trace and scenario_result.trace:
            print("\n" + "=" * 66)
            print(f"Execution Trace ({len(scenario_result.trace)} events)")
            print("=" * 66)
            for event in scenario_result.trace:
                print(f"  {event}")
            print("=" * 66)

        if trace_file:
            print(f"Trace saved to: {trace_file}")

    return 0


def handle_replay(trace_file: str, json_output: bool = False) -> int:
    """Replay and validate an execution trace from a JSON file."""
    from titan.replay import ReplayEngine

    path = Path(trace_file)
    if not path.exists():
        print(f"Error: Trace file not found: {trace_file}", file=sys.stderr)
        return 1

    try:
        result = ReplayEngine.replay_file(path)
    except Exception as exc:
        print(f"Error: Failed to load/replay trace: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(result.to_json(indent=2))
    else:
        print("=" * 66)
        print("Titan Trace Replay & Validation Report")
        print("=" * 66)
        print(f"  Trace File:                    {trace_file}")
        status_str = "VALID" if result.valid else "INVALID (Violations Detected)"
        print(f"  Trace Integrity:               {status_str}")
        print(f"  Total Events Processed:        {result.total_events}")
        print(f"  Final Reconstructed Run State: {result.final_run_state}")
        completed_jobs = sum(1 for s in result.reconstructed_job_states.values() if s == "COMPLETED")
        failed_jobs = sum(1 for s in result.reconstructed_job_states.values() if s == "FAILED")
        total_jobs = len(result.reconstructed_job_states)
        print(f"  Jobs Reconstructed (Total):    {total_jobs} ({completed_jobs} completed, {failed_jobs} failed)")
        print(f"  Total Attempts Reconstructed:  {result.attempts}")
        print(f"  Retries Reconstructed:         {result.retries}")
        print(f"  Worker Failures Detected:      {result.worker_failures}")
        print(f"  Worker Replacements:           {result.worker_replacements}")
        print(f"  Active / Total Workers:        {len(result.reconstructed_worker_states)}")
        if result.validation_errors:
            print(f"  Validation Errors ({len(result.validation_errors)}):")
            for err in result.validation_errors:
                print(f"    - {err}")
        else:
            print("  Validation Errors:             None (Consistent Execution History)")
        print("=" * 66)

    return 0 if result.valid else 1


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
            scenario_name=args.scenario,
            pattern=args.pattern,
            seed=args.seed,
            show_trace=args.trace,
            trace_file=args.trace_file,
        )

    if args.command == "replay":
        return handle_replay(trace_file=args.trace_file, json_output=args.json)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
