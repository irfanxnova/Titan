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
from titan.analysis import FailureAnalyzer
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
        help="Output replay validation or fidelity result formatted as JSON.",
    )
    replay_parser.add_argument(
        "--compare",
        "--compare-to",
        "--expected",
        dest="expected_trace_file",
        type=str,
        default=None,
        help="Compare the replayed trace against an expected trace file for fidelity and divergence detection.",
    )

    # 'analyze' subcommand
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Perform deterministic failure classification and root-cause analysis on a trace.",
    )
    analyze_parser.add_argument(
        "trace_file",
        type=str,
        help="Path to JSON execution trace file.",
    )
    analyze_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured failure analysis report formatted as JSON.",
    )
    analyze_parser.add_argument(
        "--expected",
        "--compare",
        dest="expected_trace_file",
        type=str,
        default=None,
        help="Optional reference trace file to detect and analyze execution divergence.",
    )

    # 'bench' subcommand
    bench_parser = subparsers.add_parser(
        "bench",
        help="TitanBench: reproducible failure corpus and scenario runner.",
    )
    bench_subparsers = bench_parser.add_subparsers(
        dest="bench_command",
        help="Available bench subcommands",
    )

    # bench list
    bench_list_parser = bench_subparsers.add_parser(
        "list",
        help="List all registered canonical TitanBench failure scenarios.",
    )
    bench_list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output scenario list formatted as JSON.",
    )

    # bench run
    bench_run_parser = bench_subparsers.add_parser(
        "run",
        help="Execute an individual TitanBench scenario by ID.",
    )
    bench_run_parser.add_argument(
        "scenario_id",
        type=str,
        help="Stable scenario ID to run (e.g. 'TB-A-001').",
    )
    bench_run_parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Optional custom output directory for result artifacts.",
    )
    bench_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output benchmark result formatted as JSON.",
    )

    # bench run-all
    bench_run_all_parser = bench_subparsers.add_parser(
        "run-all",
        help="Execute the full canonical TitanBench failure corpus.",
    )
    bench_run_all_parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Optional custom base directory for result artifacts.",
    )
    bench_run_all_parser.add_argument(
        "--json",
        action="store_true",
        help="Output benchmark summary formatted as JSON.",
    )

    # 'experiment' subcommand
    exp_parser = subparsers.add_parser(
        "experiment",
        help="Recovery-policy experimentation and comparison framework.",
    )
    exp_subparsers = exp_parser.add_subparsers(
        dest="experiment_command",
        help="Available experiment subcommands",
    )

    # experiment list-policies
    exp_list_parser = exp_subparsers.add_parser(
        "list-policies",
        help="List all registered recovery policies.",
    )
    exp_list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output recovery policy list formatted as JSON.",
    )

    # experiment run
    exp_run_parser = exp_subparsers.add_parser(
        "run",
        help="Execute an experiment running a scenario under a specific recovery policy.",
    )
    exp_run_parser.add_argument(
        "scenario_id",
        type=str,
        help="Stable scenario ID to evaluate (e.g. 'TB-B-001').",
    )
    exp_run_parser.add_argument(
        "policy_id",
        type=str,
        help="Stable recovery policy ID (e.g. 'R0', 'R1', 'R2', 'R3').",
    )
    exp_run_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Number of repeated trials to execute. Default: 1.",
    )
    exp_run_parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Optional custom output directory for experiment artifacts.",
    )
    exp_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output experiment result formatted as JSON.",
    )

    # experiment compare
    exp_compare_parser = exp_subparsers.add_parser(
        "compare",
        help="Compare multiple recovery policies on the same scenario.",
    )
    exp_compare_parser.add_argument(
        "scenario_id",
        type=str,
        help="Stable scenario ID to evaluate (e.g. 'TB-B-001').",
    )
    exp_compare_parser.add_argument(
        "--policies",
        type=str,
        required=True,
        help="Comma-separated recovery policy IDs to compare (e.g. 'R0,R1' or 'R0,R1,R2').",
    )
    exp_compare_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Number of repeated trials per policy. Default: 1.",
    )
    exp_compare_parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Optional custom output directory for comparison artifacts.",
    )
    exp_compare_parser.add_argument(
        "--json",
        action="store_true",
        help="Output policy comparison formatted as JSON.",
    )

    # experiment run-config
    exp_config_parser = exp_subparsers.add_parser(
        "run-config",
        help="Execute an experiment defined by a JSON configuration file.",
    )
    exp_config_parser.add_argument(
        "config_file",
        type=str,
        help="Path to JSON configuration file.",
    )
    exp_config_parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Optional custom output directory for experiment artifacts.",
    )
    exp_config_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results formatted as JSON.",
    )

    # 'evaluate' subcommand
    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate tracing overhead, replay throughput, and system stress/scaling.",
    )
    eval_subparsers = eval_parser.add_subparsers(
        dest="evaluate_command",
        help="Evaluation actions (overhead, replay, stress, all)",
    )

    # evaluate overhead
    eval_ovh = eval_subparsers.add_parser("overhead", help="Measure tracing overhead vs no-trace baseline.")
    eval_ovh.add_argument("--trials", "-t", type=int, default=3, help="Number of repetitions per workload (default: 3).")
    eval_ovh.add_argument("--no-warmup", action="store_true", help="Disable warm-up execution.")
    eval_ovh.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory for results.")
    eval_ovh.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # evaluate replay
    eval_rep = eval_subparsers.add_parser("replay", help="Measure deterministic replay runtime and throughput.")
    eval_rep.add_argument("--trials", "-t", type=int, default=5, help="Number of replay repetitions (default: 5).")
    eval_rep.add_argument("--trace-file", type=str, default=None, help="Specific trace file to evaluate.")
    eval_rep.add_argument("--no-warmup", action="store_true", help="Disable warm-up replay.")
    eval_rep.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory for results.")
    eval_rep.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # evaluate stress
    eval_str = eval_subparsers.add_parser("stress", help="Evaluate scaling and stress across workload matrix.")
    eval_str.add_argument("--timeout", type=float, default=30.0, help="Per-workload timeout in seconds.")
    eval_str.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory for results.")
    eval_str.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # evaluate all
    eval_all = eval_subparsers.add_parser("all", help="Execute complete Prompt 10 evaluation suite.")
    eval_all.add_argument("--trials", "-t", type=int, default=3, help="Repetitions for timing tests (default: 3).")
    eval_all.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory for results.")
    eval_all.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    return parser


