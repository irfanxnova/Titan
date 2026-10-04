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

from titan.job import (
    AttemptKey,
    AttemptStatus,
    CompletionCategory,
    ExecutionAttempt,
    Job,
    JobAcquired,
    JobResult,
    JobStatus,
    WorkerRecord,
)
from titan.metrics import RunMetrics, compute_percentile
from titan.runtime import FailureConfig, StaticRuntime
from titan.workload import execute_workload


class TestJobModel(unittest.TestCase):
    """Verify job data structures, retry factory, execution attempts, and deterministic execution."""

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

    def test_execution_attempt_identity_and_key(self) -> None:
        """Verify ExecutionAttempt separates attempt identity from logical job identity."""
        job = Job.create("test-logical-job", work_units=200, max_retries=3)
        attempt_1 = job.create_attempt(attempt_id=1)
        attempt_2 = attempt_1.create_retry_attempt()

        self.assertEqual(attempt_1.job_id, "test-logical-job")
        self.assertEqual(attempt_2.job_id, "test-logical-job")
        self.assertEqual(attempt_1.attempt_id, 1)
        self.assertEqual(attempt_2.attempt_id, 2)
        self.assertEqual(attempt_1.key, AttemptKey("test-logical-job", 1))
        self.assertEqual(attempt_2.key, AttemptKey("test-logical-job", 2))
        self.assertNotEqual(attempt_1.key, attempt_2.key)
        self.assertEqual(str(attempt_1.key), "test-logical-job:att-1")
        self.assertEqual(attempt_1.key.to_tuple(), ("test-logical-job", 1))

    def test_lifecycle_enums(self) -> None:
        """Verify defined state enums for logical jobs, execution attempts, and completions."""
        self.assertEqual(JobStatus.PENDING, "PENDING")
        self.assertEqual(JobStatus.RUNNING, "RUNNING")
        self.assertEqual(JobStatus.RETRY_PENDING, "RETRY_PENDING")
        self.assertEqual(JobStatus.COMPLETED, "COMPLETED")
        self.assertEqual(JobStatus.FAILED, "FAILED")

        self.assertEqual(AttemptStatus.CREATED, "CREATED")
        self.assertEqual(AttemptStatus.ASSIGNED, "ASSIGNED")
        self.assertEqual(AttemptStatus.RUNNING, "RUNNING")
        self.assertEqual(AttemptStatus.COMPLETED, "COMPLETED")
        self.assertEqual(AttemptStatus.FAILED, "FAILED")
        self.assertEqual(AttemptStatus.LOST, "LOST")
        self.assertEqual(AttemptStatus.RETRY_PENDING, "RETRY_PENDING")

        self.assertEqual(CompletionCategory.VALID, "VALID")
        self.assertEqual(CompletionCategory.DUPLICATE, "DUPLICATE")
        self.assertEqual(CompletionCategory.STALE, "STALE")
        self.assertEqual(CompletionCategory.REJECTED, "REJECTED")

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


