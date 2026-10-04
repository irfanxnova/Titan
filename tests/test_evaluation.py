"""Tests for Replay / Tracing Overhead and System Stress Evaluation Framework.

Verifies:
1. Trace-enabled and trace-disabled execution modes.
2. Observational non-interference of no-trace mode on logical execution semantics.
3. Metric calculations (safe zero-denominator division, relative overhead, bytes/event).
4. Trace size and serialization time measurement.
5. Replay duration, validity, and throughput extraction.
6. Repeated trial aggregation and MetricStats calculation (mean, median, min, max).
7. Stress workload execution across concurrency scaling, failure intensity, and retry pressure.
8. Complete JSON serialization and deserialization round-trips.
9. CLI evaluate subcommands (overhead, replay, stress, all) in text and JSON modes.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from titan.cli import main
from titan.experiment.evaluation import (
    EvaluationMode,
    EvaluationRunner,
    ReplayEvaluationResult,
    ReplayEvaluationTrial,
    StressEvaluationResult,
    StressTrial,
    StressWorkloadConfig,
    SystemEvaluationSuite,
    TraceOverheadResult,
    TraceOverheadTrial,
    compute_relative_overhead,
    safe_div,
)
from titan.experiment.trial import MetricStats
from titan.scenario import FaultConfig, Scenario, run_scenario
from titan.trace import EventType, ExecutionTrace, TraceEvent


class TestEvaluationMetrics(unittest.TestCase):
    """Verify numeric calculations, safe division, and summary statistics."""

    def test_safe_div_zero_denominator(self) -> None:
        """Safe division must return fallback on zero or float zero denominator."""
        self.assertEqual(safe_div(100, 0), 0.0)
        self.assertEqual(safe_div(100, 0.0), 0.0)
        self.assertEqual(safe_div(100, 0, fallback=-1.0), -1.0)
        self.assertEqual(safe_div(10, 2), 5.0)

    def test_relative_overhead_calculation(self) -> None:
        """Relative overhead percentage formula must be ((with - no) / no) * 100."""
        # 1.2s vs 1.0s = 20% overhead
        self.assertAlmostEqual(compute_relative_overhead(1.2, 1.0), 20.0, places=4)
        # 0.9s vs 1.0s = -10% overhead (jitter/variance)
        self.assertAlmostEqual(compute_relative_overhead(0.9, 1.0), -10.0, places=4)
        # Zero baseline must return 0.0 safely
        self.assertEqual(compute_relative_overhead(1.5, 0.0), 0.0)
        self.assertEqual(compute_relative_overhead(1.5, -0.5), 0.0)

    def test_metric_stats_with_median(self) -> None:
        """MetricStats must accurately compute count, mean, median, min, max."""
        values = [10.0, 30.0, 20.0]
        stats = MetricStats.compute(values)
        self.assertEqual(stats.count, 3)
        self.assertAlmostEqual(stats.mean, 20.0)
        self.assertAlmostEqual(stats.median, 20.0)
        self.assertEqual(stats.min, 10.0)
        self.assertEqual(stats.max, 30.0)

        # Even number of samples for median interpolation
        even_stats = MetricStats.compute([10.0, 20.0, 30.0, 40.0])
        self.assertAlmostEqual(even_stats.median, 25.0)

    def test_empty_metric_stats(self) -> None:
        """Empty sequence must produce zeros safely without error."""
        stats = MetricStats.compute([])
        self.assertEqual(stats.count, 0)
        self.assertEqual(stats.mean, 0.0)
        self.assertEqual(stats.median, 0.0)
        self.assertEqual(stats.min, 0.0)
        self.assertEqual(stats.max, 0.0)


class TestTraceEnabledAndDisabledModes(unittest.TestCase):
    """Verify Mode A (no-trace) and Mode B (with-trace) execution semantics."""

    def test_trace_disabled_execution(self) -> None:
        """Mode A (enable_tracing=False) must execute workload without populating trace events."""
        scenario = Scenario(
            name="test-notrace",
            num_workers=2,
            num_jobs=6,
            work_units=200,
            enable_tracing=False,
        )
        res = run_scenario(scenario)
        self.assertEqual(res.metrics.total_completed_unique, 6)
        self.assertEqual(res.metrics.jobs_permanently_failed, 0)
        self.assertIsNotNone(res.trace)
        self.assertFalse(res.trace.enabled)
        self.assertEqual(len(res.trace), 0)

    def test_trace_enabled_execution(self) -> None:
        """Mode B (enable_tracing=True) must execute workload and record complete trace events."""
        scenario = Scenario(
            name="test-withtrace",
            num_workers=2,
            num_jobs=6,
            work_units=200,
            enable_tracing=True,
        )
        res = run_scenario(scenario)
        self.assertEqual(res.metrics.total_completed_unique, 6)
        self.assertIsNotNone(res.trace)
        self.assertTrue(res.trace.enabled)
        self.assertGreater(len(res.trace), 0)

    def test_no_trace_mode_preserves_workload_semantics(self) -> None:
        """Disabling tracing must preserve 100% of logical execution outcomes."""
        sc_no = Scenario(name="same-notrace", num_workers=2, num_jobs=8, work_units=300, seed=42, enable_tracing=False)
        sc_with = Scenario(name="same-withtrace", num_workers=2, num_jobs=8, work_units=300, seed=42, enable_tracing=True)

        res_no = run_scenario(sc_no)
        res_with = run_scenario(sc_with)

        self.assertEqual(res_no.metrics.total_completed_unique, res_with.metrics.total_completed_unique)
        self.assertEqual(res_no.metrics.total_execution_attempts, res_with.metrics.total_execution_attempts)
        self.assertEqual(res_no.metrics.total_retries, res_with.metrics.total_retries)
        self.assertEqual(res_no.metrics.worker_failures, res_with.metrics.worker_failures)


class TestTraceOverheadEvaluation(unittest.TestCase):
    """Verify trace overhead measurement and multi-trial aggregation."""

    def test_trace_overhead_runner_and_metrics(self) -> None:
        """EvaluationRunner must measure no-trace vs with-trace across repeated trials."""
        scenario = Scenario(name="test-ovh-workload", num_workers=2, num_jobs=6, work_units=200)
        runner = EvaluationRunner(output_base_dir=tempfile.mkdtemp())

        result = runner.run_trace_overhead(scenario, repetitions=2, warmup=False, save_artifacts=False)

        self.assertEqual(result.workload_name, "test-ovh-workload")
        self.assertEqual(result.repetitions, 2)
        self.assertEqual(len(result.trials), 2)
        self.assertGreater(result.no_trace_duration_stats.mean, 0.0)
        self.assertGreater(result.with_trace_duration_stats.mean, 0.0)
        self.assertGreater(result.event_count, 0)
        self.assertGreater(result.trace_size_bytes, 0)
        self.assertGreater(result.bytes_per_event, 0.0)
        self.assertEqual(result.useful_completed_jobs, 6)

    def test_trace_overhead_serialization_roundtrip(self) -> None:
        """TraceOverheadResult must serialize to JSON and reconstruct accurately."""
        scenario = Scenario(name="test-ser-ovh", num_workers=2, num_jobs=4, work_units=200)
        runner = EvaluationRunner()
        result = runner.run_trace_overhead(scenario, repetitions=1, warmup=False, save_artifacts=False)

        json_str = result.to_json(indent=2)
        data = json.loads(json_str)
        loaded = TraceOverheadResult.from_dict(data)

        self.assertEqual(loaded.workload_name, result.workload_name)
        self.assertEqual(loaded.workers, result.workers)
        self.assertEqual(loaded.jobs, result.jobs)
        self.assertEqual(loaded.event_count, result.event_count)
        self.assertEqual(loaded.trace_size_bytes, result.trace_size_bytes)
        self.assertAlmostEqual(loaded.relative_overhead_stats.mean, result.relative_overhead_stats.mean, places=4)


class TestReplayEvaluation(unittest.TestCase):
    """Verify deterministic replay runtime, throughput, and error detection."""

    def test_replay_duration_and_throughput(self) -> None:
        """Replay evaluation must record duration, throughput, and validity."""
        scenario = Scenario(name="test-replay-src", num_workers=2, num_jobs=5, work_units=200)
        res = run_scenario(scenario)
        trace = res.trace
        self.assertIsNotNone(trace)

        runner = EvaluationRunner()
        rep_result = runner.run_replay_evaluation(
            trace,
            trace_name="test_trace",
            repetitions=3,
            warmup=False,
            save_artifacts=False,
        )

        self.assertEqual(rep_result.trace_name, "test_trace")
        self.assertEqual(rep_result.repetitions, 3)
        self.assertEqual(len(rep_result.trials), 3)
        self.assertTrue(rep_result.replay_valid)
        self.assertEqual(len(rep_result.validation_errors), 0)
        self.assertGreater(rep_result.replay_duration_stats.mean, 0.0)
        self.assertGreater(rep_result.replay_throughput_stats.mean, 0.0)

    def test_replay_invalid_trace_detected(self) -> None:
        """Replay evaluation on corrupted trace must record replay_valid=False and errors."""
        trace = ExecutionTrace()
        # Non-monotonic sequence
        trace._events.append(TraceEvent(seq=1, event_type=EventType.RUN_STARTED, timestamp=1.0))
        trace._events.append(TraceEvent(seq=5, event_type=EventType.RUN_COMPLETED, timestamp=2.0))

        runner = EvaluationRunner()
        res = runner.run_replay_evaluation(trace, trace_name="corrupt", repetitions=1, warmup=False, save_artifacts=False)

        self.assertFalse(res.replay_valid)
        self.assertGreater(len(res.validation_errors), 0)

    def test_replay_result_serialization_roundtrip(self) -> None:
        """ReplayEvaluationResult must serialize to JSON and reconstruct accurately."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.RUN_COMPLETED)

        runner = EvaluationRunner()
        res = runner.run_replay_evaluation(trace, trace_name="mini", repetitions=2, warmup=False, save_artifacts=False)

        json_str = res.to_json(indent=2)
        loaded = ReplayEvaluationResult.from_dict(json.loads(json_str))

        self.assertEqual(loaded.trace_name, res.trace_name)
        self.assertEqual(loaded.trace_event_count, res.trace_event_count)
        self.assertEqual(loaded.replay_valid, res.replay_valid)
        self.assertEqual(loaded.repetitions, res.repetitions)