def handle_status(json_output: bool = False) -> int:
    """Print the current system status and active configuration."""
    from titan.bench import CorpusRegistry
    from titan.experiment import PolicyRegistry

    config = TitanConfig.from_env()
    bench_scenarios = [s.scenario_id for s in CorpusRegistry.list_all()]
    policies = [p.policy_id for p in PolicyRegistry.list_all()]

    if json_output:
        data = {
            "name": "Titan",
            "version": __version__,
            "milestone": "Milestone 10: Replay/Tracing Overhead & System Stress Evaluation",
            "environment": config.environment,
            "log_level": config.log_level,
            "status": "ready",
            "scenarios": list(PREDEFINED_SCENARIOS.keys()),
            "benchmark_corpus": bench_scenarios,
            "recovery_policies": policies,
            "evaluation_framework": "active",
        }
        print(json.dumps(data, indent=2))
    else:
        print("Titan Research Platform")
        print(f"  Version:     {__version__}")
        print("  Milestone:   10 (Overhead & Stress Evaluation; Milestone:   9; Milestone:   8 (TitanBench Failure Corpus & Runner))")
        print(f"  Environment: {config.environment}")
        print(f"  Log Level:   {config.log_level}")
        print("  State:       Operational (TitanBench Active, Recovery Policies Active, Evaluation Active)")
        print(f"  Scenarios:   {', '.join(sorted(PREDEFINED_SCENARIOS.keys()))}")
        print(f"  TitanBench:  {len(bench_scenarios)} canonical scenarios ({', '.join(bench_scenarios)})")
        print(f"  Policies:    {', '.join(policies)}")

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


