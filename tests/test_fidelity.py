"""Tests for Titan's replay fidelity and divergence detection engine."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path for direct invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.cli import main
from titan.replay import (
    DivergenceCategory,
    DivergenceRecord,
    FidelityResult,
    ReplayEngine,
    ReplayFidelityEngine,
    ReplayJobStatus,
    ReplayResult,
)
from titan.scenario import FaultConfig, Scenario, get_scenario, run_scenario
from titan.trace import EventType, ExecutionTrace, TraceEvent


class TestFidelityResultAndSerialization(unittest.TestCase):
    """Verify FidelityResult and DivergenceRecord schemas and serialization."""

    def test_divergence_record_to_dict_and_from_dict(self) -> None:
        """Verify DivergenceRecord serialization and deserialization."""
        rec = DivergenceRecord(
            category=DivergenceCategory.OWNERSHIP,
            message="Ownership mismatch",
            seq=12,
            expected="worker-0",
            observed="worker-1",
            job_id="job-000001",
            attempt_id=1,
            worker_id="worker-1",
            details={"phase": "dispatch"},
        )
        data = rec.to_dict()
        self.assertEqual(data["category"], "OWNERSHIP")
        self.assertEqual(data["seq"], 12)
        self.assertEqual(data["expected"], "worker-0")
        self.assertEqual(data["observed"], "worker-1")
        self.assertEqual(data["job_id"], "job-000001")
        self.assertEqual(data["attempt_id"], 1)
        self.assertEqual(data["worker_id"], "worker-1")
        self.assertEqual(data["details"], {"phase": "dispatch"})

        recovered = DivergenceRecord.from_dict(data)
        self.assertEqual(recovered, rec)

    def test_fidelity_result_dict_and_json_roundtrip(self) -> None:
        """Verify FidelityResult serialization and deserialization to/from JSON."""
        rec = DivergenceRecord(
            category=DivergenceCategory.EVENT,
            message="Event type mismatch",
            seq=5,
            expected="JOB_STARTED",
            observed="JOB_FAILED",
            job_id="job-000000",
            attempt_id=1,
            worker_id="worker-0",
        )
        result = FidelityResult(
            equivalent=False,
            total_comparisons=50,
            divergence_count=1,
            divergences=[rec],
            first_divergence=rec,
            summary_by_category={"EVENT": 1},
            expected_events_count=20,
            observed_events_count=20,
        )

        data = result.to_dict()
        self.assertFalse(data["equivalent"])
        self.assertEqual(data["total_comparisons"], 50)
        self.assertEqual(data["divergence_count"], 1)
        self.assertIsNotNone(data["first_divergence"])

        json_str = result.to_json(indent=2)
        parsed = json.loads(json_str)
        self.assertFalse(parsed["equivalent"])

        recovered = FidelityResult.from_dict(parsed)
        self.assertEqual(recovered.equivalent, result.equivalent)
        self.assertEqual(recovered.total_comparisons, result.total_comparisons)
        self.assertEqual(recovered.divergence_count, result.divergence_count)
        self.assertEqual(recovered.first_divergence, result.first_divergence)
        self.assertEqual(len(recovered.divergences), 1)


class TestReplayFidelityExactMatch(unittest.TestCase):
    """Verify that identical execution traces report equivalence with zero divergences."""

    def test_exact_match_baseline_scenario(self) -> None:
        """Baseline scenario trace compared against itself must report equivalence."""
        scenario = get_scenario("baseline")
        res = run_scenario(scenario)
        self.assertIsNotNone(res.trace)

        fidelity = ReplayFidelityEngine.compare(res.trace, res.trace)
        self.assertTrue(fidelity.equivalent)
        self.assertEqual(fidelity.divergence_count, 0)
        self.assertIsNone(fidelity.first_divergence)
        self.assertEqual(fidelity.divergences, [])
        self.assertGreater(fidelity.total_comparisons, 0)
        self.assertEqual(fidelity.expected_events_count, len(res.trace.events))
        self.assertEqual(fidelity.observed_events_count, len(res.trace.events))

    def test_exact_match_worker_crash_scenario(self) -> None:
        """Worker crash scenario trace compared against itself must report equivalence."""
        scenario = get_scenario("worker-crash")
        res = run_scenario(scenario)
        self.assertIsNotNone(res.trace)

        fidelity = ReplayEngine.compare(res.trace, res.trace)
        self.assertTrue(fidelity.equivalent)
        self.assertEqual(fidelity.divergence_count, 0)
        self.assertIsNone(fidelity.first_divergence)
        self.assertGreater(fidelity.total_comparisons, 0)

    def test_identical_scenario_runs_fidelity(self) -> None:
        """Two separate runs of the identical deterministic single-worker scenario produce equivalent replay."""
        scenario1 = Scenario(
            name="det-fidelity-1",
            num_workers=1,
            num_jobs=5,
            work_units=100,
            seed=42,
        )
        scenario2 = Scenario(
            name="det-fidelity-2",
            num_workers=1,
            num_jobs=5,
            work_units=100,
            seed=42,
        )

        res1 = run_scenario(scenario1)
        res2 = run_scenario(scenario2)

        self.assertIsNotNone(res1.trace)
        self.assertIsNotNone(res2.trace)

        fidelity = ReplayFidelityEngine.compare(res1.trace, res2.trace)
        self.assertTrue(fidelity.equivalent)
        self.assertEqual(fidelity.divergence_count, 0)


class TestIntentionalDivergenceDetection(unittest.TestCase):
    """Verify detection of intentional divergences across all canonical categories."""

    def setUp(self) -> None:
        """Generate baseline and worker-crash traces for testing."""
        self.base_res = run_scenario(get_scenario("baseline"))
        self.assertIsNotNone(self.base_res.trace)
        self.base_events = self.base_res.trace.to_list()

        self.crash_res = run_scenario(get_scenario("worker-crash"))
        self.assertIsNotNone(self.crash_res.trace)
        self.crash_events = self.crash_res.trace.to_list()

    def test_changed_event_type_divergence(self) -> None:
        """Changing an event type must trigger EVENT divergence at that exact sequence."""
        modified = [dict(e) for e in self.base_events]
        # Change event at index 6 from JOB_ASSIGNED to JOB_STARTED
        target_seq = modified[6]["seq"]
        original_type = modified[6]["event_type"]
        modified[6]["event_type"] = "JOB_STARTED"

        fidelity = ReplayFidelityEngine.compare(self.base_events, modified)
        self.assertFalse(fidelity.equivalent)
        self.assertGreater(fidelity.divergence_count, 0)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.EVENT)
        self.assertEqual(first.seq, target_seq)
        self.assertEqual(first.expected, original_type)
        self.assertEqual(first.observed, "JOB_STARTED")
        self.assertIn("EVENT", fidelity.summary_by_category)

    def test_changed_worker_ownership_divergence(self) -> None:
        """Changing assigned worker must trigger OWNERSHIP divergence."""
        modified = [dict(e) for e in self.base_events]
        # Find first JOB_ASSIGNED event
        assigned_idx = next(i for i, e in enumerate(modified) if e["event_type"] == "JOB_ASSIGNED")
        target_event = modified[assigned_idx]
        orig_worker = target_event["worker_id"]
        new_worker = "worker-99"
        target_event["worker_id"] = new_worker

        fidelity = ReplayFidelityEngine.compare(self.base_events, modified)
        self.assertFalse(fidelity.equivalent)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.OWNERSHIP)
        self.assertEqual(first.seq, target_event["seq"])
        self.assertEqual(first.expected, orig_worker)
        self.assertEqual(first.observed, new_worker)
        self.assertEqual(first.job_id, target_event["job_id"])
        self.assertEqual(first.attempt_id, target_event["attempt_id"])
        self.assertIn("OWNERSHIP", fidelity.summary_by_category)

    def test_changed_retry_information_divergence(self) -> None:
        """Changing retry attempt identity must trigger RETRY divergence."""
        modified = [dict(e) for e in self.crash_events]
        # Find RETRY_SCHEDULED event
        retry_idx = next(i for i, e in enumerate(modified) if e["event_type"] == "RETRY_SCHEDULED")
        target_event = modified[retry_idx]
        orig_attempt = target_event["attempt_id"]
        target_event["attempt_id"] = orig_attempt + 5

        fidelity = ReplayFidelityEngine.compare(self.crash_events, modified)
        self.assertFalse(fidelity.equivalent)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.RETRY)
        self.assertEqual(first.seq, target_event["seq"])
        self.assertEqual(first.expected, orig_attempt)
        self.assertEqual(first.observed, orig_attempt + 5)
        self.assertIn("RETRY", fidelity.summary_by_category)

    def test_changed_terminal_outcome_divergence(self) -> None:
        """Changing job result outcome must trigger OUTCOME divergence."""
        modified = [dict(e) for e in self.base_events]
        # Find first JOB_COMPLETED event
        comp_idx = next(i for i, e in enumerate(modified) if e["event_type"] == "JOB_COMPLETED")
        target_event = modified[comp_idx]
        orig_result = target_event["data"].get("result")
        target_event["data"] = dict(target_event["data"])
        target_event["data"]["result"] = (orig_result or 0) + 99999

        fidelity = ReplayFidelityEngine.compare(self.base_events, modified)
        self.assertFalse(fidelity.equivalent)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.OUTCOME)
        self.assertEqual(first.seq, target_event["seq"])
        self.assertEqual(first.expected, orig_result)
        self.assertEqual(first.observed, (orig_result or 0) + 99999)
        self.assertIn("OUTCOME", fidelity.summary_by_category)

    def test_changed_worker_lifecycle_divergence(self) -> None:
        """Changing worker failure entity must trigger WORKER divergence."""
        modified = [dict(e) for e in self.crash_events]
        # Find WORKER_FAILED event
        failed_idx = next(i for i, e in enumerate(modified) if e["event_type"] == "WORKER_FAILED")
        target_event = modified[failed_idx]
        orig_worker = target_event["worker_id"]
        target_event["worker_id"] = "worker-alien"

        fidelity = ReplayFidelityEngine.compare(self.crash_events, modified)
        self.assertFalse(fidelity.equivalent)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.WORKER)
        self.assertEqual(first.seq, target_event["seq"])
        self.assertEqual(first.expected, orig_worker)
        self.assertEqual(first.observed, "worker-alien")
        self.assertIn("WORKER", fidelity.summary_by_category)

    def test_changed_job_state_divergence(self) -> None:
        """State-level divergence between reconstructed job statuses is detected."""
        res_exp = ReplayEngine.replay(self.base_events)
        res_obs = ReplayResult(
            valid=res_exp.valid,
            total_events=res_exp.total_events,
            final_run_state=res_exp.final_run_state,
            reconstructed_job_states=dict(res_exp.reconstructed_job_states),
            reconstructed_worker_states=dict(res_exp.reconstructed_worker_states),
            attempts=res_exp.attempts,
            retries=res_exp.retries,
            worker_failures=res_exp.worker_failures,
            worker_replacements=res_exp.worker_replacements,
            validation_errors=list(res_exp.validation_errors),
            summary_metrics=dict(res_exp.summary_metrics),
        )
        # Mutate one job state to a non-terminal state
        target_job = sorted(res_obs.reconstructed_job_states.keys())[0]
        res_obs.reconstructed_job_states[target_job] = "RUNNING"

        fidelity = ReplayFidelityEngine.compare_replay_results(res_exp, res_obs)
        self.assertFalse(fidelity.equivalent)
        self.assertIsNotNone(fidelity.first_divergence)

        first = fidelity.first_divergence
        self.assertEqual(first.category, DivergenceCategory.STATE)
        self.assertEqual(first.job_id, target_job)
        self.assertEqual(first.expected, "COMPLETED")
        self.assertEqual(first.observed, "RUNNING")
        self.assertIn("STATE", fidelity.summary_by_category)

    def test_first_divergence_is_deterministic(self) -> None:
        """The first divergence reported across multiple evaluations must be strictly identical."""
        modified = [dict(e) for e in self.base_events]
        # Introduce divergences at multiple positions
        modified[3]["worker_id"] = "divergent-worker-1"
        modified[8]["worker_id"] = "divergent-worker-2"
        modified[15]["worker_id"] = "divergent-worker-3"

        first_divs = []
        for _ in range(5):
            res = ReplayFidelityEngine.compare(self.base_events, modified)
            self.assertIsNotNone(res.first_divergence)
            first_divs.append((res.first_divergence.category, res.first_divergence.seq, res.first_divergence.expected))

        # All 5 runs must report the exact same first divergence at sequence index 3
        self.assertEqual(len(set(first_divs)), 1)
        self.assertEqual(first_divs[0][1], modified[3]["seq"])

    def test_missing_and_extra_events_divergence(self) -> None:
        """Detect missing events when observed trace is truncated, and extra events when appended."""
        # Truncated observed trace
        truncated = self.base_events[:-3]
        fidelity_trunc = ReplayFidelityEngine.compare(self.base_events, truncated)
        self.assertFalse(fidelity_trunc.equivalent)
        self.assertIsNotNone(fidelity_trunc.first_divergence)
        self.assertEqual(fidelity_trunc.first_divergence.category, DivergenceCategory.EVENT)
        self.assertIn("Missing observed event", fidelity_trunc.first_divergence.message)

        # Extra events in observed trace
        extra = list(self.base_events)
        extra.append(
            {
                "seq": len(extra) + 1,
                "event_type": "WORKER_EXITED",
                "timestamp": 999.0,
                "job_id": None,
                "attempt_id": None,
                "worker_id": "worker-extra",
                "data": {},
            }
        )
        fidelity_extra = ReplayFidelityEngine.compare(self.base_events, extra)
        self.assertFalse(fidelity_extra.equivalent)
        self.assertIsNotNone(fidelity_extra.first_divergence)
        self.assertEqual(fidelity_extra.first_divergence.category, DivergenceCategory.EVENT)
        self.assertIn("Unexpected extra observed event", fidelity_extra.first_divergence.message)


class TestCLIFidelityIntegration(unittest.TestCase):
    """Verify CLI replay fidelity comparison options."""

    def test_cli_replay_compare_equivalent(self) -> None:
        """CLI replay with --compare reports REPLAY EQUIVALENT with exit code 0."""
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f_exp:
            trace_path = f_exp.name

        try:
            # Generate trace
            code = main(["run", "--scenario", "baseline", "--trace-file", trace_path])
            self.assertEqual(code, 0)

            # Compare against itself
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", trace_path, "--compare", trace_path])

            self.assertEqual(exit_code, 0)
            output = stdout_capture.getvalue()
            self.assertIn("Titan Replay Fidelity & Divergence Report", output)
            self.assertIn("REPLAY EQUIVALENT", output)
            self.assertIn("Total Divergences:             0", output)
            self.assertIn("Replayed execution perfectly matches", output)
        finally:
            Path(trace_path).unlink(missing_ok=True)

    def test_cli_replay_compare_diverged(self) -> None:
        """CLI replay with --compare reports REPLAY DIVERGED with exit code 1."""
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f1:
            exp_path = f1.name
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f2:
            obs_path = f2.name

        try:
            # Generate expected trace
            code = main(["run", "--scenario", "baseline", "--trace-file", exp_path])
            self.assertEqual(code, 0)

            # Load and mutate for observed trace
            with open(exp_path, "r") as f:
                data = json.load(f)
            data[5]["event_type"] = "JOB_FAILED"
            with open(obs_path, "w") as f:
                json.dump(data, f)

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", obs_path, "--compare", exp_path])

            self.assertEqual(exit_code, 1)
            output = stdout_capture.getvalue()
            self.assertIn("Titan Replay Fidelity & Divergence Report", output)
            self.assertIn("REPLAY DIVERGED", output)
            self.assertIn("First Divergence:", output)
            self.assertIn("Category:", output)
            self.assertIn("EVENT", output)
        finally:
            Path(exp_path).unlink(missing_ok=True)
            Path(obs_path).unlink(missing_ok=True)

    def test_cli_replay_compare_json(self) -> None:
        """CLI replay with --compare and --json outputs structured fidelity JSON."""
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f_exp:
            trace_path = f_exp.name

        try:
            # Generate trace
            code = main(["run", "--scenario", "baseline", "--trace-file", trace_path])
            self.assertEqual(code, 0)

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", trace_path, "--compare", trace_path, "--json"])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout_capture.getvalue())
            self.assertTrue(data["equivalent"])
            self.assertEqual(data["divergence_count"], 0)
            self.assertIsNone(data["first_divergence"])
        finally:
            Path(trace_path).unlink(missing_ok=True)

    def test_cli_replay_expected_file_not_found(self) -> None:
        """CLI replay with non-existent expected file exits with code 1."""
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            trace_path = f.name
        try:
            code = main(["run", "--scenario", "baseline", "--trace-file", trace_path])
            self.assertEqual(code, 0)

            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                exit_code = main(["replay", trace_path, "--compare", "non_existent_file.json"])
            self.assertEqual(exit_code, 1)
            self.assertIn("Expected trace file not found", stderr_capture.getvalue())
        finally:
            Path(trace_path).unlink(missing_ok=True)

    def test_standard_replay_preserves_malformed_rejection(self) -> None:
        """Standard replay without --compare continues to reject malformed traces."""
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            trace_path = f.name

        try:
            code = main(["run", "--scenario", "baseline", "--trace-file", trace_path])
            self.assertEqual(code, 0)

            # Corrupt sequence continuity
            with open(trace_path, "r") as fh:
                data = json.load(fh)
            data[5]["seq"] = 9999
            with open(trace_path, "w") as fh:
                json.dump(data, fh)

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", trace_path])

            self.assertEqual(exit_code, 1)
            output = stdout_capture.getvalue()
            self.assertIn("INVALID (Violations Detected)", output)
            self.assertIn("Event sequence discontinuity", output)
        finally:
            Path(trace_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
