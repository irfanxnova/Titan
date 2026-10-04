"""Automated test suite for TitanBench failure corpus, runner, and oracles."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path for direct invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.bench import (
    BenchmarkArtifacts,
    BenchmarkResult,
    BenchmarkScenario,
    BenchmarkStatus,
    BenchmarkSummary,
    CorpusRegistry,
    ExpectedBehavior,
    ScenarioClass,
    TitanBenchRunner,
)
from titan.cli import main
from titan.scenario import FaultConfig, Scenario


class TestTitanBenchCorpus(unittest.TestCase):
    """Verify registry properties, canonical scenario definitions, and classes."""

    def setUp(self) -> None:
        CorpusRegistry.initialize_canonical_corpus()

    def test_canonical_scenario_classes_represented(self) -> None:
        """Verify registry contains all canonical scenario classes A through I."""
        scenarios = CorpusRegistry.list_all()
        classes_present = {s.scenario_class for s in scenarios}

        expected_classes = {
            ScenarioClass.CLASS_A_BASELINE,
            ScenarioClass.CLASS_B_SINGLE_WORKER_FAILURE,
            ScenarioClass.CLASS_C_IN_FLIGHT_FAILURE,
            ScenarioClass.CLASS_D_REPEATED_FAILURE,
            ScenarioClass.CLASS_E_RETRY_PRESSURE,
            ScenarioClass.CLASS_F_DUPLICATE_STALE,
            ScenarioClass.CLASS_G_CAPACITY_LOSS,
            ScenarioClass.CLASS_H_ADVERSARIAL_TIMING,
            ScenarioClass.CLASS_I_LARGE_WORKLOAD,
        }

        self.assertTrue(expected_classes.issubset(classes_present))
        self.assertEqual(len(scenarios), 9)

    def test_scenario_ids_unique_and_stable(self) -> None:
        """Verify scenario IDs are unique, non-empty, and match deterministic conventions."""
        scenarios = CorpusRegistry.list_all()
        ids = [s.scenario_id for s in scenarios]
        self.assertEqual(len(ids), len(set(ids)))

        expected_ids = [
            "TB-A-001",
            "TB-B-001",
            "TB-C-001",
            "TB-D-001",
            "TB-E-001",
            "TB-F-001",
            "TB-G-001",
            "TB-H-001",
            "TB-I-001",
        ]
        self.assertEqual(ids, expected_ids)

    def test_scenario_validation_and_integrity(self) -> None:
        """Verify each registered scenario passes validation without error."""
        for scenario in CorpusRegistry.list_all():
            scenario.validate()

    def test_registry_lookup_by_id_and_class(self) -> None:
        """Verify registry lookup by stable ID and by category class."""
        scen_a = CorpusRegistry.get("TB-A-001")
        self.assertEqual(scen_a.scenario_class, ScenarioClass.CLASS_A_BASELINE)

        by_class = CorpusRegistry.list_by_class(ScenarioClass.CLASS_B_SINGLE_WORKER_FAILURE)
        self.assertEqual(len(by_class), 1)
        self.assertEqual(by_class[0].scenario_id, "TB-B-001")

        with self.assertRaises(KeyError):
            CorpusRegistry.get("NON_EXISTENT_ID")

    def test_duplicate_registration_rejected(self) -> None:
        """Verify registering a scenario with an existing ID raises ValueError."""
        scen_a = CorpusRegistry.get("TB-A-001")
        with self.assertRaises(ValueError):
            CorpusRegistry.register(scen_a)

    def test_benchmark_scenario_serialization_roundtrip(self) -> None:
        """Verify BenchmarkScenario serialization to and from dictionary/JSON."""
        scen = CorpusRegistry.get("TB-B-001")
        scen_dict = scen.to_dict()
        scen_json = scen.to_json()

        self.assertIn("TB-B-001", scen_json)
        reconstructed = BenchmarkScenario.from_dict(json.loads(scen_json))

        self.assertEqual(reconstructed.scenario_id, scen.scenario_id)
        self.assertEqual(reconstructed.scenario_class, scen.scenario_class)
        self.assertEqual(reconstructed.name, scen.name)
        self.assertEqual(reconstructed.scenario.num_workers, scen.scenario.num_workers)
        self.assertEqual(reconstructed.scenario.num_jobs, scen.scenario.num_jobs)


class TestTitanBenchExecution(unittest.TestCase):
    """Verify execution of TitanBench scenarios through the runner and oracles."""

    def setUp(self) -> None:
        CorpusRegistry.initialize_canonical_corpus()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_baseline_scenario_execution(self) -> None:
        """Verify CLASS A (baseline) executes, replays, and passes clean."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-A-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.replay_outcome, "VALID")
        self.assertEqual(result.root_failures_count, 0)
        self.assertEqual(result.recovery_status, "CLEAN")
        self.assertEqual(result.completed_jobs, 10)
        self.assertEqual(result.failed_jobs, 0)
        self.assertEqual(result.worker_failures, 0)

    def test_single_worker_failure_execution(self) -> None:
        """Verify CLASS B (single worker failure) recovers and passes."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-B-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.root_failures_count, 1)
        self.assertEqual(result.recovery_status, "RECOVERED")
        self.assertEqual(result.completed_jobs, 10)
        self.assertEqual(result.worker_failures, 1)
        self.assertEqual(result.worker_replacements, 1)
        self.assertGreaterEqual(result.retries, 1)

    def test_in_flight_failure_execution(self) -> None:
        """Verify CLASS C (in-flight failure) executes and passes."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-C-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.root_failures_count, 1)
        self.assertEqual(result.recovery_status, "RECOVERED")
        self.assertEqual(result.completed_jobs, 8)
        self.assertEqual(result.worker_failures, 1)

    def test_repeated_failure_execution(self) -> None:
        """Verify CLASS D (repeated failure across workers) executes and passes."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-D-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.root_failures_count, 2)
        self.assertEqual(result.recovery_status, "RECOVERED")
        self.assertEqual(result.worker_failures, 2)
        self.assertEqual(result.worker_replacements, 2)
        self.assertEqual(result.completed_jobs, 15)

    def test_retry_pressure_and_expected_failure(self) -> None:
        """Verify CLASS E (retry pressure exhaustion) passes because expected failure matches oracle."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-E-001")
        result = runner.run_scenario(scenario)

        # Must PASS because the scenario explicitly expected UNRECOVERED failure!
        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.root_failures_count, 1)
        self.assertEqual(result.recovery_status, "UNRECOVERED")
        self.assertEqual(result.failed_jobs, 1)
        self.assertEqual(result.completed_jobs, 5)

    def test_duplicate_completion_execution(self) -> None:
        """Verify CLASS F (duplicate completion) executes and suppresses duplicates."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-F-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.duplicate_results_ignored, 2)
        self.assertEqual(result.completed_jobs, 10)
        self.assertEqual(result.failed_jobs, 0)

    def test_capacity_loss_execution(self) -> None:
        """Verify CLASS G (worker capacity loss) executes without replacement."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-G-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.worker_failures, 1)
        self.assertEqual(result.worker_replacements, 0)
        self.assertEqual(result.recovery_status, "RECOVERED")
        self.assertEqual(result.completed_jobs, 10)

    def test_adversarial_timing_execution(self) -> None:
        """Verify CLASS H (adversarial kill on job 0) executes and recovers."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-H-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.root_failures_count, 1)
        self.assertEqual(result.recovery_status, "RECOVERED")
        self.assertEqual(result.completed_jobs, 8)

    def test_large_workload_execution(self) -> None:
        """Verify CLASS I (large workload) executes and passes."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-I-001")
        result = runner.run_scenario(scenario)

        self.assertEqual(result.status, BenchmarkStatus.PASS)
        self.assertTrue(result.replay_valid)
        self.assertEqual(result.completed_jobs, 40)
        self.assertEqual(result.failed_jobs, 0)
        self.assertEqual(result.root_failures_count, 0)

    def test_artifact_files_generation(self) -> None:
        """Verify artifact files (scenario, trace, replay, analysis, result) are persisted."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-A-001")
        result = runner.run_scenario(scenario)

        artifacts = result.artifacts
        self.assertIsNotNone(artifacts.scenario_path)
        self.assertIsNotNone(artifacts.trace_path)
        self.assertIsNotNone(artifacts.replay_path)
        self.assertIsNotNone(artifacts.analysis_path)
        self.assertIsNotNone(artifacts.result_path)

        for path in [
            artifacts.scenario_path,
            artifacts.trace_path,
            artifacts.replay_path,
            artifacts.analysis_path,
            artifacts.result_path,
        ]:
            self.assertTrue(os.path.exists(path), f"Expected artifact {path} to exist")

        with open(artifacts.result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["scenario_id"], "TB-A-001")
            self.assertEqual(data["status"], "PASS")

    def test_benchmark_result_json_roundtrip(self) -> None:
        """Verify BenchmarkResult serialization to and from JSON."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-B-001")
        result = runner.run_scenario(scenario)

        json_str = result.to_json()
        reconstructed = BenchmarkResult.from_dict(json.loads(json_str))

        self.assertEqual(reconstructed.scenario_id, result.scenario_id)
        self.assertEqual(reconstructed.status, result.status)
        self.assertEqual(reconstructed.root_failures_count, result.root_failures_count)
        self.assertEqual(reconstructed.recovery_status, result.recovery_status)
        self.assertEqual(reconstructed.total_jobs, result.total_jobs)
        self.assertEqual(reconstructed.completed_jobs, result.completed_jobs)
        self.assertEqual(reconstructed.worker_failures, result.worker_failures)

    def test_oracle_failure_detection(self) -> None:
        """Verify that if observed behavior does not match expectations, FAIL status is returned."""
        # Baseline scenario expects 0 root failures; if we set expectation of 5 root failures, it must FAIL
        baseline_scen = CorpusRegistry.get("TB-A-001")
        mismatched_scen = BenchmarkScenario(
            scenario_id="TB-MISMATCH",
            name="mismatched-expectation",
            scenario_class=ScenarioClass.CLASS_A_BASELINE,
            description="Testing oracle detection of mismatch.",
            scenario=baseline_scen.scenario,
            expected_behavior=ExpectedBehavior(
                expected_root_failures=5,  # Mismatch! Real baseline has 0
            ),
        )

        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        result = runner.run_scenario(mismatched_scen)

        self.assertEqual(result.status, BenchmarkStatus.FAIL)
        self.assertIn("Root failure count mismatch", result.reason)

    def test_repeated_deterministic_execution_stability(self) -> None:
        """Verify repeated execution of the same deterministic scenario preserves canonical outcome."""
        runner = TitanBenchRunner(output_base_dir=self.temp_dir.name)
        scenario = CorpusRegistry.get("TB-A-001")

        res1 = runner.run_scenario(scenario)
        res2 = runner.run_scenario(scenario)

        self.assertEqual(res1.status, res2.status)
        self.assertEqual(res1.completed_jobs, res2.completed_jobs)
        self.assertEqual(res1.total_attempts, res2.total_attempts)
        self.assertEqual(res1.retries, res2.retries)
        self.assertEqual(res1.worker_failures, res2.worker_failures)
        self.assertEqual(res1.root_failures_count, res2.root_failures_count)
        self.assertEqual(res1.recovery_status, res2.recovery_status)


