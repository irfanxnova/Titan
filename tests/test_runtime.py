"""Automated test suite for the Titan failure-aware distributed runtime."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

# Ensure src/ is on sys.path for direct test invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.job import Job, JobAcquired, JobResult, JobStatus
from titan.metrics import RunMetrics, compute_percentile
from titan.runtime import FailureConfig, StaticRuntime
from titan.workload import execute_workload


class TestJobModel(unittest.TestCase):
    """Verify job data structures, retry factory, and deterministic execution."""

    def test_job_creation_and_uniqueness(self) -> None:
        """Verify job instances are immutable, generate unique IDs, and initialize attempts."""
        jobs = [Job.create(f"job-{i}", work_units=50, max_retries=4) for i in range(100)]
        ids = [j.job_id for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(jobs), 100)
        self.assertTrue(all(j.created_at > 0 for j in jobs))
        self.assertTrue(all(j.attempt == 1 for j in jobs))
        self.assertTrue(all(j.max_retries == 4 for j in jobs))

    def test_retry_job_factory(self) -> None:
        """Verify create_retry_job preserves job_id and created_at while incrementing attempt."""
        job = Job.create("retry-test-job", work_units=100, max_retries=3)
        retry_job = job.create_retry_job()
        self.assertEqual(retry_job.job_id, job.job_id)
        self.assertEqual(retry_job.work_units, job.work_units)
        self.assertEqual(retry_job.created_at, job.created_at)
        self.assertEqual(retry_job.attempt, 2)
        self.assertEqual(retry_job.max_retries, 3)

    def test_workload_determinism(self) -> None:
        """Verify that identical workload units produce identical output."""
        val1 = execute_workload(250)
        val2 = execute_workload(250)
        val3 = execute_workload(500)
        self.assertEqual(val1, val2)
        self.assertNotEqual(val1, val3)


class TestMetricsCalculation(unittest.TestCase):
    """Verify statistical and aggregation calculations on synthetic fixtures."""

    def test_compute_percentile_empty_and_single(self) -> None:
        """Verify edge cases for percentile calculation."""
        self.assertEqual(compute_percentile([], 50.0), 0.0)
        self.assertEqual(compute_percentile([42.0], 50.0), 42.0)
        self.assertEqual(compute_percentile([42.0], 99.0), 42.0)

    def test_compute_percentile_linear_interpolation(self) -> None:
        """Verify linear interpolation on known distribution [10, 20, 30, 40, 50]."""
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertAlmostEqual(compute_percentile(data, 0.0), 10.0)
        self.assertAlmostEqual(compute_percentile(data, 50.0), 30.0)
        self.assertAlmostEqual(compute_percentile(data, 100.0), 50.0)
        self.assertAlmostEqual(compute_percentile(data, 95.0), 48.0)

    def test_run_metrics_aggregation(self) -> None:
        """Verify RunMetrics aggregation from synthetic JobResult fixtures."""
        results = [
            JobResult(
                job_id="j1",
                worker_id="w0",
                status=JobStatus.COMPLETED,
                attempt=1,
                submitted_at=1.0,
                started_at=1.1,
                completed_at=1.2,
                processing_duration=0.1,
                total_latency=0.2,
                result=123,
            ),
            JobResult(
                job_id="j2",
                worker_id="w1",
                status=JobStatus.COMPLETED,
                attempt=1,
                submitted_at=1.0,
                started_at=1.2,
                completed_at=1.4,
                processing_duration=0.2,
                total_latency=0.4,
                result=456,
            ),
            JobResult(
                job_id="j3",
                worker_id="w0",
                status=JobStatus.FAILED,
                attempt=1,
                submitted_at=1.0,
                started_at=1.4,
                completed_at=1.5,
                processing_duration=0.1,
                total_latency=0.5,
                result=None,
                error="Simulated error",
            ),
        ]

        # 4 submitted, but only 3 results returned (1 lost/unreported)
        metrics = RunMetrics.calculate(
            total_unique_submitted=4,
            results=results,
            wall_clock_duration=2.0,
        )

        self.assertEqual(metrics.total_unique_submitted, 4)
        self.assertEqual(metrics.total_completed_unique, 2)
        # 1 explicit failure + 1 unreported = 2 failed
        self.assertEqual(metrics.total_failed_unique, 2)
        # Accounting invariant: completed + failed == submitted
        self.assertEqual(metrics.total_completed_unique + metrics.total_failed_unique, 4)
        self.assertAlmostEqual(metrics.throughput, 1.0)
        self.assertAlmostEqual(metrics.avg_latency, 0.3)
        self.assertAlmostEqual(metrics.p50_latency, 0.3)
        self.assertAlmostEqual(metrics.avg_processing_time, 0.15)


class TestFailureAwareRuntimeExecution(unittest.TestCase):
    """Verify end-to-end multi-process execution, failure injection, and recovery."""

    def test_zero_jobs_workload(self) -> None:
        """Verify that submitting an empty workload completes immediately without hanging."""
        runtime = StaticRuntime(num_workers=2)
        try:
            metrics, results = runtime.run_workload([])
            self.assertEqual(len(results), 0)
            self.assertEqual(metrics.total_unique_submitted, 0)
            self.assertEqual(metrics.total_completed_unique, 0)
            self.assertEqual(metrics.total_failed_unique, 0)
            self.assertEqual(metrics.throughput, 0.0)
        finally:
            runtime.stop()

    def test_single_worker_end_to_end(self) -> None:
        """Verify that a single worker processes normal jobs to completion."""
        runtime = StaticRuntime(num_workers=1)
        jobs = [Job.create(f"test-job-{i}", work_units=100) for i in range(5)]

        try:
            metrics, results = runtime.run_workload(jobs, timeout=10.0)
            self.assertEqual(len(results), 5)
            self.assertEqual(metrics.total_unique_submitted, 5)
            self.assertEqual(metrics.total_completed_unique, 5)
            self.assertEqual(metrics.total_failed_unique, 0)
            self.assertTrue(metrics.throughput > 0)
            self.assertTrue(all(r.status == JobStatus.COMPLETED for r in results))
            self.assertTrue(all(r.worker_id == "worker-0" for r in results))
            expected_result = execute_workload(100)
            self.assertTrue(all(r.result == expected_result for r in results))
        finally:
            runtime.stop()

    def test_multi_worker_workload_distribution(self) -> None:
        """Verify multiple workers concurrently process a workload."""
        runtime = StaticRuntime(num_workers=2)
        jobs = [Job.create(f"dist-job-{i}", work_units=20000) for i in range(20)]

        try:
            metrics, results = runtime.run_workload(jobs, timeout=15.0)
            self.assertEqual(len(results), 20)
            self.assertEqual(metrics.total_completed_unique, 20)
            worker_ids = {r.worker_id for r in results}
            self.assertEqual(worker_ids, {"worker-0", "worker-1"})
        finally:
            runtime.stop()

    def test_clean_shutdown(self) -> None:
        """Verify that stopping the runtime leaves no orphan worker processes."""
        runtime = StaticRuntime(num_workers=2)
        runtime.start()
        self.assertTrue(runtime.is_running)
        self.assertEqual(runtime.active_worker_count, 2)

        runtime.stop(timeout=2.0)
        self.assertFalse(runtime.is_running)
        time.sleep(0.1)
        self.assertEqual(runtime.active_worker_count, 0)

    def test_deterministic_failure_injection_and_recovery(self) -> None:
        """Verify that injected worker failure is detected, in-flight work is recovered,
        and all unique jobs complete successfully.
        """
        # Configure failure injection: terminate worker-0 after it completes 5 jobs
        failure_cfg = FailureConfig(target_worker_id="worker-0", kill_after_jobs=5)
        runtime = StaticRuntime(
            num_workers=3,
            max_retries=3,
            replace_failed_workers=True,
            failure_config=failure_cfg,
        )

        # 30 jobs with sufficient duration so worker-0 is actively processing job 6 when terminated
        jobs = [Job.create(f"fail-rec-job-{i:03d}", work_units=15000) for i in range(30)]

        try:
            metrics, results = runtime.run_workload(jobs, timeout=20.0)

            # 1. Failure must have been detected
            self.assertGreaterEqual(metrics.worker_failures, 1)

            # 2. Retries and recovered jobs must be recorded
            self.assertGreaterEqual(metrics.total_retries, 1)
            self.assertGreaterEqual(metrics.jobs_recovered, 1)

            # 3. All 30 unique jobs must reach final COMPLETED state
            self.assertEqual(metrics.total_completed_unique, 30)
            self.assertEqual(metrics.total_failed_unique, 0)

            # 4. Strict terminal accounting invariant
            self.assertEqual(
                metrics.total_completed_unique + metrics.total_failed_unique,
                metrics.total_unique_submitted,
            )

            # 5. Total attempts must exceed unique jobs due to retry
            self.assertGreater(metrics.total_execution_attempts, 30)

            # 6. Completed results list must contain unique job IDs
            completed_ids = [r.job_id for r in results if r.status == JobStatus.COMPLETED]
            self.assertEqual(len(completed_ids), 30)
            self.assertEqual(len(set(completed_ids)), 30)
        finally:
            runtime.stop()

    def test_duplicate_and_stale_result_suppression(self) -> None:
        """Verify that duplicate or stale results arriving for an already completed job
        are ignored and do not inflate the unique completed count.
        """
        runtime = StaticRuntime(num_workers=1)
        jobs = [Job.create("dedup-job", work_units=50)]

        try:
            # First execution
            metrics, results = runtime.run_workload(jobs, timeout=5.0)
            self.assertEqual(metrics.total_completed_unique, 1)
            self.assertEqual(metrics.duplicate_results_ignored, 0)

            # Simulate arrival of a duplicate / stale result for the same job
            stale_result = JobResult(
                job_id="dedup-job",
                worker_id="worker-ghost",
                status=JobStatus.COMPLETED,
                attempt=1,
                submitted_at=jobs[0].created_at,
                started_at=jobs[0].created_at + 0.01,
                completed_at=jobs[0].created_at + 0.02,
                processing_duration=0.01,
                total_latency=0.02,
                result=42,
            )
            runtime._handle_job_result(stale_result)

            self.assertEqual(runtime._duplicate_results_ignored, 1)
            self.assertEqual(len(runtime._completed_jobs), 1)
        finally:
            runtime.stop()

    def test_retry_limit_exhaustion_marks_job_failed(self) -> None:
        """Verify that a job that repeatedly fails exceeds max_retries and becomes FAILED."""
        # Max retries set to 2; worker replacement disabled so dead worker work cannot complete
        runtime = StaticRuntime(
            num_workers=1,
            max_retries=2,
            replace_failed_workers=False,
        )
        runtime.start()

        # Submit a job
        job = Job.create("exhaustion-job", work_units=100, max_retries=2)
        runtime._jobs_by_id[job.job_id] = job

        # Simulate attempt 1 failure
        fail_1 = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.FAILED,
            attempt=1,
            submitted_at=job.created_at,
            started_at=job.created_at,
            completed_at=time.perf_counter(),
            processing_duration=0.01,
            total_latency=0.02,
            error="Transient error 1",
        )
        runtime._handle_job_result(fail_1)
        self.assertEqual(runtime._total_retries, 1)
        self.assertEqual(len(runtime._failed_jobs), 0)

        # Simulate attempt 2 failure (exhausts max_retries=2)
        fail_2 = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.FAILED,
            attempt=2,
            submitted_at=job.created_at,
            started_at=job.created_at,
            completed_at=time.perf_counter(),
            processing_duration=0.01,
            total_latency=0.03,
            error="Permanent error 2",
        )
        runtime._handle_job_result(fail_2)

        # Should now be permanently failed
        self.assertEqual(len(runtime._failed_jobs), 1)
        self.assertEqual(runtime._jobs_permanently_failed, 1)
        self.assertEqual(runtime._failed_jobs[job.job_id].status, JobStatus.FAILED)
        runtime.stop()

    def test_worker_replacement_restores_capacity(self) -> None:
        """Verify that when a worker terminates abruptly, a replacement is spawned."""
        runtime = StaticRuntime(num_workers=2, replace_failed_workers=True)
        runtime.start()
        self.assertEqual(runtime.active_worker_count, 2)

        # Terminate worker-0
        runtime.kill_worker("worker-0")
        time.sleep(0.05)
        runtime._check_worker_health()

        # Replacement worker should be active, restoring count to 2
        self.assertEqual(runtime.active_worker_count, 2)
        self.assertIn("worker-0-r1", runtime._workers)
        runtime.stop()


if __name__ == "__main__":
    unittest.main()
