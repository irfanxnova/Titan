"""Focused unit and integration tests for Titan's failure classification and root-cause analysis layer."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path for discovery and direct invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.analysis import (
    AnalysisReport,
    CausalChainNode,
    CausalRole,
    FailureAnalyzer,
    FailureClass,
    FailureRecord,
    FailureSeverity,
    RecoveryOutcome,
)
from titan.cli import main
from titan.job import Job
from titan.runtime import FailureConfig, StaticRuntime
from titan.scenario import FaultConfig, Scenario, get_scenario, run_scenario
from titan.trace import EventType, ExecutionTrace, TraceEvent


class TestFailureAnalysis(unittest.TestCase):
    """Test suite for deterministic failure classification and root-cause analysis."""

    def test_clean_baseline_run_zero_root_failures(self) -> None:
        """1. Clean baseline run produces zero root failures and CLEAN overall status."""
        scenario = Scenario(
            name="clean-test",
            num_workers=2,
            num_jobs=6,
            work_units=100,
            pattern="uniform",
        )
        result = run_scenario(scenario)
        self.assertIsNotNone(result.trace)

        report = FailureAnalyzer.analyze(result.trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "CLEAN")
        self.assertEqual(report.root_failures_count, 0)
        self.assertEqual(len(report.root_failures), 0)
        self.assertEqual(report.consequences_count, 0)
        self.assertEqual(len(report.consequences), 0)
        self.assertEqual(len(report.affected_jobs), 0)
        self.assertEqual(len(report.affected_workers), 0)
        self.assertEqual(report.reconstructed_run_state, "COMPLETED")
        self.assertEqual(report.recovery_summary["UNRECOVERED"], 0)

    def test_worker_crash_root_cause_and_lost_execution_consequence(self) -> None:
        """2 & 3 & 4. Worker crash classifies WORKER_FAILURE root cause, LOST_EXECUTION consequence, and RECOVERED outcome."""
        scenario = Scenario(
            name="crash-test",
            num_workers=2,
            num_jobs=10,
            work_units=200,
            pattern="uniform",
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        result = run_scenario(scenario)
        self.assertIsNotNone(result.trace)

        report = FailureAnalyzer.analyze(result.trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "RECOVERED")
        self.assertEqual(report.root_failures_count, 1)

        # 2. Worker crash is the single root cause
        rf = report.root_failures[0]
        self.assertEqual(rf.failure_class, FailureClass.WORKER_FAILURE)
        self.assertEqual(rf.worker_id, "worker-0")
        self.assertEqual(rf.affected_entity, "worker:worker-0")
        self.assertEqual(rf.recovery_outcome, RecoveryOutcome.RECOVERED)
        self.assertIn("worker-0", rf.immediate_cause)

        # 3. LOST_EXECUTION is recognized as a downstream consequence, NOT an independent root cause
        self.assertGreater(report.consequences_count, 0)
        lost_consequences = [
            c for c in report.consequences if c.failure_class == FailureClass.LOST_EXECUTION
        ]
        self.assertGreater(len(lost_consequences), 0)

        # Root failures must NOT contain LOST_EXECUTION
        for root in report.root_failures:
            self.assertNotEqual(root.failure_class, FailureClass.LOST_EXECUTION)

        # 4. Successful retry -> RECOVERED
        self.assertEqual(rf.recovery_outcome, RecoveryOutcome.RECOVERED)
        self.assertEqual(report.recovery_summary["RECOVERED"], 1)
        self.assertEqual(report.recovery_summary["UNRECOVERED"], 0)

        # Verify causal chain structure
        chain = rf.causal_chain
        self.assertGreater(len(chain), 0)
        self.assertEqual(chain[0].role, CausalRole.ROOT_CAUSE)
        self.assertEqual(chain[0].event_type, "WORKER_FAILED")

        roles_present = [n.role for n in chain]
        self.assertIn(CausalRole.CONSEQUENCE, roles_present)
        self.assertIn(CausalRole.RECOVERY_ACTION, roles_present)
        self.assertIn(CausalRole.TERMINAL_OUTCOME, roles_present)

    def test_retry_exhaustion_unrecovered(self) -> None:
        """5. Retry exhaustion produces RETRY_EXHAUSTION and UNRECOVERED outcome."""
        # Scenario where max_retries is 1, so a lost attempt on worker-0 cannot be retried
        scenario = Scenario(
            name="exhaustion-test",
            num_workers=2,
            num_jobs=8,
            work_units=200,
            max_retries=1,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=1),
        )
        result = run_scenario(scenario)
        self.assertIsNotNone(result.trace)

        report = FailureAnalyzer.analyze(result.trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "UNRECOVERED")
        self.assertGreater(report.recovery_summary["UNRECOVERED"], 0)

        # Verify that RETRY_EXHAUSTION appears in the failure classes summary
        self.assertIn("RETRY_EXHAUSTION", report.failure_classes_summary)
        self.assertGreater(report.failure_classes_summary["RETRY_EXHAUSTION"], 0)

        # Verify that either root failures or consequences contain RETRY_EXHAUSTION with UNRECOVERED
        all_records = report.root_failures + report.consequences
        exhaustion_records = [
            rec for rec in all_records if rec.failure_class == FailureClass.RETRY_EXHAUSTION
        ]
        self.assertGreater(len(exhaustion_records), 0)
        for rec in exhaustion_records:
            self.assertEqual(rec.recovery_outcome, RecoveryOutcome.UNRECOVERED)
            self.assertEqual(rec.final_outcome, "FAILED")

    def test_standalone_job_failure_retry_exhaustion(self) -> None:
        """5b. Standalone job failures without worker crash produce RETRY_EXHAUSTION root failure."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED, timestamp=10.0)
        trace.emit(EventType.WORKER_STARTED, worker_id="worker-0", timestamp=10.1)
        trace.emit(EventType.JOB_CREATED, job_id="job-bad", data={"max_retries": 1}, timestamp=10.2)
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-bad", attempt_id=1, worker_id="worker-0", timestamp=10.3)
        trace.emit(EventType.JOB_STARTED, job_id="job-bad", attempt_id=1, worker_id="worker-0", timestamp=10.4)
        trace.emit(
            EventType.JOB_FAILED,
            job_id="job-bad",
            attempt_id=1,
            worker_id="worker-0",
            data={"error": "DivisionByZero", "max_retries_exceeded": True},
            timestamp=10.5,
        )
        trace.emit(EventType.WORKER_EXITED, worker_id="worker-0", timestamp=10.6)
        trace.emit(EventType.RUN_COMPLETED, timestamp=10.7)

        report = FailureAnalyzer.analyze(trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "UNRECOVERED")
        self.assertEqual(report.root_failures_count, 1)

        rf = report.root_failures[0]
        self.assertEqual(rf.failure_class, FailureClass.RETRY_EXHAUSTION)
        self.assertEqual(rf.recovery_outcome, RecoveryOutcome.UNRECOVERED)
        self.assertEqual(rf.final_outcome, "FAILED")
        self.assertIn("job-bad", rf.affected_entity)

    def test_multiple_independent_failures_remain_distinct(self) -> None:
        """6. Multiple independent failures remain distinct and preserved separately."""
        trace = ExecutionTrace()
        trace.emit(EventType.RUN_STARTED, timestamp=10.0)
        trace.emit(EventType.WORKER_STARTED, worker_id="worker-0", timestamp=10.1)
        trace.emit(EventType.WORKER_STARTED, worker_id="worker-1", timestamp=10.2)
        trace.emit(EventType.JOB_CREATED, job_id="job-0", data={"max_retries": 3}, timestamp=10.3)
        trace.emit(EventType.JOB_CREATED, job_id="job-1", data={"max_retries": 3}, timestamp=10.4)

        # Worker-0 gets job-0 then crashes
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-0", attempt_id=1, worker_id="worker-0", timestamp=10.5)
        trace.emit(EventType.JOB_STARTED, job_id="job-0", attempt_id=1, worker_id="worker-0", timestamp=10.6)
        trace.emit(EventType.WORKER_FAILED, worker_id="worker-0", data={"exit_code": 1}, timestamp=10.7)
        trace.emit(EventType.JOB_LOST, job_id="job-0", attempt_id=1, worker_id="worker-0", timestamp=10.8)
        trace.emit(EventType.WORKER_REPLACED, worker_id="worker-0-rep1", data={"replaced_worker_id": "worker-0"}, timestamp=10.9)
        trace.emit(EventType.WORKER_STARTED, worker_id="worker-0-rep1", data={"is_replacement": True, "replaced_worker_id": "worker-0"}, timestamp=10.95)
        trace.emit(EventType.RETRY_SCHEDULED, job_id="job-0", attempt_id=2, timestamp=11.0)

        # Worker-1 gets job-1 then crashes later
        trace.emit(EventType.JOB_ASSIGNED, job_id="job-1", attempt_id=1, worker_id="worker-1", timestamp=11.1)
        trace.emit(EventType.JOB_STARTED, job_id="job-1", attempt_id=1, worker_id="worker-1", timestamp=11.2)
        trace.emit(EventType.WORKER_FAILED, worker_id="worker-1", data={"exit_code": 2}, timestamp=11.3)
        trace.emit(EventType.JOB_LOST, job_id="job-1", attempt_id=1, worker_id="worker-1", timestamp=11.4)
        trace.emit(EventType.WORKER_REPLACED, worker_id="worker-1-rep1", data={"replaced_worker_id": "worker-1"}, timestamp=11.5)
        trace.emit(EventType.WORKER_STARTED, worker_id="worker-1-rep1", data={"is_replacement": True, "replaced_worker_id": "worker-1"}, timestamp=11.55)
        trace.emit(EventType.RETRY_SCHEDULED, job_id="job-1", attempt_id=2, timestamp=11.6)

        # Replacement workers complete the jobs
        trace.emit(EventType.JOB_REASSIGNED, job_id="job-0", attempt_id=2, worker_id="worker-0-rep1", timestamp=11.7)
        trace.emit(EventType.JOB_STARTED, job_id="job-0", attempt_id=2, worker_id="worker-0-rep1", timestamp=11.8)
        trace.emit(EventType.JOB_COMPLETED, job_id="job-0", attempt_id=2, worker_id="worker-0-rep1", data={"result": 0}, timestamp=11.9)

        trace.emit(EventType.JOB_REASSIGNED, job_id="job-1", attempt_id=2, worker_id="worker-1-rep1", timestamp=12.0)
        trace.emit(EventType.JOB_STARTED, job_id="job-1", attempt_id=2, worker_id="worker-1-rep1", timestamp=12.1)
        trace.emit(EventType.JOB_COMPLETED, job_id="job-1", attempt_id=2, worker_id="worker-1-rep1", data={"result": 1}, timestamp=12.2)

        trace.emit(EventType.WORKER_EXITED, worker_id="worker-0-rep1", timestamp=12.3)
        trace.emit(EventType.WORKER_EXITED, worker_id="worker-1-rep1", timestamp=12.4)
        trace.emit(EventType.RUN_COMPLETED, timestamp=12.5)

        report = FailureAnalyzer.analyze(trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "RECOVERED")
        self.assertEqual(report.root_failures_count, 2)

        # Verify two distinct root failures
        f1, f2 = report.root_failures[0], report.root_failures[1]
        self.assertNotEqual(f1.failure_id, f2.failure_id)
        self.assertEqual(f1.failure_class, FailureClass.WORKER_FAILURE)
        self.assertEqual(f2.failure_class, FailureClass.WORKER_FAILURE)
        self.assertEqual(f1.worker_id, "worker-0")
        self.assertEqual(f2.worker_id, "worker-1")
        self.assertEqual(f1.recovery_outcome, RecoveryOutcome.RECOVERED)
        self.assertEqual(f2.recovery_outcome, RecoveryOutcome.RECOVERED)

        # Verify affected workers
        self.assertIn("worker-0", report.affected_workers)
        self.assertIn("worker-1", report.affected_workers)

    def test_causal_chain_ordering_deterministic(self) -> None:
        """7. Causal chain ordering is strictly monotonically non-decreasing by sequence number."""
        scenario = Scenario(
            name="ordering-test",
            num_workers=2,
            num_jobs=8,
            work_units=150,
            pattern="uniform",
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        result = run_scenario(scenario)
        report = FailureAnalyzer.analyze(result.trace)

        self.assertGreater(report.root_failures_count, 0)
        for rf in report.root_failures:
            chain = rf.causal_chain
            self.assertGreater(len(chain), 0)
            for i in range(len(chain) - 1):
                self.assertLessEqual(
                    chain[i].seq,
                    chain[i + 1].seq,
                    f"Causal chain sequence inversion between {chain[i]} and {chain[i + 1]}",
                )

    def test_replay_divergence_becomes_replay_divergence(self) -> None:
        """8. Replay divergence between traces becomes REPLAY_DIVERGENCE with NOT_APPLICABLE outcome."""
        scenario = Scenario(name="div-base", num_workers=2, num_jobs=4, work_units=50)
        res = run_scenario(scenario)
        exp_trace = res.trace
        self.assertIsNotNone(exp_trace)

        # Create observed trace with a mutated result value (valid replay, but divergent data)
        obs_trace = ExecutionTrace()
        for ev in exp_trace.events:
            if ev.event_type == EventType.JOB_COMPLETED and ev.job_id == "job-000000":
                obs_trace.emit(
                    EventType.JOB_COMPLETED,
                    job_id=ev.job_id,
                    attempt_id=ev.attempt_id,
                    worker_id=ev.worker_id,
                    data={"result": 999999},  # Divergent result
                    timestamp=ev.timestamp,
                )
            else:
                obs_trace.emit(
                    ev.event_type,
                    job_id=ev.job_id,
                    attempt_id=ev.attempt_id,
                    worker_id=ev.worker_id,
                    data=ev.data,
                    timestamp=ev.timestamp,
                )

        report = FailureAnalyzer.analyze(obs_trace, expected_trace=exp_trace)

        self.assertTrue(report.valid)
        self.assertEqual(report.overall_status, "DIVERGENT")
        self.assertGreater(report.divergences_count, 0)

        div_records = [
            rf for rf in report.root_failures if rf.failure_class == FailureClass.REPLAY_DIVERGENCE
        ]
        self.assertGreater(len(div_records), 0)
        for d in div_records:
            self.assertEqual(d.recovery_outcome, RecoveryOutcome.NOT_APPLICABLE)

    def test_malformed_trace_rejected_via_replay_validation(self) -> None:
        """9. Malformed trace is rejected using existing replay validation without unsupported analysis."""
        bad_events = [
            {"seq": 1, "event_type": "JOB_ASSIGNED", "timestamp": 1.0, "job_id": "job-0", "attempt_id": 1, "worker_id": "worker-0"},
            {"seq": 5, "event_type": "JOB_COMPLETED", "timestamp": 2.0, "job_id": "job-0", "attempt_id": 1, "worker_id": "worker-0"},
        ]

        report = FailureAnalyzer.analyze(bad_events)

        self.assertFalse(report.valid)
        self.assertEqual(report.overall_status, "INVALID_TRACE")
        self.assertGreater(len(report.validation_errors), 0)
        self.assertEqual(report.root_failures_count, 0)
        self.assertEqual(len(report.root_failures), 0)

    def test_json_serialization_round_trip(self) -> None:
        """10. JSON serialization and deserialization round-trip cleanly."""
        scenario = Scenario(
            name="json-test",
            num_workers=2,
            num_jobs=6,
            work_units=100,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=1),
        )
        result = run_scenario(scenario)
        report = FailureAnalyzer.analyze(result.trace)

        data = report.to_dict()
        json_str = report.to_json(indent=2)
        loaded = AnalysisReport.from_dict(json.loads(json_str))

        self.assertEqual(loaded.valid, report.valid)
        self.assertEqual(loaded.overall_status, report.overall_status)
        self.assertEqual(loaded.total_events, report.total_events)
        self.assertEqual(loaded.root_failures_count, report.root_failures_count)
        self.assertEqual(loaded.consequences_count, report.consequences_count)
        self.assertEqual(loaded.failure_classes_summary, report.failure_classes_summary)
        self.assertEqual(loaded.affected_jobs, report.affected_jobs)
        self.assertEqual(loaded.affected_workers, report.affected_workers)
        self.assertEqual(loaded.recovery_summary, report.recovery_summary)
        self.assertEqual(len(loaded.root_failures), len(report.root_failures))

        if loaded.root_failures:
            rf_orig = report.root_failures[0]
            rf_load = loaded.root_failures[0]
            self.assertEqual(rf_orig.failure_id, rf_load.failure_id)
            self.assertEqual(rf_orig.failure_class, rf_load.failure_class)
            self.assertEqual(rf_orig.recovery_outcome, rf_load.recovery_outcome)
            self.assertEqual(len(rf_orig.causal_chain), len(rf_load.causal_chain))

    def test_cli_analyze_command_text(self) -> None:
        """11. CLI analyze command displays human-readable report."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "test_trace.json"
            main(["run", "--scenario", "worker-crash", "--jobs", "20", "--work-units", "500", "--trace-file", str(trace_path)])

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["analyze", str(trace_path)])

            self.assertEqual(exit_code, 0)
            output = stdout_capture.getvalue()
            self.assertIn("Titan Deterministic Failure & Root-Cause Analysis Report", output)
            self.assertIn("Trace Integrity:               VALID", output)
            self.assertIn("Overall Run Status:", output)
            self.assertIn("Root Failures Detected:", output)
            self.assertIn("Affected Logical Entities:", output)
            self.assertIn("Recovery Status Summary:", output)
            self.assertIn("Causal Chain:", output)

    def test_cli_analyze_command_json(self) -> None:
        """12. CLI analyze --json outputs structured JSON report."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "test_trace.json"
            main(["run", "--scenario", "worker-crash", "--jobs", "20", "--work-units", "100", "--trace-file", str(trace_path)])

            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["analyze", str(trace_path), "--json"])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout_capture.getvalue())
            self.assertTrue(data["valid"])
            self.assertIn(data["overall_status"], ("RECOVERED", "CLEAN"))
            self.assertIn("root_failures", data)
            self.assertIn("consequences", data)
            self.assertIn("failure_classes_summary", data)

    def test_repeated_analysis_identical_output(self) -> None:
        """13. Repeated analysis of the same trace produces strictly identical output."""
        scenario = Scenario(
            name="det-test",
            num_workers=2,
            num_jobs=10,
            work_units=150,
            fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
        )
        res = run_scenario(scenario)
        trace = res.trace

        report1 = FailureAnalyzer.analyze(trace)
        report2 = FailureAnalyzer.analyze(trace)

        self.assertEqual(report1.to_json(), report2.to_json())
        self.assertEqual(report1.to_dict(), report2.to_dict())

    def test_cli_analyze_non_existent_file(self) -> None:
        """Verify CLI analyze returns 1 when trace file does not exist."""
        exit_code = main(["analyze", "non_existent_trace_file_xyz.json"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