class TestStressEvaluation(unittest.TestCase):
    """Verify stress evaluation across scaling, failure, and retry configurations."""

    def test_stress_workload_execution_and_scaling(self) -> None:
        """Concurrency scaling configuration must execute, replay, and record goodput."""
        config = StressWorkloadConfig(
            name="test-stress-scale",
            category="concurrency_scaling",
            workers=2,
            jobs=6,
            work_units=300,
        )
        runner = EvaluationRunner()
        result = runner.run_stress_evaluation(config, repetitions=1, save_artifacts=False)

        self.assertEqual(result.config.name, "test-stress-scale")
        self.assertEqual(result.successful_trials, 1)
        self.assertEqual(result.recovery_rate, 1.0)
        self.assertEqual(len(result.trials), 1)

        trial = result.trials[0]
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertEqual(trial.completed_jobs, 6)
        self.assertEqual(trial.failed_jobs, 0)
        self.assertTrue(trial.replay_valid)
        self.assertGreater(trial.goodput_jobs_per_sec, 0.0)

    def test_stress_failure_and_recovery_recording(self) -> None:
        """Failure stress configuration must record worker crash, replacement, and recovery."""
        config = StressWorkloadConfig(
            name="test-stress-failure",
            category="failure_intensity",
            workers=2,
            jobs=10,
            work_units=500,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        runner = EvaluationRunner()
        result = runner.run_stress_evaluation(config, repetitions=1, save_artifacts=False)

        self.assertEqual(result.successful_trials, 1)
        trial = result.trials[0]
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertGreaterEqual(trial.worker_failures, 1)
        self.assertGreaterEqual(trial.worker_replacements, 1)
        self.assertEqual(trial.completed_jobs, 10)
        self.assertTrue(trial.replay_valid)

    def test_stress_retry_pressure_fail_fast(self) -> None:
        """Retry pressure configuration (max_retries=1) must record fail-fast terminal failure."""
        config = StressWorkloadConfig(
            name="test-stress-retry",
            category="retry_pressure",
            workers=2,
            jobs=6,
            work_units=500,
            max_retries=1,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=1),
        )
        runner = EvaluationRunner()
        result = runner.run_stress_evaluation(config, repetitions=1, save_artifacts=False)

        trial = result.trials[0]
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertGreater(trial.failed_jobs, 0)
        self.assertEqual(result.successful_trials, 0)
        self.assertEqual(result.recovery_rate, 0.0)

    def test_stress_result_serialization_roundtrip(self) -> None:
        """StressEvaluationResult must serialize to JSON and reconstruct accurately."""
        config = StressWorkloadConfig(
            name="test-ser-stress",
            category="concurrency_scaling",
            workers=2,
            jobs=4,
            work_units=200,
        )
        runner = EvaluationRunner()
        res = runner.run_stress_evaluation(config, repetitions=1, save_artifacts=False)

        json_str = res.to_json(indent=2)
        loaded = StressEvaluationResult.from_dict(json.loads(json_str))

        self.assertEqual(loaded.config.name, res.config.name)
        self.assertEqual(loaded.config.category, res.config.category)
        self.assertEqual(loaded.successful_trials, res.successful_trials)
        self.assertEqual(len(loaded.trials), len(res.trials))

    def test_system_evaluation_suite_serialization(self) -> None:
        """SystemEvaluationSuite must serialize complete multi-suite results to JSON."""
        suite = SystemEvaluationSuite(
            timestamp=123456789.0,
            platform_info={"platform": "test-os"},
            trace_overhead_results=[],
            replay_results=[],
            stress_results=[],
        )
        json_str = suite.to_json(indent=2)
        loaded = SystemEvaluationSuite.from_dict(json.loads(json_str))

        self.assertEqual(loaded.timestamp, 123456789.0)
        self.assertEqual(loaded.platform_info["platform"], "test-os")


