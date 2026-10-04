"""Tests for Titan Recovery-Policy Experimentation Framework (Prompt 9).

Verifies recovery policy configuration, immutability, fair comparison parameter
preservation, metric extraction, single and repeated trial execution, result
aggregation, policy comparison, and CLI integration.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from titan.bench import CorpusRegistry
from titan.cli import main
from titan.experiment.metrics import (
    METRIC_DEFINITIONS,
    UNAVAILABLE_METRICS,
    ExperimentMetrics,
    extract_experiment_metrics,
)
from titan.experiment.policy import PolicyRegistry, RecoveryPolicy
from titan.experiment.runner import ExperimentRunner
from titan.experiment.trial import (
    ExperimentResult,
    ExperimentTrial,
    MetricStats,
    PolicyComparison,
)
from titan.scenario import FaultConfig, Scenario


class TestRecoveryPolicyModel(unittest.TestCase):
    """Test policy model creation, validation, immutability, and fair comparison rules."""

    def test_policy_creation_and_validation(self) -> None:
        """Valid policy parameters succeed; invalid parameters raise ValueError."""
        p = RecoveryPolicy(
            policy_id="TEST-1",
            name="test-policy",
            description="A test policy",
            replace_failed_workers=True,
            max_retries=2,
            backoff_factor=0.5,
        )
        p.validate()
        self.assertEqual(p.policy_id, "TEST-1")
        self.assertEqual(p.max_retries, 2)
        self.assertTrue(p.replace_failed_workers)

        # Empty ID
        with self.assertRaises(ValueError):
            RecoveryPolicy(policy_id="", name="test", description="").validate()

        # Empty name
        with self.assertRaises(ValueError):
            RecoveryPolicy(policy_id="P1", name="", description="").validate()

        # max_retries < 1
        with self.assertRaises(ValueError):
            RecoveryPolicy(policy_id="P1", name="test", description="", max_retries=0).validate()

        # negative backoff
        with self.assertRaises(ValueError):
            RecoveryPolicy(policy_id="P1", name="test", description="", backoff_factor=-1.0).validate()

    def test_stable_canonical_policy_ids(self) -> None:
        """Canonical recovery policies have stable IDs: R0, R1, R2, R3."""
        PolicyRegistry.initialize_canonical_policies()
        policies = PolicyRegistry.list_all()
        ids = [p.policy_id for p in policies]
        self.assertIn("R0", ids)
        self.assertIn("R1", ids)
        self.assertIn("R2", ids)
        self.assertIn("R3", ids)

        r0 = PolicyRegistry.get("R0")
        self.assertTrue(r0.replace_failed_workers)
        self.assertEqual(r0.max_retries, 3)

        r1 = PolicyRegistry.get("R1")
        self.assertFalse(r1.replace_failed_workers)
        self.assertEqual(r1.max_retries, 3)

        r2 = PolicyRegistry.get("R2")
        self.assertTrue(r2.replace_failed_workers)
        self.assertEqual(r2.max_retries, 1)

        r3 = PolicyRegistry.get("R3")
        self.assertFalse(r3.replace_failed_workers)
        self.assertEqual(r3.max_retries, 1)

    def test_policy_immutability(self) -> None:
        """RecoveryPolicy instances are frozen dataclasses and cannot be mutated."""
        p = PolicyRegistry.get("R0")
        with self.assertRaises((AttributeError, TypeError)):
            p.max_retries = 5  # type: ignore

    def test_policy_registry_operations(self) -> None:
        """Registry manages policy registration, lookup, duplicate checks, and clearing."""
        PolicyRegistry.initialize_canonical_policies()
        self.assertEqual(len(PolicyRegistry.list_all()), 4)

        custom = RecoveryPolicy(
            policy_id="CUSTOM-1",
            name="custom",
            description="custom policy",
            replace_failed_workers=False,
            max_retries=2,
        )
        PolicyRegistry.register(custom)
        self.assertEqual(PolicyRegistry.get("CUSTOM-1").max_retries, 2)

        # Duplicate ID rejected
        with self.assertRaises(ValueError):
            PolicyRegistry.register(custom)

        # Unknown ID lookup
        with self.assertRaises(KeyError):
            PolicyRegistry.get("UNKNOWN_XYZ")

        # Restore canonical policies
        PolicyRegistry.initialize_canonical_policies()
        self.assertEqual(len(PolicyRegistry.list_all()), 4)

    def test_fair_comparison_parameter_preservation(self) -> None:
        """Applying a policy strictly preserves all non-policy scenario parameters."""
        base_scenario = Scenario(
            name="base-scen",
            num_workers=4,
            num_jobs=35,
            work_units=1500,
            pattern="bimodal",
            seed=12345,
            max_retries=3,
            replace_failed_workers=True,
            fault_config=FaultConfig(target_worker_id="worker-2", kill_after_jobs=4),
            duplicate_jobs=("job-000001",),
            timeout=10.0,
        )

        r1 = PolicyRegistry.get("R1")
        derived = r1.apply_to_scenario(base_scenario)

        # Preserved parameters (Fair Comparison invariant)
        self.assertEqual(derived.num_workers, base_scenario.num_workers)
        self.assertEqual(derived.num_jobs, base_scenario.num_jobs)
        self.assertEqual(derived.work_units, base_scenario.work_units)
        self.assertEqual(derived.pattern, base_scenario.pattern)
        self.assertEqual(derived.seed, base_scenario.seed)
        self.assertEqual(derived.fault_config, base_scenario.fault_config)
        self.assertEqual(derived.duplicate_jobs, base_scenario.duplicate_jobs)
        self.assertEqual(derived.timeout, base_scenario.timeout)

        # Overridden policy parameters
        self.assertEqual(derived.replace_failed_workers, r1.replace_failed_workers)
        self.assertEqual(derived.max_retries, r1.max_retries)


class TestExperimentMetrics(unittest.TestCase):
    """Test metric definitions, explicit formulas, and metric honesty boundaries."""

    def test_metric_definitions_registry(self) -> None:
        """Explicit metric formulas, units, scope, and descriptions are documented."""
        required_metrics = [
            "recovery_rate",
            "unrecovered_failure_rate",
            "useful_completions",
            "total_attempts",
            "retry_count",
            "duplicate_work",
            "retry_overhead",
            "lost_work",
            "worker_failures",
            "worker_replacements",
            "wall_clock_duration_sec",
            "recovery_duration_sec",
            "goodput_jobs_per_sec",
            "avg_latency_ms",
        ]
        for mname in required_metrics:
            self.assertIn(mname, METRIC_DEFINITIONS)
            mdef = METRIC_DEFINITIONS[mname]
            self.assertTrue(len(mdef.formula) > 0)
            self.assertTrue(len(mdef.units) > 0)
            self.assertTrue(len(mdef.scope) > 0)
            self.assertTrue(len(mdef.limitations) > 0)

    def test_unavailable_metrics_documented(self) -> None:
        """Intentionally unavailable metrics are cataloged with explicit technical rationales."""
        self.assertIn("cpu_utilization_pct", UNAVAILABLE_METRICS)
        self.assertIn("memory_rss_bytes", UNAVAILABLE_METRICS)
        self.assertIn("network_io_bytes", UNAVAILABLE_METRICS)
        self.assertIn("intra_job_partial_work_lost", UNAVAILABLE_METRICS)
        self.assertIn("failure_detection_latency", UNAVAILABLE_METRICS)


class TestExperimentRunnerExecution(unittest.TestCase):
    """Test real scenario execution, repeated trials, aggregation, and policy comparison."""

    def setUp(self) -> None:
        CorpusRegistry.initialize_canonical_corpus()
        PolicyRegistry.initialize_canonical_policies()

    def test_single_trial_baseline_r0(self) -> None:
        """Execute TB-B-001 under Baseline Policy R0."""
        runner = ExperimentRunner()
        scen = CorpusRegistry.get("TB-B-001")
        policy = PolicyRegistry.get("R0")

        with tempfile.TemporaryDirectory() as tmpdir:
            trial = runner.run_trial(
                benchmark_scenario=scen,
                policy=policy,
                repetition=1,
                save_artifacts=True,
                trial_dir=Path(tmpdir),
            )
            self.assertEqual(trial.execution_status, "COMPLETED")
            self.assertTrue(trial.replay_valid)
            self.assertEqual(trial.analysis_status, "RECOVERED")
            self.assertEqual(trial.metrics.completed_jobs, 10)
            self.assertEqual(trial.metrics.failed_jobs, 0)
            self.assertEqual(trial.metrics.recovery_rate, 1.0)
            self.assertEqual(trial.metrics.worker_failures, 1)
            self.assertEqual(trial.metrics.worker_replacements, 1)
            self.assertEqual(trial.metrics.retries, 1)
            self.assertEqual(trial.metrics.duplicate_work, 1)
            self.assertEqual(trial.metrics.lost_work, 1)
            self.assertIn("trial", trial.artifacts)
            self.assertIn("trace", trial.artifacts)

    def test_single_trial_no_replacement_r1(self) -> None:
        """Execute TB-B-001 under Policy R1 (No Worker Replacement)."""
        runner = ExperimentRunner()
        scen = CorpusRegistry.get("TB-B-001")
        policy = PolicyRegistry.get("R1")

        trial = runner.run_trial(
            benchmark_scenario=scen,
            policy=policy,
            repetition=1,
            save_artifacts=False,
        )
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertTrue(trial.replay_valid)
        self.assertEqual(trial.analysis_status, "RECOVERED")
        self.assertEqual(trial.metrics.completed_jobs, 10)
        self.assertEqual(trial.metrics.failed_jobs, 0)
        self.assertEqual(trial.metrics.worker_failures, 1)
        self.assertEqual(trial.metrics.worker_replacements, 0)  # R1 does NOT replace
        self.assertEqual(trial.metrics.retries, 1)

    def test_single_trial_limited_retry_r2(self) -> None:
        """Execute TB-E-001 under Policy R2 (Limited Retry)."""
        runner = ExperimentRunner()
        scen = CorpusRegistry.get("TB-E-001")
        policy = PolicyRegistry.get("R2")

        trial = runner.run_trial(
            benchmark_scenario=scen,
            policy=policy,
            repetition=1,
            save_artifacts=False,
        )
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertTrue(trial.replay_valid)
        self.assertEqual(trial.analysis_status, "UNRECOVERED")
        self.assertEqual(trial.metrics.completed_jobs, 5)
        self.assertEqual(trial.metrics.failed_jobs, 1)
        self.assertEqual(trial.metrics.recovery_rate, 0.0)
        self.assertEqual(trial.metrics.retries, 0)  # max_retries=1 prevents retry

    def test_single_trial_minimal_recovery_r3(self) -> None:
        """Execute TB-B-001 under Policy R3 (Minimal Recovery: No replacement + max_retries=1)."""
        runner = ExperimentRunner()
        scen = CorpusRegistry.get("TB-B-001")
        policy = PolicyRegistry.get("R3")

        trial = runner.run_trial(
            benchmark_scenario=scen,
            policy=policy,
            repetition=1,
            save_artifacts=False,
        )
        self.assertEqual(trial.execution_status, "COMPLETED")
        self.assertTrue(trial.replay_valid)
        self.assertEqual(trial.analysis_status, "UNRECOVERED")
        self.assertEqual(trial.metrics.completed_jobs, 9)
        self.assertEqual(trial.metrics.failed_jobs, 1)
        self.assertEqual(trial.metrics.worker_replacements, 0)
        self.assertEqual(trial.metrics.retries, 0)

    def test_repeated_trial_aggregation(self) -> None:
        """Execute 2 repeated trials and verify aggregation metrics in ExperimentResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ExperimentRunner(output_base_dir=tmpdir)
            result = runner.run_experiment(
                scenario_id="TB-A-001",
                policy_id="R0",
                repetitions=2,
            )
            self.assertEqual(result.repetitions, 2)
            self.assertEqual(result.successful_trials, 2)
            self.assertEqual(result.failed_trials, 0)
            self.assertEqual(result.recovery_rate, 1.0)
            self.assertEqual(len(result.trials), 2)

            comp_stats = result.metric_summaries["completed_jobs"]
            self.assertEqual(comp_stats.count, 2)
            self.assertEqual(comp_stats.mean, 10.0)

            dur_stats = result.metric_summaries["wall_clock_duration_sec"]
            self.assertEqual(dur_stats.count, 2)
            self.assertTrue(dur_stats.mean > 0.0)

            # Check that files were created
            summary_file = Path(tmpdir) / result.experiment_id / "summary.json"
            exp_file = Path(tmpdir) / result.experiment_id / "experiment.json"
            self.assertTrue(summary_file.exists())
            self.assertTrue(exp_file.exists())

    def test_trial_and_result_serialization_roundtrip(self) -> None:
        """ExperimentTrial and ExperimentResult serialize to dict/JSON and reconstruct accurately."""
        runner = ExperimentRunner()
        scen = CorpusRegistry.get("TB-A-001")
        policy = PolicyRegistry.get("R0")
        trial = runner.run_trial(scen, policy, repetition=1, save_artifacts=False)

        # Trial roundtrip
        trial_dict = trial.to_dict()
        trial_reconstructed = ExperimentTrial.from_dict(trial_dict)
        self.assertEqual(trial_reconstructed.experiment_id, trial.experiment_id)
        self.assertEqual(trial_reconstructed.metrics.completed_jobs, trial.metrics.completed_jobs)

        # Result roundtrip
        exp_res = ExperimentResult.aggregate(
            experiment_id="TEST_EXP",
            scenario_id="TB-A-001",
            scenario_class="CLASS_A_BASELINE",
            policy_id="R0",
            policy_config=policy.to_dict(),
            trials=[trial],
        )
        res_dict = exp_res.to_dict()
        res_json = exp_res.to_json()
        res_reconstructed = ExperimentResult.from_dict(json.loads(res_json))
        self.assertEqual(res_reconstructed.experiment_id, exp_res.experiment_id)
        self.assertEqual(res_reconstructed.recovery_rate, exp_res.recovery_rate)
        self.assertEqual(len(res_reconstructed.trials), 1)

    def test_policy_comparison_table_and_observations(self) -> None:
        """Compare R0 and R1 on TB-B-001; verify comparison table and observed differences."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ExperimentRunner(output_base_dir=tmpdir)
            comparison = runner.compare_policies(
                scenario_id="TB-B-001",
                policy_ids=["R0", "R1"],
                repetitions=1,
            )
            self.assertEqual(comparison.scenario_id, "TB-B-001")
            self.assertEqual(comparison.policies, ["R0", "R1"])
            self.assertIn("R0", comparison.results)
            self.assertIn("R1", comparison.results)

            table_str = comparison.to_table()
            self.assertIn("Recovery Rate (%)", table_str)
            self.assertIn("Worker Replacements (mean)", table_str)
            self.assertIn("R0", table_str)
            self.assertIn("R1", table_str)

            self.assertTrue(len(comparison.observed_differences) == 2)
            # R0 has 1 replacement, R1 has 0 replacements
            self.assertIn("Replacements = 1", comparison.observed_differences[0])
            self.assertIn("Replacements = 0", comparison.observed_differences[1])

            comp_dict = comparison.to_dict()
            self.assertEqual(comp_dict["scenario_id"], "TB-B-001")

    def test_run_config_runner(self) -> None:
        """Execute experiment from a configuration JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "scenario_id": "TB-A-001",
                        "policy_id": "R0",
                        "repetitions": 1,
                    },
                    f,
                )

            runner = ExperimentRunner(output_base_dir=tmpdir)
            res = runner.run_config(config_file)
            self.assertIsInstance(res, ExperimentResult)
            self.assertEqual(res.scenario_id, "TB-A-001")
            self.assertEqual(res.policy_id, "R0")


