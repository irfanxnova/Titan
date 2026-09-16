"""Automated test suite for the Titan static baseline distributed runtime."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

# Ensure src/ is on sys.path for direct test invocation
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from titan.job import Job, JobResult, JobStatus
from titan.metrics import RunMetrics, compute_percentile
from titan.runtime import StaticRuntime
from titan.workload import execute_workload


class TestJobModel(unittest.TestCase):
    """Verify job data structures and deterministic execution."""

    def test_job_creation_and_uniqueness(self) -> None:
        """Verify job instances are immutable and generate unique IDs."""
        jobs = [Job.create(f"job-{i}", work_units=50) for i in range(100)]
        ids = [j.job_id for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(jobs), 100)
        self.assertTrue(all(j.created_at > 0 for j in jobs))

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
        # p0 = 10, p50 = 30, p100 = 50
        self.assertAlmostEqual(compute_percentile(data, 0.0), 10.0)
        self.assertAlmostEqual(compute_percentile(data, 50.0), 30.0)
        self.assertAlmostEqual(compute_percentile(data, 100.0), 50.0)
        # p95: rank = 0.95 * 4 = 3.8 -> 40 + 0.8 * (50 - 40) = 48.0
        self.assertAlmostEqual(compute_percentile(data, 95.0), 48.0)

    def test_run_metrics_aggregation(self) -> None:
        """Verify RunMetrics aggregation from synthetic JobResult fixtures."""
        results = [
            JobResult(
                job_id="j1",
                worker_id="w0",
                status=JobStatus.COMPLETED,
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
            total_submitted=4,
            results=results,
            wall_clock_duration=2.0,
        )

        self.assertEqual(metrics.total_submitted, 4)
        self.assertEqual(metrics.total_completed, 2)
        # 1 explicit failure + 1 unreported = 2 failed
        self.assertEqual(metrics.total_failed, 2)
        # Throughput = 2 completed / 2.0s = 1.0 jobs/s
        self.assertAlmostEqual(metrics.throughput, 1.0)
        # Completed latencies: [0.2, 0.4] -> avg = 0.3
        self.assertAlmostEqual(metrics.avg_latency, 0.3)
        self.assertAlmostEqual(metrics.p50_latency, 0.3)
        # Completed durations: [0.1, 0.2] -> avg = 0.15
        self.assertAlmostEqual(metrics.avg_processing_time, 0.15)


class TestStaticRuntimeExecution(unittest.TestCase):
    """Verify end-to-end multi-process execution with the static baseline runtime."""

    def test_single_worker_end_to_end(self) -> None:
        """Verify that a single worker can process jobs to completion."""
        runtime = StaticRuntime(num_workers=1)
        jobs = [Job.create(f"test-job-{i}", work_units=100) for i in range(5)]

        try:
            metrics, results = runtime.run_workload(jobs, timeout=10.0)
            self.assertEqual(len(results), 5)
            self.assertEqual(metrics.total_submitted, 5)
            self.assertEqual(metrics.total_completed, 5)
            self.assertEqual(metrics.total_failed, 0)
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
        # Use enough jobs and work_units to ensure concurrent queue acquisition across processes
        jobs = [Job.create(f"dist-job-{i}", work_units=20000) for i in range(20)]

        try:
            metrics, results = runtime.run_workload(jobs, timeout=15.0)
            self.assertEqual(len(results), 20)
            self.assertEqual(metrics.total_completed, 20)
            # Verify that both workers participated in processing
            worker_ids = {r.worker_id for r in results}
            self.assertEqual(worker_ids, {"worker-0", "worker-1"})
        finally:
            runtime.stop()

    def test_clean_shutdown(self) -> None:
        """Verify that starting and stopping the runtime leaves no orphan processes."""
        runtime = StaticRuntime(num_workers=2)
        runtime.start()
        self.assertTrue(runtime.is_running)
        self.assertEqual(runtime.active_worker_count, 2)

        runtime.stop(timeout=2.0)
        self.assertFalse(runtime.is_running)
        # Give OS a moment to reap processes
        time.sleep(0.1)
        self.assertEqual(runtime.active_worker_count, 0)

    def test_worker_termination_tolerance(self) -> None:
        """Verify that coordinator survives when a worker terminates abruptly."""
        runtime = StaticRuntime(num_workers=2)
        runtime.start()

        # Terminate one worker process abruptly
        doomed_worker = runtime._workers[0]
        doomed_worker.terminate()
        doomed_worker.join(timeout=2.0)

        # Worker count should now be 1 alive
        self.assertEqual(runtime.active_worker_count, 1)

        # Submit jobs - the remaining alive worker should still process them
        jobs = [Job.create(f"survivor-job-{i}", work_units=50) for i in range(4)]
        try:
            metrics, results = runtime.run_workload(jobs, timeout=5.0)
            # Remaining worker should have processed the jobs
            self.assertEqual(len(results), 4)
            self.assertEqual(metrics.total_completed, 4)
            self.assertTrue(all(r.worker_id == "worker-1" for r in results))
        finally:
            runtime.stop()


if __name__ == "__main__":
    unittest.main()
