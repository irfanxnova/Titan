"""Tests for Titan's deterministic trace replay engine and validation layer."""

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
    ReplayAttemptStatus,
    ReplayEngine,
    ReplayJobStatus,
    ReplayResult,
    ReplayRunStatus,
    ReplayWorkerStatus,
)
from titan.scenario import FaultConfig, Scenario, run_scenario
from titan.trace import EventType, ExecutionTrace, TraceEvent


class TestReplayResultAndSerialization(unittest.TestCase):
    """Verify ReplayResult serialization, deserialization, and schema integrity."""

    def test_replay_result_dict_and_json_roundtrip(self) -> None:
        """Verify serialization to dictionary and formatted JSON, and deserialization from dictionary."""
        result = ReplayResult(
            valid=True,
            total_events=15,
            final_run_state="COMPLETED",
            reconstructed_job_states={"j-1": "COMPLETED", "j-2": "COMPLETED"},
            reconstructed_worker_states={"w-0": "IDLE", "w-1": "IDLE"},
            attempts=2,
            retries=0,
            worker_failures=0,
            worker_replacements=0,
            validation_errors=[],
            summary_metrics={"total_jobs": 2, "completed_jobs": 2},
        )
        d = result.to_dict()
        self.assertTrue(d["valid"])
        self.assertEqual(d["total_events"], 15)
        self.assertEqual(d["final_run_state"], "COMPLETED")
        self.assertEqual(d["reconstructed_job_states"]["j-1"], "COMPLETED")

        # JSON round-trip
        json_str = result.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["total_events"], 15)

        reconstructed = ReplayResult.from_dict(d)
        self.assertEqual(reconstructed.valid, result.valid)
        self.assertEqual(reconstructed.total_events, result.total_events)
        self.assertEqual(reconstructed.reconstructed_job_states, result.reconstructed_job_states)
        self.assertEqual(reconstructed.summary_metrics, result.summary_metrics)