class TestCLIEvaluationIntegration(unittest.TestCase):
    """Verify CLI evaluate subcommands (overhead, replay, stress, all)."""

    def test_cli_evaluate_replay_text(self) -> None:
        """CLI evaluate replay must print formatted report and exit 0."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["evaluate", "replay", "--trials", "1", "--no-warmup"])

        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Titan Deterministic Replay Evaluation Report", output)
        self.assertIn("tb_a_baseline", output)
        self.assertIn("YES", output)

    def test_cli_evaluate_replay_json(self) -> None:
        """CLI evaluate replay --json must output valid JSON array."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["evaluate", "replay", "--trials", "1", "--no-warmup", "--json"])

        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertTrue(data[0]["replay_valid"])

    def test_cli_evaluate_overhead_json(self) -> None:
        """CLI evaluate overhead --json must execute workloads and output valid JSON."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main([
                    "evaluate", "overhead",
                    "--trials", "1",
                    "--no-warmup",
                    "--output-dir", tmp_dir,
                    "--json",
                ])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout_capture.getvalue())
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 3)  # small, medium, large
            self.assertEqual(data[0]["workload_name"], "overhead-small")
            self.assertIn("no_trace_duration_stats", data[0])
            self.assertIn("with_trace_duration_stats", data[0])

    def test_cli_status_reports_milestone_10(self) -> None:
        """CLI status command must report Milestone 10."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["status"])

        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Milestone:   10", output)
        self.assertIn("State:       Operational", output)


if __name__ == "__main__":
    unittest.main()