class TestTitanBenchCLI(unittest.TestCase):
    """Verify TitanBench CLI commands (bench list, bench run, bench run-all)."""

    def setUp(self) -> None:
        CorpusRegistry.initialize_canonical_corpus()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cli_bench_list(self) -> None:
        """Verify 'titan bench list' prints all scenarios."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["bench", "list"])

        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("TB-A-001", output)
        self.assertIn("TB-I-001", output)
        self.assertIn("Total registered scenarios: 9", output)

    def test_cli_bench_list_json(self) -> None:
        """Verify 'titan bench list --json' outputs valid JSON array."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["bench", "list", "--json"])

        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 9)

    def test_cli_bench_run_single(self) -> None:
        """Verify 'titan bench run TB-A-001' executes and exits 0."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["bench", "run", "TB-A-001", "--output-dir", self.temp_dir.name])

        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("TB-A-001", output)
        self.assertIn("PASS", output)

    def test_cli_bench_run_json(self) -> None:
        """Verify 'titan bench run TB-A-001 --json' outputs valid benchmark result JSON."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["bench", "run", "TB-A-001", "--output-dir", self.temp_dir.name, "--json"])

        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["scenario_id"], "TB-A-001")
        self.assertEqual(data["status"], "PASS")

    def test_cli_bench_run_invalid_id(self) -> None:
        """Verify running a non-existent scenario ID returns non-zero error."""
        buf = io.StringIO()
        err_buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stderr", err_buf):
            code = main(["bench", "run", "INVALID_ID"])

        self.assertEqual(code, 1)
        self.assertIn("Unknown benchmark scenario ID", err_buf.getvalue())

    def test_cli_status_includes_titanbench(self) -> None:
        """Verify 'titan status' reports Milestone 8 and TitanBench canonical corpus."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["status"])

        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("Milestone:   8", output)
        self.assertIn("TitanBench Active", output)
        self.assertIn("TB-A-001", output)


if __name__ == "__main__":
    unittest.main()