def handle_replay(
    trace_file: str,
    json_output: bool = False,
    expected_trace_file: str | None = None,
) -> int:
    """Replay and validate an execution trace, optionally checking fidelity against an expected trace."""
    from titan.replay import ReplayEngine, ReplayFidelityEngine

    path = Path(trace_file)
    if not path.exists():
        print(f"Error: Trace file not found: {trace_file}", file=sys.stderr)
        return 1

    # Fidelity comparison mode
    if expected_trace_file is not None:
        expected_path = Path(expected_trace_file)
        if not expected_path.exists():
            print(f"Error: Expected trace file not found: {expected_trace_file}", file=sys.stderr)
            return 1

        try:
            fidelity_result = ReplayFidelityEngine.compare_files(
                expected_path=expected_path,
                observed_path=path,
            )
        except Exception as exc:
            print(f"Error: Failed during fidelity comparison: {exc}", file=sys.stderr)
            return 1

        if json_output:
            print(fidelity_result.to_json(indent=2))
        else:
            print("=" * 66)
            print("Titan Replay Fidelity & Divergence Report")
            print("=" * 66)
            print(f"  Observed Trace:                {trace_file}")
            print(f"  Expected Trace:                {expected_trace_file}")
            status_str = (
                "REPLAY EQUIVALENT"
                if fidelity_result.equivalent
                else "REPLAY DIVERGED (Execution Contract Divergence)"
            )
            print(f"  Fidelity Status:               {status_str}")
            print(f"  Total Comparisons:             {fidelity_result.total_comparisons}")
            print(f"  Total Divergences:             {fidelity_result.divergence_count}")
            print(f"  Expected Events:               {fidelity_result.expected_events_count}")
            print(f"  Observed Events:               {fidelity_result.observed_events_count}")

            if fidelity_result.equivalent:
                print("  Diagnostic Summary:            Replayed execution perfectly matches the expected deterministic contract.")
            else:
                first = fidelity_result.first_divergence
                if first:
                    loc_parts = []
                    if first.seq is not None:
                        loc_parts.append(f"seq {first.seq}")
                    if first.job_id:
                        loc_parts.append(f"job: {first.job_id}")
                    if first.attempt_id is not None:
                        loc_parts.append(f"attempt: {first.attempt_id}")
                    if first.worker_id:
                        loc_parts.append(f"worker: {first.worker_id}")
                    loc_str = (
                        f"seq {first.seq} ({', '.join(loc_parts[1:])})"
                        if first.seq is not None and len(loc_parts) > 1
                        else (", ".join(loc_parts) if loc_parts else "N/A")
                    )

                    print("\n  First Divergence:")
                    cat_val = first.category.value if hasattr(first.category, "value") else str(first.category)
                    print(f"    Category:                    {cat_val}")
                    print(f"    Location:                    {loc_str}")
                    print(f"    Expected:                    {first.expected}")
                    print(f"    Observed:                    {first.observed}")
                    print(f"    Summary:                     {first.message}")

                if fidelity_result.summary_by_category:
                    print("\n  Divergence Summary by Category:")
                    for cat, count in sorted(fidelity_result.summary_by_category.items()):
                        print(f"    {cat:<28} {count}")

                print(f"\n  All Divergences ({len(fidelity_result.divergences)}):")
                for idx, div in enumerate(fidelity_result.divergences, 1):
                    cat_val = div.category.value if hasattr(div.category, "value") else str(div.category)
                    seq_info = f" at seq {div.seq}" if div.seq is not None else ""
                    print(f"    [{idx}] {cat_val}{seq_info}: {div.message}")

            print("=" * 66)

        return 0 if fidelity_result.equivalent else 1

    # Standard replay validation
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


