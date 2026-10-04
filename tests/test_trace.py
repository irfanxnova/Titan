"""Tests for Titan's structured event tracing and execution history infrastructure."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from titan.cli import main
from titan.job import AttemptKey, AttemptStatus, ExecutionAttempt, Job, JobAcquired, JobResult, JobStarted, JobStatus
from titan.runtime import FailureConfig, StaticRuntime
from titan.scenario import FaultConfig, Scenario, get_scenario, run_scenario
from titan.trace import EventType, ExecutionTrace, TraceEvent


class TestTraceModelAndSchema(unittest.TestCase):
    """Verify event schemas, canonical types, and serialization behavior."""

    def test_all_canonical_event_types_defined(self) -> None:
        """Verify that all required canonical event types are present in EventType."""
        required_types = {
            "JOB_CREATED",
            "JOB_ASSIGNED",
            "JOB_STARTED",
            "JOB_COMPLETED",
            "JOB_FAILED",
            "WORKER_STARTED",
            "WORKER_EXITED",
            "WORKER_FAILED",
            "JOB_LOST",
            "RETRY_SCHEDULED",
            "JOB_REASSIGNED",
            "WORKER_REPLACED",
            "RUN_STARTED",
            "RUN_COMPLETED",
        }
        actual_types = {e.value for e in EventType}
        for req in required_types:
            self.assertIn(req, actual_types, f"Required event type {req} missing from EventType enum")

    def test_trace_event_immutability_and_fields(self) -> None:
        """Verify TraceEvent attributes and frozen immutability."""
        event = TraceEvent(
            seq=1,
            event_type=EventType.JOB_CREATED,
            timestamp=100.5,
            job_id="job-001",
            attempt_id=1,
            worker_id="worker-0",
            data={"work_units": 500},
        )
        self.assertEqual(event.seq, 1)
        self.assertEqual(event.event_type, EventType.JOB_CREATED)
        self.assertEqual(event.timestamp, 100.5)
        self.assertEqual(event.job_id, "job-001")
        self.assertEqual(event.attempt_id, 1)
        self.assertEqual(event.worker_id, "worker-0")
        self.assertEqual(event.data, {"work_units": 500})

        # Verify frozen immutability
        with self.assertRaises(AttributeError):
            event.seq = 2  # type: ignore

    def test_trace_event_serialization_round_trip(self) -> None:
        """Verify TraceEvent dictionary serialization and deserialization."""
        event = TraceEvent(
            seq=42,
            event_type=EventType.JOB_COMPLETED,
            timestamp=123.456789,
            job_id="job-abc",
            attempt_id=2,
            worker_id="worker-1",
            data={"result": 1000, "duration": 0.05},
        )
        d = event.to_dict()
        self.assertEqual(d["seq"], 42)
        self.assertEqual(d["event_type"], "JOB_COMPLETED")
        self.assertEqual(d["job_id"], "job-abc")
        self.assertEqual(d["attempt_id"], 2)
        self.assertEqual(d["worker_id"], "worker-1")
        self.assertEqual(d["data"]["result"], 1000)

        # Round-trip back to TraceEvent
        reconstructed = TraceEvent.from_dict(d)
        self.assertEqual(reconstructed.seq, event.seq)
        self.assertEqual(reconstructed.event_type, event.event_type)
        self.assertEqual(reconstructed.job_id, event.job_id)
        self.assertEqual(reconstructed.attempt_id, event.attempt_id)
        self.assertEqual(reconstructed.worker_id, event.worker_id)
        self.assertEqual(reconstructed.data, event.data)

    def test_execution_trace_monotonic_sequencing(self) -> None:
        """Verify that ExecutionTrace produces strictly monotonically increasing sequence numbers."""
        trace = ExecutionTrace()
        self.assertEqual(len(trace), 0)

        e1 = trace.emit(EventType.RUN_STARTED, data={"jobs": 2})
        e2 = trace.emit(EventType.WORKER_STARTED, worker_id="worker-0")
        e3 = trace.emit(EventType.JOB_CREATED, job_id="j1")
        e4 = trace.emit(EventType.JOB_ASSIGNED, job_id="j1", attempt_id=1, worker_id="worker-0")

        self.assertEqual(e1.seq, 1)
        self.assertEqual(e2.seq, 2)
        self.assertEqual(e3.seq, 3)
        self.assertEqual(e4.seq, 4)
        self.assertEqual(len(trace), 4)

        # Verify ordering is monotonically increasing
        seqs = [e.seq for e in trace.events]
        self.assertEqual(seqs, [1, 2, 3, 4])

    def test_execution_trace_filtering_and_queries(self) -> None:
        """Verify filtering by job, worker, event type, and composite find_events."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED)
        trace.emit(EventType.WORKER_STARTED, worker_id="w-0")
        trace.emit(EventType.WORKER_STARTED, worker_id="w-1")
        trace.emit(EventType.JOB_CREATED, job_id="j-1")
        trace.emit(EventType.JOB_CREATED, job_id="j-2")
        trace.emit(EventType.JOB_ASSIGNED, job_id="j-1", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_ASSIGNED, job_id="j-2", attempt_id=1, worker_id="w-1")
        trace.emit(EventType.JOB_COMPLETED, job_id="j-1", attempt_id=1, worker_id="w-0")
        trace.emit(EventType.JOB_COMPLETED, job_id="j-2", attempt_id=1, worker_id="w-1")
        trace.emit(EventType.RUN_COMPLETED)

        # Filter by job
        j1_events = trace.filter_by_job("j-1")
        self.assertEqual(len(j1_events), 3)
        self.assertEqual([e.event_type for e in j1_events], [
            EventType.JOB_CREATED,
            EventType.JOB_ASSIGNED,
            EventType.JOB_COMPLETED,
        ])

        # Filter by worker
        w0_events = trace.filter_by_worker("w-0")
        self.assertEqual(len(w0_events), 3)

        # Filter by type
        completions = trace.filter_by_type(EventType.JOB_COMPLETED)
        self.assertEqual(len(completions), 2)

        # Composite find_events
        found = trace.find_events(event_type=EventType.JOB_ASSIGNED, worker_id="w-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].job_id, "j-2")

    def test_execution_trace_json_and_file_io(self) -> None:
        """Verify that traces can be saved to and loaded from JSON files."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED, data={"test": True})
        trace.emit(EventType.JOB_CREATED, job_id="job-99", data={"units": 100})
        trace.emit(EventType.RUN_COMPLETED)

        # Serialized JSON string
        json_str = trace.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["event_type"], "RUN_STARTED")

        # Save to file and reload
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "test_trace.json"
            trace.save_to_file(file_path)
            self.assertTrue(file_path.exists())

            loaded = ExecutionTrace.load_from_file(file_path)
            self.assertEqual(len(loaded), 3)
            self.assertEqual(loaded[0].event_type, EventType.RUN_STARTED)
            self.assertEqual(loaded[1].job_id, "job-99")
            self.assertEqual(loaded[2].event_type, EventType.RUN_COMPLETED)


class TestRuntimeExecutionTracing(unittest.TestCase):
    """Verify runtime integration and trace generation during live execution."""

    def test_baseline_scenario_trace_completeness(self) -> None:
        """Verify that a normal run produces complete, properly sequenced lifecycle events."""
        scenario = Scenario(
            name="trace-baseline-test",
            num_workers=2,
            num_jobs=6,
            work_units=100,
            pattern="uniform",
        )
        result = run_scenario(scenario)
        trace = result.trace
        self.assertIsNotNone(trace)
        self.assertGreater(len(trace), 0)

        # 1. First event must be RUN_STARTED
        first_event = trace[0]
        self.assertEqual(first_event.seq, 1)
        self.assertEqual(first_event.event_type, EventType.RUN_STARTED)
        self.assertEqual(first_event.data.get("total_jobs"), 6)

        # 2. Initial workers must emit WORKER_STARTED
        worker_starts = trace.filter_by_type(EventType.WORKER_STARTED)
        self.assertEqual(len(worker_starts), 2)
        worker_ids = {e.worker_id for e in worker_starts}
        self.assertEqual(worker_ids, {"worker-0", "worker-1"})

        # 3. All jobs must emit JOB_CREATED
        created_events = trace.filter_by_type(EventType.JOB_CREATED)
        self.assertEqual(len(created_events), 6)
        created_job_ids = {e.job_id for e in created_events}
        self.assertEqual(len(created_job_ids), 6)

        # 4. Each job must transition: ASSIGNED -> STARTED -> COMPLETED
        for job_id in created_job_ids:
            job_events = trace.filter_by_job(job_id)
            types = [e.event_type for e in job_events]
            self.assertEqual(types, [
                EventType.JOB_CREATED,
                EventType.JOB_ASSIGNED,
                EventType.JOB_STARTED,
                EventType.JOB_COMPLETED,
            ])
            # Check attempt_id preservation
            self.assertEqual(job_events[1].attempt_id, 1)
            self.assertEqual(job_events[2].attempt_id, 1)
            self.assertEqual(job_events[3].attempt_id, 1)
            # Check worker_id preservation between assigned and completed
            self.assertEqual(job_events[1].worker_id, job_events[3].worker_id)

        # 5. Last event before shutdown must be RUN_COMPLETED
        # (or last non-worker-exited event is RUN_COMPLETED)
        run_completed_events = trace.filter_by_type(EventType.RUN_COMPLETED)
        self.assertEqual(len(run_completed_events), 1)
        self.assertEqual(run_completed_events[0].data["completed"], 6)
        self.assertEqual(run_completed_events[0].data["failed"], 0)

    def test_worker_crash_trace_reconstruction(self) -> None:
        """Verify trace accurately reconstructs WORKER_FAILED -> JOB_LOST -> RETRY_SCHEDULED -> WORKER_REPLACED -> JOB_REASSIGNED."""
        scenario = Scenario(
            name="trace-crash-test",
            num_workers=2,
            num_jobs=8,
            work_units=200,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        result = run_scenario(scenario)
        trace = result.trace
        self.assertIsNotNone(trace)

        # 1. Verify WORKER_FAILED event was emitted
        worker_failed_events = trace.filter_by_type(EventType.WORKER_FAILED)
        self.assertEqual(len(worker_failed_events), 1)
        self.assertEqual(worker_failed_events[0].worker_id, "worker-0")

        # 2. Verify JOB_LOST event was emitted for the in-flight attempt
        lost_events = trace.filter_by_type(EventType.JOB_LOST)
        self.assertEqual(len(lost_events), 1)
        lost_job_id = lost_events[0].job_id
        self.assertEqual(lost_events[0].attempt_id, 1)
        self.assertEqual(lost_events[0].worker_id, "worker-0")

        # 3. Verify RETRY_SCHEDULED event for that job
        retry_events = trace.filter_by_type(EventType.RETRY_SCHEDULED)
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(retry_events[0].job_id, lost_job_id)
        self.assertEqual(retry_events[0].attempt_id, 2)

        # 4. Verify WORKER_REPLACED event
        replaced_events = trace.filter_by_type(EventType.WORKER_REPLACED)
        self.assertEqual(len(replaced_events), 1)
        replacement_worker_id = replaced_events[0].worker_id
        self.assertEqual(replaced_events[0].data.get("replaced_worker_id"), "worker-0")

        # 5. Verify JOB_REASSIGNED event for attempt 2
        reassigned_events = trace.filter_by_type(EventType.JOB_REASSIGNED)
        self.assertEqual(len(reassigned_events), 1)
        self.assertEqual(reassigned_events[0].job_id, lost_job_id)
        self.assertEqual(reassigned_events[0].attempt_id, 2)

        # 6. Verify complete reconstructable lifecycle of the recovered job:
        # CREATED -> ASSIGNED (att 1, worker-0) -> LOST (att 1, worker-0) -> RETRY_SCHEDULED (att 2) -> REASSIGNED (att 2) -> STARTED (att 2) -> COMPLETED (att 2)
        recovered_job_events = trace.filter_by_job(lost_job_id)
        event_sequence = [e.event_type for e in recovered_job_events]
        expected_sequence = [
            EventType.JOB_CREATED,
            EventType.JOB_ASSIGNED,
            EventType.JOB_LOST,
            EventType.RETRY_SCHEDULED,
            EventType.JOB_REASSIGNED,
            EventType.JOB_STARTED,
            EventType.JOB_COMPLETED,
        ]
        self.assertEqual(event_sequence, expected_sequence)

    def test_trace_preserves_identities_and_metadata(self) -> None:
        """Verify that every lifecycle event retains its logical job_id, attempt_id, and worker_id."""
        scenario = Scenario(
            name="trace-identity-test",
            num_workers=1,
            num_jobs=3,
            work_units=100,
        )
        result = run_scenario(scenario)
        trace = result.trace
        self.assertIsNotNone(trace)

        for event in trace:
            if event.event_type in (EventType.JOB_ASSIGNED, EventType.JOB_STARTED, EventType.JOB_COMPLETED):
                self.assertIsNotNone(event.job_id, f"{event.event_type} must have job_id")
                self.assertIsNotNone(event.attempt_id, f"{event.event_type} must have attempt_id")
                self.assertIsNotNone(event.worker_id, f"{event.event_type} must have worker_id")
                self.assertGreater(event.timestamp, 0.0)

    def test_trace_observational_separation(self) -> None:
        """Verify that mutating or clearing the trace does not alter runtime state or metrics."""
        runtime = StaticRuntime(num_workers=1)
        runtime.start()
        try:
            job = Job.create("test-sep-job", work_units=50)
            metrics, results = runtime.run_workload([job])

            # Authoritative state is complete
            self.assertTrue(runtime.is_job_completed(job.job_id))
            self.assertEqual(len(results), 1)

            # Mutate/clear observational trace
            runtime.trace.clear()
            self.assertEqual(len(runtime.trace), 0)

            # Runtime authoritative state remains unchanged
            self.assertTrue(runtime.is_job_completed(job.job_id))
            self.assertEqual(runtime.get_job_status(job.job_id), JobStatus.COMPLETED)
            self.assertEqual(len(runtime.get_all_jobs()), 1)
        finally:
            runtime.stop()

    def test_deterministic_trace_ordering(self) -> None:
        """Verify that identical deterministic scenarios produce identical event sequences."""
        scenario1 = Scenario(
            name="det-trace-1",
            num_workers=1,
            num_jobs=4,
            work_units=50,
            seed=123,
        )
        scenario2 = Scenario(
            name="det-trace-2",
            num_workers=1,
            num_jobs=4,
            work_units=50,
            seed=123,
        )
        res1 = run_scenario(scenario1)
        res2 = run_scenario(scenario2)

        types1 = [e.event_type.value for e in res1.trace if e.event_type != EventType.WORKER_EXITED]
        types2 = [e.event_type.value for e in res2.trace if e.event_type != EventType.WORKER_EXITED]
        self.assertEqual(types1, types2)

        jobs1 = [e.job_id for e in res1.trace if e.job_id is not None]
        jobs2 = [e.job_id for e in res2.trace if e.job_id is not None]
        self.assertEqual(jobs1, jobs2)


class TestCLITraceIntegration(unittest.TestCase):
    """Verify CLI --trace and --trace-file flags and JSON trace export."""

    def test_cli_run_trace_flag(self) -> None:
        """Verify running scenario with --trace displays sequential trace output."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--scenario", "baseline", "--jobs", "3", "--trace"])
        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("Execution Trace", output)
        self.assertIn("RUN_STARTED", output)
        self.assertIn("JOB_CREATED", output)
        self.assertIn("JOB_ASSIGNED", output)
        self.assertIn("JOB_COMPLETED", output)
        self.assertIn("RUN_COMPLETED", output)

    def test_cli_run_json_includes_trace(self) -> None:
        """Verify running scenario with --json outputs structured trace array."""
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            exit_code = main(["run", "--scenario", "baseline", "--jobs", "2", "--json"])
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout_capture.getvalue())
        self.assertIn("trace", data)
        self.assertIsInstance(data["trace"], list)
        self.assertGreater(len(data["trace"]), 0)

        # Validate structure of first event
        first_event = data["trace"][0]
        self.assertEqual(first_event["seq"], 1)
        self.assertEqual(first_event["event_type"], "RUN_STARTED")

    def test_cli_run_trace_file_export(self) -> None:
        """Verify running scenario with --trace-file exports valid JSON trace to disk."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "output_trace.json"
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["run", "--scenario", "baseline", "--jobs", "3", "--trace-file", str(trace_path)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(trace_path.exists())

            # Load exported trace and verify contents
            loaded_trace = ExecutionTrace.load_from_file(trace_path)
            self.assertGreater(len(loaded_trace), 0)
            self.assertEqual(loaded_trace[0].event_type, EventType.RUN_STARTED)
            self.assertIn(EventType.JOB_COMPLETED, [e.event_type for e in loaded_trace])


if __name__ == "__main__":
    unittest.main()