class TestCLIExperimentIntegration(unittest.TestCase):
    """Test CLI commands for experiment listing, running, and comparison."""

    def test_cli_list_policies(self) -> None:
        """CLI experiment list-policies prints registered policies."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["experiment", "list-policies"])
        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("Titan Recovery Policies", output)
        self.assertIn("R0", output)
        self.assertIn("R1", output)
        self.assertIn("R2", output)
        self.assertIn("R3", output)

    def test_cli_list_policies_json(self) -> None:
        """CLI experiment list-policies --json outputs valid JSON."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["experiment", "list-policies", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 4)
        policy_ids = [p["policy_id"] for p in data]
        self.assertIn("R0", policy_ids)
        self.assertIn("R3", policy_ids)

    def test_cli_run_experiment_text(self) -> None:
        """CLI experiment run executes trial and prints summary report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["experiment", "run", "TB-A-001", "R0", "--trials", "1", "-o", tmpdir])
            self.assertEqual(code, 0)
            output = buf.getvalue()
            self.assertIn("Titan Recovery-Policy Experiment Result", output)
            self.assertIn("TB-A-001", output)
            self.assertIn("R0", output)

    def test_cli_run_experiment_json(self) -> None:
        """CLI experiment run with --json outputs machine-readable ExperimentResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["experiment", "run", "TB-A-001", "R0", "--trials", "1", "-o", tmpdir, "--json"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["scenario_id"], "TB-A-001")
            self.assertEqual(data["policy_id"], "R0")
            self.assertEqual(data["recovery_rate"], 1.0)

    def test_cli_compare_policies_text(self) -> None:
        """CLI experiment compare prints side-by-side comparison table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["experiment", "compare", "TB-B-001", "--policies", "R0,R1", "--trials", "1", "-o", tmpdir])
            self.assertEqual(code, 0)
            output = buf.getvalue()
            self.assertIn("Titan Recovery Policy Comparison", output)
            self.assertIn("R0", output)
            self.assertIn("R1", output)
            self.assertIn("Observed Differences:", output)


if __name__ == "__main__":
    unittest.main()