class TestDeterministicReplayEngine(unittest.TestCase):
    """Verify trace replay and state reconstruction from real and synthetic execution traces."""

    def test_valid_baseline_scenario_trace_replay(self) -> None:
        """Replay a real execution trace captured from the baseline scenario."""
        scenario = Scenario(
            name="replay-baseline",
            num_workers=2,
            num_jobs=6,
            work_units=100,
            pattern="uniform",
        )
        scenario_result = run_scenario(scenario)
        trace = scenario_result.trace
        self.assertIsNotNone(trace)

        # Replay the generated trace
        replay_result = ReplayEngine.replay(trace)
        self.assertTrue(replay_result.valid, f"Validation errors: {replay_result.validation_errors}")
        self.assertEqual(replay_result.final_run_state, "COMPLETED")
        self.assertEqual(len(replay_result.reconstructed_job_states), 6)
        self.assertTrue(all(s == "COMPLETED" for s in replay_result.reconstructed_job_states.values()))
        self.assertEqual(replay_result.worker_failures, 0)
        self.assertEqual(replay_result.retries, 0)
        self.assertEqual(replay_result.validation_errors, [])

    def test_valid_worker_crash_scenario_trace_replay(self) -> None:
        """Replay a real execution trace captured from the worker-crash failure injection scenario."""
        scenario = Scenario(
            name="replay-worker-crash",
            num_workers=2,
            num_jobs=8,
            work_units=200,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        scenario_result = run_scenario(scenario)
        trace = scenario_result.trace
        self.assertIsNotNone(trace)

        replay_result = ReplayEngine.replay(trace)
        self.assertTrue(replay_result.valid, f"Validation errors: {replay_result.validation_errors}")
        self.assertEqual(replay_result.final_run_state, "COMPLETED")
        self.assertEqual(replay_result.worker_failures, 1)
        self.assertEqual(replay_result.retries, 1)
        self.assertEqual(replay_result.worker_replacements, 1)
        self.assertEqual(len(replay_result.reconstructed_job_states), 8)
        self.assertTrue(all(s == "COMPLETED" for s in replay_result.reconstructed_job_states.values()))
        self.assertEqual(replay_result.validation_errors, [])

    def test_full_failure_retry_reassignment_reconstruction(self) -> None:
        """Verify exact step-by-step reconstruction of a crashed job through retry, replacement, and completion."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED, data={"total_jobs": 1})
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_CREATED, job_id="job-recovery-test", data={"work_units": 100, "max_retries": 3})
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-recovery-test", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_STARTED, job_id="job-recovery-test", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.WORKER_FAILED, worker_id="w-0", data={"exit_code": 42})
        trace.emit(EventType.JOB_LOST, job_id="job-recovery-test", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.RETRY_SCHEDULED, job_id="job-recovery-test", attempt_id=2)
        trace.emit(EventType.WORKER_REPLACED, worker_id="w-0-r1", data={"replaced_worker_id": "w-0"})
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0-r1", data={"is_replacement": True, "replaced_worker_id": "w-0"})
        trace.emit(EventType.JOB_REASSIGNED, job_id="job-recovery-test", attempt_id=2, worker_id="w-0-r1")
        trace.emit(EventType.JOB_STARTED, job_id="job-recovery-test", attempt_id=2, worker_id="w-0-r1")
        trace.emit(EventType.JOB_COMPLETED, job_id="job-recovery-test", attempt_id=2, worker_id="w-0-r1", data={"result": 1234})
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertTrue(result.valid, f"Validation errors: {result.validation_errors}")
        self.assertEqual(result.reconstructed_job_states["job-recovery-test"], "COMPLETED")
        self.assertEqual(result.worker_failures, 1)
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.worker_replacements, 1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.reconstructed_worker_states["w-0"], "FAILED")
        self.assertEqual(result.reconstructed_worker_states["w-0-r1"], "IDLE")

    def test_worker_replacement_reconstruction(self) -> None:
        """Verify worker replacement tracking links replacement worker to the failed predecessor."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.WORKER_FAILED, worker_id="w-0", data={"exit_code": 1})
        trace.emit(EventType.WORKER_REPLACED, worker_id="w-0-r1", data={"replaced_worker_id": "w-0"})
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0-r1", data={"is_replacement": True, "replaced_worker_id": "w-0"})
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertTrue(result.valid, f"Validation errors: {result.validation_errors}")
        self.assertEqual(result.worker_failures, 1)
        self.assertEqual(result.worker_replacements, 1)

    def test_deterministic_replay_of_same_trace(self) -> None:
        """Verify that repeated replays of identical traces yield strictly identical ReplayResult records."""
        scenario = Scenario(
            name="det-replay-test",
            num_workers=2,
            num_jobs=5,
            work_units=100,
        )
        res = run_scenario(scenario)
        trace = res.trace

        replay1 = ReplayEngine.replay(trace)
        replay2 = ReplayEngine.replay(trace)

        self.assertEqual(replay1.valid, replay2.valid)
        self.assertEqual(replay1.total_events, replay2.total_events)
        self.assertEqual(replay1.reconstructed_job_states, replay2.reconstructed_job_states)
        self.assertEqual(replay1.reconstructed_worker_states, replay2.reconstructed_worker_states)
        self.assertEqual(replay1.summary_metrics, replay2.summary_metrics)


class TestReplayValidationAndAnomalyDetection(unittest.TestCase):
    """Verify that illegal transitions, corrupted sequences, and domain violations are detected."""

    def test_invalid_event_ordering_detected(self) -> None:
        """Verify that non-monotonic sequence numbers are flagged as invalid."""
        events = [
            TraceEvent(seq=1, event_type=EventType.RUN_STARTED, timestamp=1.0),
            TraceEvent(seq=3, event_type=EventType.WORKER_STARTED, timestamp=2.0, worker_id="w-0"),  # seq jumped from 1 to 3
            TraceEvent(seq=4, event_type=EventType.RUN_COMPLETED, timestamp=3.0),
        ]
        result = ReplayEngine.replay(events)
        self.assertFalse(result.valid)
        self.assertTrue(any("discontinuity" in err for err in result.validation_errors))

    def test_unknown_job_detected(self) -> None:
        """Verify that assigning or completing an uncreated job produces validation errors."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_ASSIGNED, job_id="phantom-job", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("unknown job" in err for err in result.validation_errors))

    def test_unknown_worker_detected(self) -> None:
        """Verify that assigning work to an unregistered worker produces validation errors."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.JOB_CREATED, job_id="job-1")
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-1", attempt_id=1, worker_id="ghost-worker")
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("unknown worker" in err for err in result.validation_errors))

    def test_illegal_lifecycle_transitions_detected(self) -> None:
        """Verify that completing an attempt that was never assigned is rejected."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_CREATED, job_id="job-jump")
        # Attempt completion without assignment
        trace.emit(EventType.JOB_COMPLETED, job_id="job-jump", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("unassigned attempt" in err for err in result.validation_errors))

    def test_retry_without_failure_detected(self) -> None:
        """Verify that scheduling a retry for a job that already completed is rejected."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_CREATED, job_id="job-done")
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-done", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_STARTED, job_id="job-done", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_COMPLETED, job_id="job-done", attempt_id=1, worker_id="w-0")
        # Illegal retry of completed job
        trace.emit(EventType.RETRY_SCHEDULED, job_id="job-done", attempt_id=2)
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("already completed" in err for err in result.validation_errors))

    def test_duplicate_terminal_completion_detected(self) -> None:
        """Verify that emitting multiple completions for the same attempt is rejected."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_CREATED, job_id="job-dup")
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-dup", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_STARTED, job_id="job-dup", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_COMPLETED, job_id="job-dup", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_COMPLETED, job_id="job-dup", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("Duplicate terminal completion" in err for err in result.validation_errors))

    def test_worker_replacement_without_failed_worker_detected(self) -> None:
        """Verify that replacing a non-existent or healthy worker is rejected."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        # Replace worker that never failed
        trace.emit(EventType.WORKER_REPLACED, worker_id="w-0-r1", data={"replaced_worker_id": "w-0"})
        trace.emit(EventType.RUN_COMPLETED)

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("non-failed worker" in err for err in result.validation_errors))

    def test_events_after_run_completed_detected(self) -> None:
        """Verify that job events occurring after RUN_COMPLETED are rejected."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.JOB_CREATED, job_id="job-late")
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-late", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_STARTED, job_id="job-late", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_COMPLETED, job_id="job-late", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.RUN_COMPLETED)
        # Illegal job creation after RUN_COMPLETED
        trace.emit(EventType.JOB_CREATED, job_id="job-post-mortem")

        result = ReplayEngine.replay(trace)
        self.assertFalse(result.valid)
        self.assertTrue(any("after RUN_COMPLETED" in err for err in result.validation_errors))


class TestCLIReplayIntegration(unittest.TestCase):
    """Verify CLI replay subcommand, text reporting, and JSON output."""

    def test_cli_replay_text_valid_trace(self) -> None:
        """Verify CLI replay prints report and exits with code 0 on valid trace file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "baseline_trace.json"
            # Generate trace
            with patch("sys.stdout", io.StringIO()):
                main(["run", "--scenario", "baseline", "--jobs", "4", "--trace-file", str(trace_path)])

            self.assertTrue(trace_path.exists())

            # Replay via CLI
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", str(trace_path)])

            self.assertEqual(exit_code, 0)
            output = stdout_capture.getvalue()
            self.assertIn("Titan Trace Replay & Validation Report", output)
            self.assertIn("Trace Integrity:               VALID", output)
            self.assertIn("Jobs Reconstructed (Total):    4 (4 completed, 0 failed)", output)

    def test_cli_replay_json_valid_trace(self) -> None:
        """Verify CLI replay --json outputs valid JSON payload with valid=True."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "baseline_trace.json"
            with patch("sys.stdout", io.StringIO()):
                main(["run", "--scenario", "baseline", "--jobs", "3", "--trace-file", str(trace_path)])

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", str(trace_path), "--json"])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout_capture.getvalue())
            self.assertTrue(data["valid"])
            self.assertEqual(data["final_run_state"], "COMPLETED")
            self.assertEqual(data["validation_errors"], [])

    def test_cli_replay_corrupted_trace_fails(self) -> None:
        """Verify CLI replay rejects a corrupted trace with exit code 1."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "corrupted_trace.json"
            corrupted_data = [
                {"seq": 1, "event_type": "RUN_STARTED", "timestamp": 1.0},
                {"seq": 2, "event_type": "JOB_ASSIGNED", "timestamp": 2.0, "job_id": "ghost", "attempt_id": 1, "worker_id": "w0"},
                {"seq": 3, "event_type": "RUN_COMPLETED", "timestamp": 3.0},
            ]
            trace_path.write_text(json.dumps(corrupted_data), encoding="utf-8")

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["replay", str(trace_path)])

            self.assertEqual(exit_code, 1)
            output = stdout_capture.getvalue()
            self.assertIn("INVALID (Violations Detected)", output)
            self.assertIn("unknown job", output)

    def test_cli_replay_nonexistent_file_fails(self) -> None:
        """Verify CLI replay returns exit code 1 when trace file does not exist."""
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            exit_code = main(["replay", "does_not_exist_xyz.json"])
        self.assertEqual(exit_code, 1)
        self.assertIn("not found", stderr_capture.getvalue())


if __name__ == "__main__":
    unittest.main()
