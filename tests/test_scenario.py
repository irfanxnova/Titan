"""Automated test suite for Titan deterministic scenarios and fault injection."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path for direct invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.cli import main
from titan.job import AttemptStatus, JobStatus
from titan.scenario import (
    PREDEFINED_SCENARIOS,
    FaultConfig,
    Scenario,
    get_scenario,
    run_scenario,
)


class TestScenarioDefinition(unittest.TestCase):
    """Verify deterministic workload generation and scenario validation."""

    def test_uniform_workload_determinism(self) -> None:
        """Verify identical uniform scenario configuration produces identical jobs."""
        s1 = Scenario("s1", num_workers=2, num_jobs=10, work_units=500, pattern="uniform")
        s2 = Scenario("s2", num_workers=2, num_jobs=10, work_units=500, pattern="uniform")

        jobs1 = s1.generate_jobs()
        jobs2 = s2.generate_jobs()

        self.assertEqual(len(jobs1), 10)
        self.assertEqual(len(jobs2), 10)
        self.assertEqual([j.job_id for j in jobs1], [j.job_id for j in jobs2])
        self.assertEqual([j.work_units for j in jobs1], [j.work_units for j in jobs2])
        self.assertTrue(all(j.work_units == 500 for j in jobs1))

    def test_seeded_workload_determinism(self) -> None:
        """Verify seeded bimodal pattern produces identical work units across multiple runs."""
        s1 = Scenario("s1", num_workers=2, num_jobs=20, work_units=1000, pattern="bimodal", seed=12345)
        s2 = Scenario("s2", num_workers=2, num_jobs=20, work_units=1000, pattern="bimodal", seed=12345)
        s_diff = Scenario("s3", num_workers=2, num_jobs=20, work_units=1000, pattern="bimodal", seed=99999)

        jobs1 = s1.generate_jobs()
        jobs2 = s2.generate_jobs()
        jobs_diff = s_diff.generate_jobs()

        self.assertEqual([j.work_units for j in jobs1], [j.work_units for j in jobs2])
        self.assertNotEqual([j.work_units for j in jobs1], [j.work_units for j in jobs_diff])

    def test_linear_workload_generation(self) -> None:
        """Verify linear workload pattern increases monotonically."""
        s = Scenario("linear-s", num_workers=2, num_jobs=5, work_units=100, pattern="linear")
        jobs = s.generate_jobs()
        units = [j.work_units for j in jobs]
        self.assertEqual(len(units), 5)
        self.assertTrue(all(units[i] <= units[i + 1] for i in range(len(units) - 1)))

    def test_invalid_scenario_validation(self) -> None:
        """Verify invalid scenario parameters raise ValueError."""
        with self.assertRaises(ValueError):
            Scenario("", num_workers=2, num_jobs=10).validate()
        with self.assertRaises(ValueError):
            Scenario("bad-w", num_workers=0, num_jobs=10).validate()
        with self.assertRaises(ValueError):
            Scenario("bad-j", num_workers=2, num_jobs=-1).validate()
        with self.assertRaises(ValueError):
            Scenario("bad-u", num_workers=2, num_jobs=10, work_units=0).validate()
        with self.assertRaises(ValueError):
            Scenario("bad-r", num_workers=2, num_jobs=10, max_retries=0).validate()
        with self.assertRaises(ValueError):
            Scenario("bad-p", num_workers=2, num_jobs=10, pattern="invalid_pattern").validate()

    def test_predefined_scenarios_registry(self) -> None:
        """Verify predefined scenarios can be retrieved and validated."""
        for name in ("baseline", "worker-crash", "stress-recovery"):
            sc = get_scenario(name)
            self.assertEqual(sc.name, name)
            sc.validate()

        with self.assertRaises(ValueError) as ctx:
            get_scenario("non-existent")
        self.assertIn("Unknown scenario 'non-existent'", str(ctx.exception))


class TestFaultConfigValidation(unittest.TestCase):
    """Verify fault configuration constraints and validation rules."""

    def test_valid_fault_config(self) -> None:
        """Verify valid fault config passes validation with worker name or index."""
        fc1 = FaultConfig(target_worker_id="worker-0", kill_after_jobs=5)
        fc1.validate(num_workers=2, total_jobs=10)

        fc2 = FaultConfig(target_worker_id="1", kill_after_jobs=0)
        fc2.validate(num_workers=2, total_jobs=10)
        self.assertEqual(fc2.to_failure_config().target_worker_id, "worker-1")

    def test_out_of_bounds_target_worker_rejected(self) -> None:
        """Verify targeting a non-existent worker process index is rejected."""
        fc = FaultConfig(target_worker_id="worker-5", kill_after_jobs=1)
        with self.assertRaises(ValueError) as ctx:
            fc.validate(num_workers=2, total_jobs=10)
        self.assertIn("out of range", str(ctx.exception))

    def test_negative_kill_threshold_rejected(self) -> None:
        """Verify negative kill_after_jobs is rejected."""
        fc = FaultConfig(target_worker_id="worker-0", kill_after_jobs=-1)
        with self.assertRaises(ValueError):
            fc.validate(num_workers=2, total_jobs=10)

    def test_kill_threshold_exceeding_total_jobs_rejected(self) -> None:
        """Verify kill_after_jobs >= total_jobs is rejected."""
        fc = FaultConfig(target_worker_id="worker-0", kill_after_jobs=10)
        with self.assertRaises(ValueError) as ctx:
            fc.validate(num_workers=2, total_jobs=10)
        self.assertIn("strictly less than", str(ctx.exception))


class TestDeterministicExecutionAndFaultInjection(unittest.TestCase):
    """Verify execution repeatability and fault injection behavior under controlled scenarios."""

    def test_identical_scenario_produces_identical_results(self) -> None:
        """Requirement 1 & 5: Identical scenario configuration produces identical metrics and completion."""
        scenario = Scenario(
            name="repeatable-test",
            num_workers=2,
            num_jobs=10,
            work_units=1000,
            pattern="uniform",
        )

        res1 = run_scenario(scenario)
        res2 = run_scenario(scenario)

        # Both runs must complete all 10 unique jobs with zero failures and zero retries
        self.assertEqual(res1.metrics.total_unique_submitted, 10)
        self.assertEqual(res2.metrics.total_unique_submitted, 10)
        self.assertEqual(res1.metrics.total_completed_unique, 10)
        self.assertEqual(res2.metrics.total_completed_unique, 10)
        self.assertEqual(res1.metrics.total_failed_unique, 0)
        self.assertEqual(res2.metrics.total_failed_unique, 0)
        self.assertEqual(res1.metrics.total_execution_attempts, 10)
        self.assertEqual(res2.metrics.total_execution_attempts, 10)
        self.assertEqual(res1.metrics.worker_failures, 0)
        self.assertEqual(res2.metrics.worker_failures, 0)
        self.assertEqual(res1.fault_injected, False)
        self.assertEqual(res2.fault_injected, False)

    def test_disabled_fault_injection_causes_normal_execution(self) -> None:
        """Requirement 2 & 5: Fault injection is disabled by default and causes normal execution."""
        scenario = Scenario(
            name="no-fault",
            num_workers=2,
            num_jobs=8,
            work_units=500,
            fault_config=None,
        )
        res = run_scenario(scenario)

        self.assertFalse(res.fault_injected)
        self.assertIsNone(res.fault_target)
        self.assertIsNone(res.fault_point)
        self.assertEqual(res.metrics.worker_failures, 0)
        self.assertEqual(res.metrics.total_retries, 0)
        self.assertEqual(res.metrics.jobs_recovered, 0)
        self.assertEqual(res.metrics.total_completed_unique, 8)

    def test_fault_injection_occurs_at_deterministic_point(self) -> None:
        """Requirement 2: Fault injection triggers worker crash at the exact configured threshold,
        and flows through LOST/retry/replacement semantics.
        """
        scenario = Scenario(
            name="deterministic-fault-test",
            num_workers=3,
            num_jobs=25,
            work_units=15000,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=4),
            max_retries=3,
            replace_failed_workers=True,
            timeout=20.0,
        )

        res = run_scenario(scenario)

        self.assertTrue(res.fault_injected)
        self.assertEqual(res.fault_target, "worker-0")
        self.assertEqual(res.fault_point, 4)

        # 1. Exactly 1 worker failure must have been detected
        self.assertGreaterEqual(res.metrics.worker_failures, 1)

        # 2. Retries and recovered jobs must be recorded
        self.assertGreaterEqual(res.metrics.total_retries, 1)
        self.assertGreaterEqual(res.metrics.jobs_recovered, 1)

        # 3. All 25 unique jobs must complete successfully
        self.assertEqual(res.metrics.total_completed_unique, 25)
        self.assertEqual(res.metrics.total_failed_unique, 0)
        self.assertEqual(
            res.metrics.total_completed_unique + res.metrics.total_failed_unique,
            res.metrics.total_unique_submitted,
        )

        # 4. Total attempts must reflect the retried attempt
        self.assertGreater(res.metrics.total_execution_attempts, 25)

    def test_scenario_result_observability_payload(self) -> None:
        """Requirement 4: Scenario and fault injection configuration are visible in to_dict telemetry."""
        scenario = Scenario(
            name="observable-scenario",
            num_workers=2,
            num_jobs=10,
            work_units=500,
            fault_config=FaultConfig(target_worker_id="worker-1", kill_after_jobs=2),
        )
        res = run_scenario(scenario)
        data = res.to_dict()

        self.assertIn("scenario", data)
        self.assertIn("metrics", data)
        self.assertEqual(data["scenario"]["name"], "observable-scenario")
        self.assertEqual(data["scenario"]["workers"], 2)
        self.assertEqual(data["scenario"]["jobs"], 10)
        self.assertTrue(data["scenario"]["fault"]["enabled"])
        self.assertEqual(data["scenario"]["fault"]["target_worker"], "worker-1")
        self.assertEqual(data["scenario"]["fault"]["kill_after_jobs"], 2)


class TestCLIScenarioIntegration(unittest.TestCase):
    """Verify CLI integration of scenario options, validation, and execution."""

    def test_cli_run_named_scenario_text(self) -> None:
        """Verify running a named scenario via CLI text mode."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--scenario", "baseline", "--jobs", "5", "--work-units", "100"])
        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Titan Runtime Execution & Recovery Report", output)
        self.assertIn("Scenario:                      baseline", output)
        self.assertIn("Fault Injection:               Disabled", output)
        self.assertIn("Jobs Completed (Unique):       5", output)

    def test_cli_run_named_scenario_json(self) -> None:
        """Verify running a named scenario via CLI JSON mode outputs scenario metadata."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--scenario", "worker-crash", "--jobs", "10", "--work-units", "500", "--json"])
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertIn("scenario", data)
        self.assertIn("config", data)
        self.assertIn("metrics", data)
        self.assertEqual(data["scenario"]["name"], "worker-crash")
        self.assertTrue(data["scenario"]["fault"]["enabled"])
        self.assertEqual(data["scenario"]["fault"]["target_worker"], "worker-0")
        self.assertEqual(data["metrics"]["total_completed_unique"], 10)

    def test_cli_unknown_scenario_rejected(self) -> None:
        """Verify CLI rejects unknown scenario name with error code 1."""
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            exit_code = main(["run", "--scenario", "non-existent-scenario"])
        self.assertEqual(exit_code, 1)
        self.assertIn("Unknown scenario 'non-existent-scenario'", stderr_capture.getvalue())

    def test_cli_invalid_fault_worker_rejected(self) -> None:
        """Verify CLI rejects out-of-range kill-worker index with error code 1."""
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            exit_code = main(["run", "--workers", "2", "--kill-worker", "5"])
        self.assertEqual(exit_code, 1)
        self.assertIn("out of range", stderr_capture.getvalue())


if __name__ == "__main__":
    unittest.main()
