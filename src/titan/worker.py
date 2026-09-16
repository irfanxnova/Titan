"""Worker process logic for the Titan runtime with failure injection support."""

from __future__ import annotations

import os
import time
from multiprocessing import Queue
from typing import Any

from titan.job import Job, JobAcquired, JobResult, JobStatus
from titan.workload import execute_workload


def worker_process_main(
    worker_id: str,
    job_queue: Queue[Any],
    event_queue: Queue[Any],
    failure_target: str | None = None,
    kill_after_jobs: int | None = None,
) -> None:
    """Main execution loop for an individual worker OS process.

    Continuously acquires jobs from job_queue, reports acquisition for in-flight
    ownership tracking, executes the workload, and posts results to event_queue.
    Supports deterministic failure injection via immediate OS process exit.
    """
    completed_jobs_count = 0

    while True:
        try:
            job: Job | None = job_queue.get()
        except (EOFError, KeyboardInterrupt):
            break

        # Sentinel token received; initiate clean shutdown
        if job is None:
            break

        acquired_at = time.perf_counter()

        # Step 1: Immediately emit acquisition event for in-flight ownership tracking
        acquisition = JobAcquired(
            job_id=job.job_id,
            worker_id=worker_id,
            attempt=job.attempt,
            acquired_at=acquired_at,
        )
        try:
            event_queue.put(acquisition)
        except (ValueError, OSError):
            break

        # Step 2: Deterministic failure injection check
        # If this worker is the configured target and has reached the kill threshold,
        # terminate the process abruptly mid-job without reporting completion.
        if (
            failure_target is not None
            and failure_target == worker_id
            and kill_after_jobs is not None
            and completed_jobs_count == kill_after_jobs
        ):
            # Give background queue feeder thread a brief slice to transfer to OS pipe
            time.sleep(0.02)
            # Real OS process termination with non-zero exit code (42)
            os._exit(42)

        # Step 3: Execute deterministic workload
        started_at = time.perf_counter()
        try:
            computed_value = execute_workload(job.work_units)
            completed_at = time.perf_counter()
            duration = completed_at - started_at
            latency = completed_at - job.created_at

            result = JobResult(
                job_id=job.job_id,
                worker_id=worker_id,
                status=JobStatus.COMPLETED,
                attempt=job.attempt,
                submitted_at=job.created_at,
                started_at=started_at,
                completed_at=completed_at,
                processing_duration=duration,
                total_latency=latency,
                result=computed_value,
                error=None,
            )
        except Exception as exc:  # pylint: disable=broad-except
            completed_at = time.perf_counter()
            duration = completed_at - started_at
            latency = completed_at - job.created_at

            result = JobResult(
                job_id=job.job_id,
                worker_id=worker_id,
                status=JobStatus.FAILED,
                attempt=job.attempt,
                submitted_at=job.created_at,
                started_at=started_at,
                completed_at=completed_at,
                processing_duration=duration,
                total_latency=latency,
                result=None,
                error=str(exc),
            )

        try:
            event_queue.put(result)
            completed_jobs_count += 1
        except (ValueError, OSError):
            break