def handle_analyze(
    trace_file: str,
    json_output: bool = False,
    expected_trace_file: str | None = None,
) -> int:
    """Analyze a structured execution trace for failures, causal chains, and recovery."""
    path = Path(trace_file)
    if not path.exists():
        print(f"Error: Trace file not found: {trace_file}", file=sys.stderr)
        return 1

    expected_path = Path(expected_trace_file) if expected_trace_file else None
    if expected_path and not expected_path.exists():
        print(f"Error: Expected trace file not found: {expected_trace_file}", file=sys.stderr)
        return 1

    try:
        report = FailureAnalyzer.analyze_file(path, expected_path=expected_path)
    except Exception as exc:
        print(f"Error: Failed to analyze trace: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(report.to_json(indent=2))
    else:
        print("=" * 66)
        print("Titan Deterministic Failure & Root-Cause Analysis Report")
        print("=" * 66)
        print(f"  Trace File:                    {trace_file}")
        if expected_trace_file:
            print(f"  Expected Trace File:           {expected_trace_file}")
        trace_status_str = "VALID" if report.valid else "INVALID (Violations Detected)"
        print(f"  Trace Integrity:               {trace_status_str}")
        print(f"  Overall Run Status:            {report.overall_status}")
        print(f"  Total Events Processed:        {report.total_events}")
        print(f"  Final Reconstructed Run State: {report.reconstructed_run_state}")
        print(f"  Root Failures Detected:        {report.root_failures_count}")
        print(f"  Downstream Consequences:       {report.consequences_count}")

        if report.failure_classes_summary:
            print("\n  Failure Classes Summary:")
            for fclass, count in sorted(report.failure_classes_summary.items()):
                print(f"    {fclass:<28} {count}")

        jobs_str = ", ".join(report.affected_jobs) if report.affected_jobs else "None"
        workers_str = ", ".join(report.affected_workers) if report.affected_workers else "None"
        print(f"\n  Affected Logical Entities:")
        print(f"    Jobs ({len(report.affected_jobs)}):     {jobs_str}")
        print(f"    Workers ({len(report.affected_workers)}):  {workers_str}")

        print(f"\n  Recovery Status Summary:")
        for rec_k, rec_v in sorted(report.recovery_summary.items()):
            print(f"    {rec_k:<28} {rec_v}")

        if report.root_failures:
            print(f"\n  Root Failure Details & Causal Chains ({len(report.root_failures)}):")
            for idx, rf in enumerate(report.root_failures, 1):
                loc_info = f"seq {rf.seq}" if rf.seq is not None else "N/A"
                print(f"\n    [{idx}] Failure ID: {rf.failure_id}")
                print(f"        Class:           {rf.failure_class.value}")
                print(f"        Severity:        {rf.severity.value}")
                print(f"        Location:        {loc_info}")
                print(f"        Affected Entity: {rf.affected_entity}")
                print(f"        Immediate Cause: {rf.immediate_cause}")
                print(f"        Recovery Action: {rf.recovery_action or 'None'}")
                print(f"        Recovery Status: {rf.recovery_outcome.value}")
                print(f"        Final Outcome:   {rf.final_outcome or 'N/A'}")
                print(f"        Explanation:     {rf.explanation}")

                if rf.causal_chain:
                    print("        Causal Chain:")
                    for node in rf.causal_chain:
                        role_str = node.role.value if hasattr(node.role, "value") else str(node.role)
                        target_info = []
                        if node.job_id:
                            target_info.append(f"job={node.job_id}")
                        if node.attempt_id is not None:
                            target_info.append(f"att={node.attempt_id}")
                        if node.worker_id:
                            target_info.append(f"worker={node.worker_id}")
                        t_str = f" ({', '.join(target_info)})" if target_info else ""
                        print(
                            f"          [seq {node.seq:>3}] {role_str:<16} {node.event_type}{t_str}: {node.description}"
                        )

        if report.validation_errors:
            print(f"\n  Validation Errors ({len(report.validation_errors)}):")
            for err in report.validation_errors:
                print(f"    - {err}")

        print("=" * 66)

    return 0 if (report.valid and report.overall_status in ("CLEAN", "RECOVERED")) else 1


def handle_bench_list(json_output: bool = False) -> int:
    """List all registered canonical TitanBench failure scenarios."""
    from titan.bench import CorpusRegistry

    scenarios = CorpusRegistry.list_all()
    if json_output:
        print(json.dumps([s.to_dict() for s in scenarios], indent=2))
        return 0

    print("=" * 80)
    print("TitanBench Canonical Failure Corpus")
    print("=" * 80)
    for s in scenarios:
        sclass = s.scenario_class.value if hasattr(s.scenario_class, "value") else str(s.scenario_class)
        print(f"  {s.scenario_id:<10} | {sclass:<30} | {s.name}")
        print(f"             Description: {s.description}")
        print(
            f"             Config: {s.scenario.num_workers} workers, {s.scenario.num_jobs} jobs, "
            f"retries={s.scenario.max_retries}, replace={s.scenario.replace_failed_workers}"
        )
        print("-" * 80)
    print(f"Total registered scenarios: {len(scenarios)}")
    print("=" * 80)
    return 0


def handle_bench_run(
    scenario_id: str,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute an individual TitanBench scenario by ID and evaluate oracle."""
    from titan.bench import BenchmarkStatus, CorpusRegistry, TitanBenchRunner

    try:
        scenario = CorpusRegistry.get(scenario_id)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    runner = TitanBenchRunner()
    result = runner.run_scenario(scenario, output_dir=output_dir)

    if json_output:
        print(result.to_json())
        return 0 if result.status == BenchmarkStatus.PASS else 1

    print("=" * 66)
    print("TitanBench Execution & Verification Report")
    print("=" * 66)
    print(f"  Scenario ID:             {result.scenario_id}")
    print(f"  Class:                   {result.scenario_class}")
    print(f"  Status:                  {result.status.value}")
    print(f"  Reason:                  {result.reason}")
    print(f"  Replay Status:           {result.replay_outcome}")
    print(f"  Root Failure Count:      {result.root_failures_count}")
    print(f"  Recovery Classification: {result.recovery_status}")
    print(f"  Jobs (Total/Comp/Fail):  {result.total_jobs} / {result.completed_jobs} / {result.failed_jobs}")
    print(f"  Attempts / Retries:      {result.total_attempts} / {result.retries}")
    print(f"  Worker Failures/Repl:    {result.worker_failures} / {result.worker_replacements}")
    print(f"  Duplicates Ignored:      {result.duplicate_results_ignored}")
    print(f"  Artifact Location:       {result.artifacts.result_path or 'None'}")
    print("=" * 66)

    return 0 if result.status == BenchmarkStatus.PASS else 1


def handle_bench_run_all(
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute all canonical TitanBench failure scenarios sequentially."""
    from titan.bench import BenchmarkStatus, TitanBenchRunner

    runner = TitanBenchRunner(output_base_dir=output_dir or "results")
    summary = runner.run_all()

    if json_output:
        print(summary.to_json())
        return 0 if summary.all_passed else 1

    print("=" * 80)
    print("TitanBench Canonical Failure Corpus Run")
    print("=" * 80)
    for res in summary.results:
        print(
            f"  [{res.status.value:<4}] {res.scenario_id:<10} ({res.scenario_class:<30}) "
            f"Replay: {res.replay_outcome:<5} | Roots: {res.root_failures_count} | "
            f"Recovery: {res.recovery_status}"
        )
        if res.status != BenchmarkStatus.PASS:
            print(f"         Reason: {res.reason}")

    print("=" * 80)
    print(
        f"TitanBench Summary: {summary.passed}/{summary.total_scenarios} passed "
        f"({summary.failed} failed, {summary.invalid} invalid) in {summary.total_duration_sec:.2f}s."
    )
    print(f"Artifacts saved under: {runner.output_base_dir}")
    print("=" * 80)

    return 0 if summary.all_passed else 1


def handle_experiment_list_policies(json_output: bool = False) -> int:
    """List all registered recovery policies."""
    from titan.experiment import PolicyRegistry

    policies = PolicyRegistry.list_all()
    if json_output:
        print(json.dumps([p.to_dict() for p in policies], indent=2))
        return 0

    print("=" * 80)
    print("Titan Recovery Policies")
    print("=" * 80)
    for p in policies:
        print(f"  [{p.policy_id:<4}] {p.name:<28} Replace: {str(p.replace_failed_workers):<5} | Max Retries: {p.max_retries}")
        print(f"         {p.description}")
    print("=" * 80)
    return 0


def handle_experiment_run(
    scenario_id: str,
    policy_id: str,
    trials: int = 1,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute an experiment evaluating a scenario under a recovery policy."""
    from titan.bench import CorpusRegistry
    from titan.experiment import ExperimentRunner, PolicyRegistry

    try:
        CorpusRegistry.get(scenario_id)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        PolicyRegistry.get(policy_id)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    runner = ExperimentRunner(output_base_dir=output_dir or "experiments/results")
    result = runner.run_experiment(
        scenario_id=scenario_id,
        policy_id=policy_id,
        repetitions=trials,
        output_dir=output_dir,
    )

    if json_output:
        print(result.to_json())
        return 0 if result.recovery_rate > 0.0 else 1

    print("=" * 70)
    print("Titan Recovery-Policy Experiment Result")
    print("=" * 70)
    print(f"  Experiment ID:           {result.experiment_id}")
    print(f"  Scenario:                {result.scenario_id} ({result.scenario_class})")
    print(f"  Policy:                  {result.policy_id} ({result.policy_config.get('name', '')})")
    print(f"  Repetitions:             {result.repetitions}")
    print(f"  Successful Trials:       {result.successful_trials}/{result.repetitions} ({result.recovery_rate * 100.0:.1f}%)")

    comp_m = result.metric_summaries.get("completed_jobs")
    fail_m = result.metric_summaries.get("failed_jobs")
    att_m = result.metric_summaries.get("total_attempts")
    ret_m = result.metric_summaries.get("retries")
    rep_m = result.metric_summaries.get("worker_replacements")
    dur_m = result.metric_summaries.get("wall_clock_duration_sec")
    rec_dur_m = result.metric_summaries.get("recovery_duration_sec")
    goodput_m = result.metric_summaries.get("goodput_jobs_per_sec")

    if comp_m:
        print(f"  Completed Jobs (mean):   {comp_m.mean:.1f}")
    if fail_m:
        print(f"  Failed Jobs (mean):      {fail_m.mean:.1f}")
    if att_m:
        print(f"  Total Attempts (mean):   {att_m.mean:.1f}")
    if ret_m:
        print(f"  Retries (mean):          {ret_m.mean:.1f}")
    if rep_m:
        print(f"  Replacements (mean):     {rep_m.mean:.1f}")
    if rec_dur_m:
        print(f"  Recovery Duration:       {rec_dur_m.mean:.4f} s")
    if dur_m:
        print(f"  Wall-Clock Duration:     {dur_m.mean:.4f} s")
    if goodput_m:
        print(f"  Goodput:                 {goodput_m.mean:.2f} jobs/s")
    print("=" * 70)
    return 0 if result.recovery_rate > 0.0 else 1


def handle_experiment_compare(
    scenario_id: str,
    policies_str: str,
    trials: int = 1,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Compare multiple recovery policies on the same scenario."""
    from titan.bench import CorpusRegistry
    from titan.experiment import ExperimentRunner, PolicyRegistry

    try:
        CorpusRegistry.get(scenario_id)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    policies = [p.strip() for p in policies_str.split(",") if p.strip()]
    if not policies:
        print("Error: Specify at least one policy ID to compare.", file=sys.stderr)
        return 1

    for pid in policies:
        try:
            PolicyRegistry.get(pid)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    runner = ExperimentRunner(output_base_dir=output_dir or "experiments/results")
    comparison = runner.compare_policies(
        scenario_id=scenario_id,
        policy_ids=policies,
        repetitions=trials,
        output_dir=output_dir,
    )

    if json_output:
        print(comparison.to_json())
        return 0

    print("=" * 80)
    print(f"Titan Recovery Policy Comparison: {comparison.scenario_id} ({comparison.scenario_class})")
    print(f"Evaluated with {trials} trial(s) per policy. Non-policy variables strictly controlled.")
    print("=" * 80)
    print(comparison.to_table())
    print("=" * 80)
    print("Observed Differences:")
    for obs in comparison.observed_differences:
        print(f"  - {obs}")
    print("=" * 80)
    return 0


def handle_experiment_run_config(
    config_file: str,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute an experiment defined by a JSON configuration file."""
    from titan.experiment import ExperimentResult, ExperimentRunner, PolicyComparison

    runner = ExperimentRunner(output_base_dir=output_dir or "experiments/results")
    try:
        res = runner.run_config(config_file, output_dir=output_dir)
    except Exception as exc:
        print(f"Error executing config: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(res.to_json())
        return 0

    if isinstance(res, PolicyComparison):
        print("=" * 80)
        print(f"Titan Recovery Policy Comparison: {res.scenario_id} ({res.scenario_class})")
        print("=" * 80)
        print(res.to_table())
        print("=" * 80)
        print("Observed Differences:")
        for obs in res.observed_differences:
            print(f"  - {obs}")
        print("=" * 80)
        return 0
    elif isinstance(res, ExperimentResult):
        print("=" * 70)
        print(f"Titan Recovery-Policy Experiment Result: {res.experiment_id}")
        print("=" * 70)
        print(f"  Scenario:          {res.scenario_id}")
        print(f"  Policy:            {res.policy_id}")
        print(f"  Recovery Rate:     {res.recovery_rate * 100.0:.1f}%")
        print(f"  Successful Trials: {res.successful_trials}/{res.repetitions}")
        print("=" * 70)
        return 0 if res.recovery_rate > 0.0 else 1

    return 0


def handle_evaluate_overhead(
    trials: int = 3,
    no_warmup: bool = False,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute trace overhead evaluation suite comparing no-trace vs trace-enabled."""
    from titan.experiment.evaluation import EvaluationRunner

    runner = EvaluationRunner(output_base_dir=output_dir or "experiments/results")
    results = runner.run_overhead_suite(repetitions=trials, warmup=not no_warmup)

    if json_output:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 0

    print("=" * 90)
    print("Titan Tracing Overhead Evaluation Report")
    print(f"Evaluated with {trials} trials per workload. Non-instrumentation variables controlled.")
    print("=" * 90)
    header = f"{'Workload':<18} | {'Workers':<7} | {'Jobs':<5} | {'No-Trace (s)':<12} | {'With-Trace (s)':<14} | {'Trace (KB)':<10} | {'Overhead (%)':<12}"
    print(header)
    print("-" * 90)
    for r in results:
        trace_kb = r.trace_size_bytes / 1024.0
        line = (
            f"{r.workload_name:<18} | {r.workers:<7} | {r.jobs:<5} | "
            f"{r.no_trace_duration_stats.mean:<12.4f} | {r.with_trace_duration_stats.mean:<14.4f} | "
            f"{trace_kb:<10.2f} | {r.relative_overhead_stats.mean:<12.2f}"
        )
        print(line)
    print("=" * 90)
    return 0


def handle_evaluate_replay(
    trials: int = 5,
    trace_file: str | None = None,
    no_warmup: bool = False,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute deterministic replay evaluation suite measuring duration and throughput."""
    from titan.experiment.evaluation import EvaluationRunner
    from titan.trace import ExecutionTrace

    runner = EvaluationRunner(output_base_dir=output_dir or "experiments/results")

    if trace_file is not None:
        try:
            trace = ExecutionTrace.load_from_file(trace_file)
        except Exception as exc:
            print(f"Error loading trace file '{trace_file}': {exc}", file=sys.stderr)
            return 1
        results = [
            runner.run_replay_evaluation(
                trace,
                trace_name=Path(trace_file).stem,
                trace_source=trace_file,
                repetitions=trials,
                warmup=not no_warmup,
            )
        ]
    else:
        results = runner.run_replay_suite(repetitions=trials, warmup=not no_warmup)

    if json_output:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 0

    print("=" * 90)
    print("Titan Deterministic Replay Evaluation Report")
    print(f"Evaluated with {trials} replay repetitions per trace. Observational & non-destructive.")
    print("=" * 90)
    header = f"{'Trace Name':<24} | {'Events':<7} | {'Size (KB)':<10} | {'Duration (s)':<14} | {'Throughput (ev/s)':<18} | {'Valid':<5}"
    print(header)
    print("-" * 90)
    for r in results:
        size_kb = r.trace_size_bytes / 1024.0
        line = (
            f"{r.trace_name:<24} | {r.trace_event_count:<7} | {size_kb:<10.2f} | "
            f"{r.replay_duration_stats.mean:<14.6f} | {r.replay_throughput_stats.mean:<18.1f} | "
            f"{'YES' if r.replay_valid else 'NO':<5}"
        )
        print(line)
    print("=" * 90)
    return 0


def handle_evaluate_stress(
    timeout: float = 30.0,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute system stress and scaling evaluation matrix."""
    from titan.experiment.evaluation import EvaluationRunner

    runner = EvaluationRunner(output_base_dir=output_dir or "experiments/results")
    results = runner.run_stress_suite(timeout=timeout)

    if json_output:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 0

    print("=" * 105)
    print("Titan System Stress & Scalability Evaluation Report")
    print("Controlled scaling across concurrency, workload size, failure intensity, and retry pressure.")
    print("=" * 105)
    header = f"{'Configuration':<24} | {'Category':<20} | {'W':<3} | {'J':<4} | {'Status':<9} | {'Recovery':<12} | {'Duration (s)':<12} | {'Goodput':<10}"
    print(header)
    print("-" * 105)
    for r in results:
        t = r.trials[0] if r.trials else None
        status = t.execution_status if t else "N/A"
        recovery = t.recovery_outcome if t else "N/A"
        dur = r.execution_duration_stats.mean
        goodput = r.goodput_stats.mean
        line = (
            f"{r.config.name:<24} | {r.config.category:<20} | {r.config.workers:<3} | {r.config.jobs:<4} | "
            f"{status:<9} | {recovery:<12} | {dur:<12.4f} | {goodput:<10.1f}"
        )
        print(line)
    print("=" * 105)
    return 0


def handle_evaluate_all(
    trials: int = 3,
    output_dir: str | None = None,
    json_output: bool = False,
) -> int:
    """Execute comprehensive Prompt 10 evaluation suite: overhead + replay + stress."""
    from titan.experiment.evaluation import EvaluationRunner

    runner = EvaluationRunner(output_base_dir=output_dir or "experiments/results")
    suite = runner.run_full_system_evaluation(overhead_repetitions=trials, replay_repetitions=trials)

    if json_output:
        print(suite.to_json(indent=2))
        return 0

    handle_evaluate_overhead(trials=trials, output_dir=output_dir, json_output=False)
    print()
    handle_evaluate_replay(trials=trials, output_dir=output_dir, json_output=False)
    print()
    handle_evaluate_stress(output_dir=output_dir, json_output=False)
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
            scenario_name=args.scenario,
            pattern=args.pattern,
            seed=args.seed,
            show_trace=args.trace,
            trace_file=args.trace_file,
        )

    if args.command == "replay":
        return handle_replay(
            trace_file=args.trace_file,
            json_output=args.json,
            expected_trace_file=args.expected_trace_file,
        )

    if args.command == "analyze":
        return handle_analyze(
            trace_file=args.trace_file,
            json_output=args.json,
            expected_trace_file=args.expected_trace_file,
        )

    if args.command == "bench":
        if args.bench_command == "list":
            return handle_bench_list(json_output=args.json)
        elif args.bench_command == "run":
            return handle_bench_run(
                scenario_id=args.scenario_id,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.bench_command == "run-all":
            return handle_bench_run_all(
                output_dir=args.output_dir,
                json_output=args.json,
            )
        else:
            print("Error: Specify a bench subcommand (list, run, run-all). See 'titan bench --help'.", file=sys.stderr)
            return 1

    if args.command == "experiment":
        if args.experiment_command == "list-policies":
            return handle_experiment_list_policies(json_output=args.json)
        elif args.experiment_command == "run":
            return handle_experiment_run(
                scenario_id=args.scenario_id,
                policy_id=args.policy_id,
                trials=args.trials,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.experiment_command == "compare":
            return handle_experiment_compare(
                scenario_id=args.scenario_id,
                policies_str=args.policies,
                trials=args.trials,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.experiment_command == "run-config":
            return handle_experiment_run_config(
                config_file=args.config_file,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        else:
            print("Error: Specify an experiment subcommand (list-policies, run, compare, run-config). See 'titan experiment --help'.", file=sys.stderr)
            return 1

    if args.command == "evaluate":
        if args.evaluate_command == "overhead":
            return handle_evaluate_overhead(
                trials=args.trials,
                no_warmup=args.no_warmup,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.evaluate_command == "replay":
            return handle_evaluate_replay(
                trials=args.trials,
                trace_file=args.trace_file,
                no_warmup=args.no_warmup,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.evaluate_command == "stress":
            return handle_evaluate_stress(
                timeout=args.timeout,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        elif args.evaluate_command == "all":
            return handle_evaluate_all(
                trials=args.trials,
                output_dir=args.output_dir,
                json_output=args.json,
            )
        else:
            print("Error: Specify an evaluate subcommand (overhead, replay, stress, all). See 'titan evaluate --help'.", file=sys.stderr)
            return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

