"""Static baseline distributed runtime for Titan.

Coordinates the Producer -> Queue -> Workers -> Collector -> Metrics pipeline
using separate OS processes and Python standard library multiprocessing.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time
from typing import Sequence

from titan.job import Job, JobResult
from titan.metrics import RunMetrics
from titan.worker import worker_process_main


class StaticRuntime:
    """Static baseline runtime managing worker processes and job queues."""

    def __init__(self, num_workers: int = 1) -> None:
        if num_workers < 1:
            raise ValueError(f"num_workers must be at least 1, got {num_workers}")
        self.num_workers = num_workers
        self._ctx = mp.get_context("spawn")
        self._job_queue: mp.Queue = self._ctx.Queue()
        self._result_queue: mp.Queue = self._ctx.Queue()
        self._workers: list[mp.Process] = []
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Indicate whether worker processes are currently active."""
        return self._is_running

    @property
    def active_worker_count(self) -> int:
        """Count of currently alive worker processes."""
        return sum(1 for w in self._workers if w.is_alive())

    def start(self) -> None:
        """Spawn and start all configured worker OS processes."""
        if self._is_running:
            return

        self._workers = []
        for i in range(self.num_workers):
            worker_id = f"worker-{i}"
            process = self._ctx.Process(
                target=worker_process_main,
                args=(worker_id, self._job_queue, self._result_queue),
                name=f"TitanWorker-{worker_id}",
                daemon=True,
            )
            process.start()
            self._workers.append(process)

        self._is_running = True

    def stop(self, timeout: float = 3.0) -> None:
        """Perform a clean shutdown of all worker processes."""
        if not self._is_running:
            return

        # Send a None sentinel token to each worker to signal clean exit
        for _ in self._workers:
            try:
                self._job_queue.put(None)
            except (ValueError, OSError):
                break

        # Wait for workers to exit cleanly
        deadline = time.perf_counter() + timeout
        for process in self._workers:
            remaining = max(0.01, deadline - time.perf_counter())
            process.join(timeout=remaining)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)

        self._is_running = False

    def submit_job(self, job: Job) -> None:
        """Enqueue a single job for processing."""
        if not self._is_running:
            raise RuntimeError("Runtime must be started before submitting jobs.")
        self._job_queue.put(job)

    def run_workload(
        self,
        jobs: Sequence[Job],
        timeout: float | None = None,
    ) -> tuple[RunMetrics, list[JobResult]]:
        """Execute a batch of jobs end-to-end and compute performance metrics.

        Args:
            jobs: Sequence of Job instances to execute.
            timeout: Optional overall timeout in seconds.

        Returns:
            Tuple of (RunMetrics, list[JobResult]).
        """
        if not self._is_running:
            self.start()

        wall_clock_start = time.perf_counter()

        # Producer: Enqueue all workload jobs
        for job in jobs:
            self._job_queue.put(job)

        # Collector: Drain results from the result queue
        results: list[JobResult] = []
        deadline = (wall_clock_start + timeout) if timeout is not None else None

        while len(results) < len(jobs):
            if deadline is not None and time.perf_counter() > deadline:
                break

            # If all workers are dead and no more results are available, abort drain
            if self.active_worker_count == 0 and self._result_queue.empty():
                break

            try:
                result = self._result_queue.get(timeout=0.05)
                results.append(result)
            except queue.Empty:
                continue

        wall_clock_end = time.perf_counter()
        wall_clock_duration = max(0.000001, wall_clock_end - wall_clock_start)

        metrics = RunMetrics.calculate(
            total_submitted=len(jobs),
            results=results,
            wall_clock_duration=wall_clock_duration,
        )

        return metrics, results
