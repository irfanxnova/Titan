"""Worker process logic for the Titan runtime."""

from __future__ import annotations

import time
from multiprocessing import Queue
from typing import Any

from titan.job import Job, JobResult, JobStatus
from titan.workload import execute_workload


def worker_process_main(
    worker_id: str,
    job_queue: Queue[Any],
    result_queue: Queue[Any],
) -> None:
    """Main execution loop for an individual worker OS process.

    Continuously acquires jobs from job_queue, executes the workload, and
    posts results to result_queue until a None sentinel is received.
    """
    while True:
        try:
            job: Job | None = job_queue.get()
        except (EOFError, KeyboardInterrupt):
            break

        # Sentinel token received; initiate clean shutdown
        if job is None:
            break

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
                submitted_at=job.created_at,
                started_at=started_at,
                completed_at=completed_at,
                processing_duration=duration,
                total_latency=latency,
                result=None,
                error=str(exc),
            )

        result_queue.put(result)