class TestExecutionModelSemantics(unittest.TestCase):
    """Specific verification tests required for Prompt 2 execution model."""

    def test_test1_single_successful_execution(self) -> None:
        """Test 1: Single successful execution.
        Job J1, Attempt 1, Worker W1 -> completed.
        Verify: logical job completes; attempt is recorded; ownership is represented correctly;
        terminal state is correct.
        """
        runtime = StaticRuntime(num_workers=1)
        job = Job.create("test-j1", work_units=50, max_retries=3)
        try:
            metrics, results = runtime.run_workload([job], timeout=5.0)

            # 1. Logical job completes
            self.assertEqual(metrics.total_completed_unique, 1)
            self.assertEqual(metrics.total_failed_unique, 0)
            self.assertTrue(runtime.is_job_completed("test-j1"))
            self.assertEqual(runtime.get_job_status("test-j1"), JobStatus.COMPLETED)

            # 2. Attempt is recorded with explicit identity
            attempts = runtime.get_attempts("test-j1")
            self.assertEqual(len(attempts), 1)
            attempt_1 = attempts[0]
            self.assertEqual(attempt_1.attempt_id, 1)
            self.assertEqual(attempt_1.job_id, "test-j1")
            self.assertEqual(attempt_1.key, AttemptKey("test-j1", 1))
            self.assertEqual(runtime.get_attempt_status(attempt_1.key), AttemptStatus.COMPLETED)

            # 3. Ownership is cleared upon completion
            self.assertIsNone(runtime.get_attempt_owner(attempt_1.key))

            # 4. Terminal state is correct
            self.assertTrue(runtime.is_job_terminal("test-j1"))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, JobStatus.COMPLETED)
            self.assertEqual(results[0].attempt_id, 1)
            self.assertEqual(results[0].worker_id, "worker-0")
        finally:
            runtime.stop()

    def test_test2_failure_followed_by_retry(self) -> None:
        """Test 2: Failure followed by retry.
        Job J1: Attempt 1 -> failure, Attempt 2 -> success.
        Verify: Job ID remains the same; Attempt IDs are different; ownership transitions correctly;
        final job state is completed.
        """
        runtime = StaticRuntime(num_workers=1, max_retries=3)
        job = Job.create("retry-job-j1", work_units=50, max_retries=3)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt_1 = job.create_attempt(attempt_id=1)
        runtime._attempts_by_job.setdefault(job.job_id, []).append(attempt_1)
        runtime._attempt_states[attempt_1.key] = AttemptStatus.RUNNING
        runtime._attempt_ownership[attempt_1.key] = "worker-0"
        runtime._active_attempt_for_job[job.job_id] = attempt_1.key

        # Simulate attempt 1 failure
        fail_res = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.FAILED,
            attempt_id=1,
            submitted_at=job.created_at,
            started_at=job.created_at,
            completed_at=time.perf_counter(),
            processing_duration=0.01,
            total_latency=0.02,
            error="Transient worker failure",
        )
        cat1 = runtime._handle_job_result(fail_res)
        self.assertEqual(cat1, CompletionCategory.VALID)

        # Attempt 1 must be marked RETRY_PENDING / FAILED and ownership released
        self.assertIn(runtime.get_attempt_status(attempt_1.key), (AttemptStatus.FAILED, AttemptStatus.RETRY_PENDING))
        self.assertIsNone(runtime.get_attempt_owner(attempt_1.key))
        self.assertEqual(runtime.get_job_status(job.job_id), JobStatus.RETRY_PENDING)

        # Attempt 2 must have been created with distinct attempt identity
        attempts = runtime.get_attempts(job.job_id)
        self.assertEqual(len(attempts), 2)
        attempt_2 = attempts[1]
        self.assertEqual(attempt_2.job_id, job.job_id)
        self.assertEqual(attempt_2.attempt_id, 2)
        self.assertNotEqual(attempt_1.attempt_id, attempt_2.attempt_id)
        self.assertEqual(attempt_2.key, AttemptKey(job.job_id, 2))
        self.assertEqual(runtime.get_attempt_status(attempt_2.key), AttemptStatus.CREATED)

        # Simulate attempt 2 acquisition by worker-1
        acq_2 = JobAcquired(job_id=job.job_id, worker_id="worker-1", attempt_id=2, acquired_at=time.perf_counter())
        runtime._handle_job_acquired(acq_2)
        self.assertEqual(runtime.get_attempt_owner(attempt_2.key), "worker-1")
        self.assertEqual(runtime.get_attempt_status(attempt_2.key), AttemptStatus.RUNNING)

        # Simulate attempt 2 successful completion
        succ_res = JobResult(
            job_id=job.job_id,
            worker_id="worker-1",
            status=JobStatus.COMPLETED,
            attempt_id=2,
            submitted_at=job.created_at,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter() + 0.01,
            processing_duration=0.01,
            total_latency=0.03,
            result=42,
        )
        cat2 = runtime._handle_job_result(succ_res)
        self.assertEqual(cat2, CompletionCategory.VALID)

        # Final state verification: Job completed, Attempt 2 completed
        self.assertTrue(runtime.is_job_completed(job.job_id))
        self.assertEqual(runtime.get_job_status(job.job_id), JobStatus.COMPLETED)
        self.assertIsNone(runtime.get_attempt_owner(attempt_2.key))
        self.assertEqual(runtime.get_attempt_status(attempt_2.key), AttemptStatus.COMPLETED)
        self.assertEqual(runtime._completed_jobs[job.job_id].attempt_id, 2)
        self.assertEqual(runtime._total_retries, 1)

    def test_test3_duplicate_completion(self) -> None:
        """Test 3: Duplicate completion.
        Send the completion for a successful attempt more than once.
        Verify: logical completion happens only once; duplicate completion does not corrupt state.
        """
        runtime = StaticRuntime(num_workers=1)
        job = Job.create("dup-job", work_units=50, max_retries=3)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt = job.create_attempt(1)
        runtime._register_and_enqueue_attempt(attempt)

        acq = JobAcquired(job_id=job.job_id, worker_id="worker-0", attempt_id=1, acquired_at=time.perf_counter())
        runtime._handle_job_acquired(acq)

        succ = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.COMPLETED,
            attempt_id=1,
            submitted_at=job.created_at,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter() + 0.01,
            processing_duration=0.01,
            total_latency=0.02,
            result=999,
        )

        cat1 = runtime._handle_job_result(succ)
        self.assertEqual(cat1, CompletionCategory.VALID)
        self.assertEqual(len(runtime._completed_jobs), 1)
        self.assertEqual(runtime._duplicate_results_ignored, 0)
        self.assertEqual(runtime._completed_jobs[job.job_id].result, 999)

        # Re-send identical completion
        cat2 = runtime._handle_job_result(succ)
        self.assertEqual(cat2, CompletionCategory.DUPLICATE)
        self.assertEqual(len(runtime._completed_jobs), 1)
        self.assertEqual(runtime._duplicate_results_ignored, 1)
        self.assertEqual(runtime._completed_jobs[job.job_id].result, 999)

        # Send a third duplicate
        cat3 = runtime._handle_job_result(succ)
        self.assertEqual(cat3, CompletionCategory.DUPLICATE)
        self.assertEqual(runtime._duplicate_results_ignored, 2)
        self.assertEqual(len(runtime._completed_jobs), 1)

    def test_test4_stale_completion(self) -> None:
        """Test 4: Stale completion.
        Attempt 1 -> lost; Attempt 2 -> completed; Attempt 1 -> late completion.
        Verify: that the late completion cannot overwrite Attempt 2's successful logical result.
        """
        runtime = StaticRuntime(num_workers=2, max_retries=3)
        job = Job.create("stale-job", work_units=50, max_retries=3)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt_1 = job.create_attempt(1)
        runtime._register_and_enqueue_attempt(attempt_1)
        runtime._attempt_ownership[attempt_1.key] = "worker-0"
        runtime._attempt_states[attempt_1.key] = AttemptStatus.RUNNING

        # Attempt 1 lost (e.g. worker-0 dies)
        runtime._attempt_ownership.pop(attempt_1.key, None)
        runtime._attempt_states[attempt_1.key] = AttemptStatus.LOST

        # Attempt 2 created and completed by worker-1
        attempt_2 = job.create_attempt(2)
        runtime._register_and_enqueue_attempt(attempt_2)
        runtime._attempt_ownership[attempt_2.key] = "worker-1"
        runtime._attempt_states[attempt_2.key] = AttemptStatus.RUNNING

        res_2 = JobResult(
            job_id=job.job_id,
            worker_id="worker-1",
            status=JobStatus.COMPLETED,
            attempt_id=2,
            submitted_at=job.created_at,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter() + 0.01,
            processing_duration=0.01,
            total_latency=0.02,
            result=200,
        )
        cat2 = runtime._handle_job_result(res_2)
        self.assertEqual(cat2, CompletionCategory.VALID)
        self.assertEqual(runtime._completed_jobs[job.job_id].attempt_id, 2)
        self.assertEqual(runtime._completed_jobs[job.job_id].result, 200)

        # Late completion arrives from Attempt 1
        res_1_late = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.COMPLETED,
            attempt_id=1,
            submitted_at=job.created_at,
            started_at=time.perf_counter() - 0.05,
            completed_at=time.perf_counter(),
            processing_duration=0.05,
            total_latency=0.06,
            result=100,
        )
        cat1 = runtime._handle_job_result(res_1_late)
        self.assertEqual(cat1, CompletionCategory.STALE)
        self.assertEqual(runtime._duplicate_results_ignored, 1)

        # Attempt 2 result was NOT overwritten
        self.assertEqual(runtime._completed_jobs[job.job_id].attempt_id, 2)
        self.assertEqual(runtime._completed_jobs[job.job_id].result, 200)

    def test_test5_retry_limit(self) -> None:
        """Test 5: Retry limit.
        Verify that the existing retry limit is respected and does not silently create unlimited attempts.
        """
        runtime = StaticRuntime(num_workers=1, max_retries=2, replace_failed_workers=False)
        job = Job.create("limit-job", work_units=50, max_retries=2)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt_1 = job.create_attempt(1)
        runtime._register_and_enqueue_attempt(attempt_1)

        # Fail attempt 1
        fail_1 = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.FAILED,
            attempt_id=1,
            submitted_at=job.created_at,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter() + 0.01,
            processing_duration=0.01,
            total_latency=0.02,
            error="First failure",
        )
        runtime._handle_job_result(fail_1)
        self.assertEqual(len(runtime.get_attempts(job.job_id)), 2)
        self.assertEqual(runtime._total_retries, 1)
        self.assertFalse(runtime.is_job_terminal(job.job_id))

        # Fail attempt 2 (reaches max_retries=2)
        fail_2 = JobResult(
            job_id=job.job_id,
            worker_id="worker-0",
            status=JobStatus.FAILED,
            attempt_id=2,
            submitted_at=job.created_at,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter() + 0.01,
            processing_duration=0.01,
            total_latency=0.03,
            error="Second failure",
        )
        runtime._handle_job_result(fail_2)

        # Must NOT create attempt 3
        self.assertEqual(len(runtime.get_attempts(job.job_id)), 2)
        self.assertTrue(runtime.is_job_terminal(job.job_id))
        self.assertTrue(runtime.is_job_failed(job.job_id))
        self.assertEqual(runtime._jobs_permanently_failed, 1)
        self.assertEqual(runtime.get_job_status(job.job_id), JobStatus.FAILED)
        self.assertFalse(runtime.can_retry_job(job.job_id))

    def test_test6_worker_failure_ownership_transition(self) -> None:
        """Test 6: Worker failure.
        Verify that worker failure causes the appropriate ownership/attempt transition.
        """
        runtime = StaticRuntime(num_workers=2, max_retries=3, replace_failed_workers=False)
        runtime.start()
        job = Job.create("wf-job", work_units=50000, max_retries=3)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt_1 = job.create_attempt(1)
        runtime._register_and_enqueue_attempt(attempt_1)

        # Simulate worker-0 acquiring attempt 1
        acq = JobAcquired(job_id=job.job_id, worker_id="worker-0", attempt_id=1, acquired_at=time.perf_counter())
        runtime._handle_job_acquired(acq)
        self.assertEqual(runtime.get_attempt_owner(attempt_1.key), "worker-0")
        self.assertEqual(runtime.get_attempt_status(attempt_1.key), AttemptStatus.RUNNING)

        # Kill worker-0
        runtime.kill_worker("worker-0")
        time.sleep(0.05)
        runtime._check_worker_health()

        # Worker-0 dead: ownership revoked, attempt 1 is LOST
        self.assertIsNone(runtime.get_attempt_owner(attempt_1.key))
        self.assertEqual(runtime.get_attempt_status(attempt_1.key), AttemptStatus.LOST)

        # Attempt 2 created
        attempts = runtime.get_attempts(job.job_id)
        self.assertEqual(len(attempts), 2)
        attempt_2 = attempts[1]
        self.assertEqual(attempt_2.attempt_id, 2)
        self.assertEqual(runtime.get_attempt_status(attempt_2.key), AttemptStatus.CREATED)

        runtime.stop()

    def test_test7_worker_replacement_identity(self) -> None:
        """Test 7: Worker replacement.
        Verify that replacement worker identity is distinct from the failed worker and that
        capacity recovery remains correct.
        """
        runtime = StaticRuntime(num_workers=2, replace_failed_workers=True)
        runtime.start()
        self.assertEqual(runtime.active_worker_count, 2)

        orig_workers = runtime.get_all_workers()
        self.assertEqual(len(orig_workers), 2)
        self.assertTrue(all(not w.is_replacement for w in orig_workers))

        # Kill worker-0
        runtime.kill_worker("worker-0")
        time.sleep(0.05)
        runtime._check_worker_health()

        # Pool capacity restored to 2
        self.assertEqual(runtime.active_worker_count, 2)
        self.assertIn("worker-0-r1", runtime._workers)

        # Historical registry preserves original worker-0 AND records replacement worker-0-r1
        all_workers = runtime.get_all_workers()
        self.assertEqual(len(all_workers), 3)

        rec_w0 = runtime.get_worker_record("worker-0")
        self.assertIsNotNone(rec_w0)
        self.assertFalse(rec_w0.is_replacement)
        self.assertIsNotNone(rec_w0.terminated_at)

        rec_r1 = runtime.get_worker_record("worker-0-r1")
        self.assertIsNotNone(rec_r1)
        self.assertTrue(rec_r1.is_replacement)
        self.assertEqual(rec_r1.replaced_worker_id, "worker-0")

        runtime.stop()

    def test_test8_existing_failure_injection_behavior(self) -> None:
        """Test 8: Existing failure-injection behavior.
        Run the existing deterministic worker-failure scenario and verify that the new execution model
        does not regress it.
        """
        failure_cfg = FailureConfig(target_worker_id="worker-0", kill_after_jobs=3)
        runtime = StaticRuntime(
            num_workers=3,
            max_retries=3,
            replace_failed_workers=True,
            failure_config=failure_cfg,
        )

        jobs = [Job.create(f"e2e-fail-{i:03d}", work_units=12000) for i in range(20)]
        try:
            metrics, results = runtime.run_workload(jobs, timeout=15.0)
            self.assertGreaterEqual(metrics.worker_failures, 1)
            self.assertGreaterEqual(metrics.total_retries, 1)
            self.assertGreaterEqual(metrics.jobs_recovered, 1)
            self.assertEqual(metrics.total_completed_unique, 20)
            self.assertEqual(metrics.total_failed_unique, 0)
            self.assertEqual(
                metrics.total_completed_unique + metrics.total_failed_unique,
                metrics.total_unique_submitted,
            )
            self.assertGreater(metrics.total_execution_attempts, 20)
        finally:
            runtime.stop()


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
        failure_cfg = FailureConfig(target_worker_id="worker-0", kill_after_jobs=5)
        runtime = StaticRuntime(
            num_workers=3,
            max_retries=3,
            replace_failed_workers=True,
            failure_config=failure_cfg,
        )

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
        runtime = StaticRuntime(
            num_workers=1,
            max_retries=2,
            replace_failed_workers=False,
        )
        runtime.start()

        job = Job.create("exhaustion-job", work_units=100, max_retries=2)
        runtime._jobs_by_id[job.job_id] = job
        runtime._job_states[job.job_id] = JobStatus.PENDING

        attempt = job.create_attempt(1)
        runtime._register_and_enqueue_attempt(attempt)

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
