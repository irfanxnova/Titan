"""TitanBench execution runner and artifact generator.

Executes benchmark scenarios through the Titan runtime, captures execution traces,
validates history via ReplayEngine, performs root-cause failure analysis,
evaluates oracle assertions, and writes standardized machine-readable artifacts.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Sequence

from titan.analysis import FailureAnalyzer
from titan.bench.corpus import BenchmarkScenario, CorpusRegistry
from titan.bench.result import (
    BenchmarkArtifacts,
    BenchmarkResult,
    BenchmarkStatus,
    BenchmarkSummary,
)
from titan.replay import ReplayEngine
from titan.scenario import run_scenario


class TitanBenchRunner:
    """Deterministic scenario runner and oracle evaluator for TitanBench."""

    def __init__(self, output_base_dir: str | Path = "results") -> None:
        self.output_base_dir = Path(output_base_dir)

    def run_scenario(
        self,
        benchmark_scenario: BenchmarkScenario,
        output_dir: str | Path | None = None,
    ) -> BenchmarkResult:
        """Execute an individual benchmark scenario end-to-end and evaluate oracle assertions.

        Execution pipeline:
            1. Validate scenario
            2. Run workload via Titan runtime
            3. Capture execution trace
            4. Replay trace via ReplayEngine
            5. Classify failures via FailureAnalyzer
            6. Evaluate oracle expectations -> PASS / FAIL / INVALID
            7. Persist artifact files (scenario.json, trace.json, replay.json, analysis.json, result.json)
        """
        scenario_id = benchmark_scenario.scenario_id
        target_dir = Path(output_dir) if output_dir else self.output_base_dir / scenario_id
        start_time = time.perf_counter()

        # Step 1: Validate scenario
        try:
            benchmark_scenario.validate()
        except Exception as exc:
            return BenchmarkResult(
                scenario_id=scenario_id,
                scenario_class=str(benchmark_scenario.scenario_class),
                status=BenchmarkStatus.INVALID,
                reason=f"Scenario validation error: {exc}",
                run_status="INVALID",
                replay_valid=False,
                replay_outcome="INVALID",
                root_failures_count=0,
                recovery_status="UNKNOWN",
                total_jobs=benchmark_scenario.scenario.num_jobs,
                completed_jobs=0,
                failed_jobs=0,
                total_attempts=0,
                retries=0,
                worker_failures=0,
                worker_replacements=0,
                duplicate_results_ignored=0,
                execution_duration=time.perf_counter() - start_time,
                validation_errors=[str(exc)],
            )

        # Step 2: Execute scenario via Titan runtime
        try:
            scenario_result = run_scenario(benchmark_scenario.scenario)
            metrics = scenario_result.metrics
            trace = scenario_result.trace
        except Exception as exc:
            duration = time.perf_counter() - start_time
            tb_str = traceback.format_exc()
            return BenchmarkResult(
                scenario_id=scenario_id,
                scenario_class=str(benchmark_scenario.scenario_class),
                status=BenchmarkStatus.INVALID,
                reason=f"Runtime execution failure: {exc}",
                run_status="CRASHED",
                replay_valid=False,
                replay_outcome="CRASHED",
                root_failures_count=0,
                recovery_status="UNKNOWN",
                total_jobs=benchmark_scenario.scenario.num_jobs,
                completed_jobs=0,
                failed_jobs=0,
                total_attempts=0,
                retries=0,
                worker_failures=0,
                worker_replacements=0,
                duplicate_results_ignored=0,
                execution_duration=duration,
                validation_errors=[str(exc), tb_str],
            )

        execution_duration = time.perf_counter() - start_time

        # Step 3 & 4: Replay trace
        if trace is None:
            return BenchmarkResult(
                scenario_id=scenario_id,
                scenario_class=str(benchmark_scenario.scenario_class),
                status=BenchmarkStatus.INVALID,
                reason="Execution produced no trace artifact",
                run_status="NO_TRACE",
                replay_valid=False,
                replay_outcome="NO_TRACE",
                root_failures_count=0,
                recovery_status="UNKNOWN",
                total_jobs=metrics.total_unique_submitted,
                completed_jobs=metrics.total_completed_unique,
                failed_jobs=metrics.jobs_permanently_failed,
                total_attempts=metrics.total_execution_attempts,
                retries=metrics.total_retries,
                worker_failures=metrics.worker_failures,
                worker_replacements=0,
                duplicate_results_ignored=metrics.duplicate_results_ignored,
                execution_duration=execution_duration,
                validation_errors=["Trace is None"],
            )

        replay_result = ReplayEngine.replay(trace)

        # Step 5: Failure classification and root cause analysis
        analysis_report = FailureAnalyzer.analyze(trace)

        # Step 6: Oracle evaluation
        passed, reason = benchmark_scenario.expected_behavior.evaluate(
            metrics=metrics,
            replay_res=replay_result,
            analysis_rep=analysis_report,
        )
        status = BenchmarkStatus.PASS if passed else BenchmarkStatus.FAIL

        # Step 7: Create output directory and write artifacts
        artifacts = BenchmarkArtifacts()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)

            scenario_path = target_dir / "scenario.json"
            trace_path = target_dir / "trace.json"
            replay_path = target_dir / "replay.json"
            analysis_path = target_dir / "analysis.json"
            result_path = target_dir / "result.json"

            with open(scenario_path, "w", encoding="utf-8") as f:
                json.dump(benchmark_scenario.to_dict(), f, indent=2)

            with open(trace_path, "w", encoding="utf-8") as f:
                json.dump(trace.to_list(), f, indent=2)

            with open(replay_path, "w", encoding="utf-8") as f:
                json.dump(replay_result.to_dict(), f, indent=2)

            with open(analysis_path, "w", encoding="utf-8") as f:
                json.dump(analysis_report.to_dict(), f, indent=2)

            artifacts = BenchmarkArtifacts(
                scenario_path=str(scenario_path),
                trace_path=str(trace_path),
                replay_path=str(replay_path),
                analysis_path=str(analysis_path),
                result_path=str(result_path),
            )
        except OSError as exc:
            # Filesystem write error shouldn't crash the result, but noted in validation_errors
            replay_result.validation_errors.append(f"Artifact write error: {exc}")

        # Construct authoritative BenchmarkResult
        result = BenchmarkResult(
            scenario_id=scenario_id,
            scenario_class=(
                benchmark_scenario.scenario_class.value
                if hasattr(benchmark_scenario.scenario_class, "value")
                else str(benchmark_scenario.scenario_class)
            ),
            status=status,
            reason=reason,
            run_status=replay_result.final_run_state,
            replay_valid=replay_result.valid,
            replay_outcome="VALID" if replay_result.valid else "INVALID",
            root_failures_count=analysis_report.root_failures_count,
            recovery_status=analysis_report.overall_status,
            total_jobs=metrics.total_unique_submitted,
            completed_jobs=metrics.total_completed_unique,
            failed_jobs=metrics.jobs_permanently_failed,
            total_attempts=metrics.total_execution_attempts,
            retries=metrics.total_retries,
            worker_failures=metrics.worker_failures,
            worker_replacements=replay_result.worker_replacements,
            duplicate_results_ignored=metrics.duplicate_results_ignored,
            execution_duration=execution_duration,
            validation_errors=list(replay_result.validation_errors),
            artifacts=artifacts,
            failure_analysis_summary={
                "overall_status": analysis_report.overall_status,
                "root_failures_count": analysis_report.root_failures_count,
                "consequences_count": analysis_report.consequences_count,
                "failure_classes": analysis_report.failure_classes_summary,
                "recovery_summary": analysis_report.recovery_summary,
                "affected_jobs": analysis_report.affected_jobs,
                "affected_workers": analysis_report.affected_workers,
            },
            metrics_summary={
                "wall_clock_time": round(metrics.wall_clock_duration, 4),
                "primary_throughput": round(metrics.throughput, 2),
                "average_latency_ms": round(metrics.avg_latency * 1000.0, 3),
            },
        )

        # Write result.json
        if artifacts.result_path:
            try:
                with open(artifacts.result_path, "w", encoding="utf-8") as f:
                    json.dump(result.to_dict(), f, indent=2)
            except OSError:
                pass

        return result

    def run_all(
        self,
        scenarios: Sequence[BenchmarkScenario] | None = None,
        output_base_dir: str | Path | None = None,
    ) -> BenchmarkSummary:
        """Execute a sequence of benchmark scenarios (or all canonical scenarios)."""
        suite = list(scenarios) if scenarios is not None else CorpusRegistry.list_all()
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)

        start_time = time.perf_counter()
        results: list[BenchmarkResult] = []
        passed = 0
        failed = 0
        invalid = 0

        for scen in suite:
            res = self.run_scenario(scen)
            results.append(res)
            if res.status == BenchmarkStatus.PASS:
                passed += 1
            elif res.status == BenchmarkStatus.FAIL:
                failed += 1
            else:
                invalid += 1

        total_duration = time.perf_counter() - start_time
        return BenchmarkSummary(
            total_scenarios=len(suite),
            passed=passed,
            failed=failed,
            invalid=invalid,
            total_duration_sec=total_duration,
            results=results,
        )
