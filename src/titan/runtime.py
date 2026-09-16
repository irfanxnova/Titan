"""Failure-aware static baseline distributed runtime for Titan.

Coordinates the Producer -> Queue -> Workers -> Collector -> Metrics pipeline
with in-flight work ownership tracking, deterministic failure detection,
at-least-once retry recovery, and deduplication of results.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time
from dataclasses import dataclass
from typing import Sequence

from titan.job import Job, JobAcquired, JobResult, JobStatus
from titan.metrics import RunMetrics
from titan.worker import worker_process_main


@dataclass(frozen=True)
class FailureConfig:
    """Configuration for deterministic worker failure injection."""

    target_worker_id: str
    kill_after_jobs: int


class StaticRuntime:
    """Static baseline runtime with in-flight ownership tracking and failure recovery."""

    def __init__(
        self,
        num_workers: int = 1,
        max_retries: int = 3,
        replace_failed_workers: bool = True,
        failure_config: FailureConfig | None = None,
    ) -> None:
        if num_workers < 1:
            raise ValueError(f"num_workers must be at least 1, got {num_workers}")
        if max_retries < 1:
            raise ValueError(f"max_retries must be at least 1, got {max_retries}")

        self.num_workers = num_workers
        self.max_retries = max_retries
        self.replace_failed_workers = replace_failed_workers
        self.failure_config = failure_config

        self._ctx = mp.get_context("spawn")
        self._job_queue: mp.Queue = self._ctx.Queue()
        self._event_queue: mp.Queue = self._ctx.Queue()

        self._workers: dict[str, mp.Process] = {}
        self._handled_dead_workers: set[str] = set()
        self._replacement_counter = 0
        self._is_running = False

        # In-flight ownership and result accounting
        self._in_flight: dict[str, dict[str, Job]] = {}
        self._completed_jobs: dict[str, JobResult] = {}
        self._failed_jobs: dict[str, JobResult] = {}
        self._jobs_by_id: dict[str, Job] = {}

        # Telemetry counters
        self._total_execution_attempts = 0
        self._total_retries = 0
        self._worker_failures = 0
        self._jobs_recovered = 0
        self._jobs_permanently_failed = 0
        self._duplicate_results_ignored = 0
        self._recovery_start_time: float | None = None
        self._recovery_end_time: float | None = None

    @property
    def is_running(self) -> bool:
        """Indicate whether worker processes are currently active."""
        return self._is_running

    @property
    def active_worker_count(self) -> int:
        """Count of currently alive worker processes."""
        return sum(1 for p in self._workers.values() if p.is_alive())

    def start(self) -> None:
        """Spawn and start all configured worker OS processes."""
        if self._is_running:
            return

        self._workers.clear()
        self._handled_dead_workers.clear()

        for i in range(self.num_workers):
            worker_id = f"worker-{i}"
            fail_target = None
            kill_after = None
            if self.failure_config and self.failure_config.target_worker_id == worker_id:
                fail_target = self.failure_config.target_worker_id
                kill_after = self.failure_config.kill_after_jobs

            process = self._ctx.Process(
                target=worker_process_main,
                args=(worker_id, self._job_queue, self._event_queue, fail_target, kill_after),
                name=f"TitanWorker-{worker_id}",
                daemon=True,
            )
            process.start()
            self._workers[worker_id] = process

        # Brief warm-up to allow OS to spawn and initialize child python runtimes
        time.sleep(0.1)

        self._is_running = True

    def stop(self, timeout: float = 3.0) -> None:
        """Perform a clean shutdown of all worker processes."""
        if not self._is_running:
            return

        # Send sentinel tokens to each worker process
        for _ in list(self._workers.values()):
            try:
                self._job_queue.put(None)
            except (ValueError, OSError):
                break

        deadline = time.perf_counter() + timeout
        for process in self._workers.values():
            remaining = max(0.01, deadline - time.perf_counter())
            process.join(timeout=remaining)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)

        self._is_running = False

    def kill_worker(self, worker_id: str) -> None:
        """Explicitly terminate a worker process for failure testing."""
        process = self._workers.get(worker_id)
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=2.0)

    def submit_job(self, job: Job) -> None:
        """Enqueue a single job for processing."""
        if not self._is_running:
            raise RuntimeError("Runtime must be started before submitting jobs.")
        self._jobs_by_id[job.job_id] = job
        self._job_queue.put(job)

    def _spawn_replacement_worker(self, dead_worker_id: str) -> None:
        """Spawn a replacement worker to restore static worker pool capacity."""
        self._replacement_counter += 1
        new_worker_id = f"{dead_worker_id}-r{self._replacement_counter}"
        process = self._ctx.Process(
            target=worker_process_main,
            args=(new_worker_id, self._job_queue, self._event_queue, None, None),
            name=f"TitanWorker-{new_worker_id}",
            daemon=True,
        )
        process.start()
        self._workers[new_worker_id] = process

    def _drain_events(self, timeout: float = 0.02) -> None:
        """Drain all pending events from the event queue."""
        try:
            event = self._event_queue.get(timeout=timeout)
            if isinstance(event, JobAcquired):
                self._handle_job_acquired(event)
            elif isinstance(event, JobResult):
                self._handle_job_result(event)
        except queue.Empty:
            pass

        # Drain any further events available in buffer
        while True:
            try:
                event = self._event_queue.get_nowait()
                if isinstance(event, JobAcquired):
                    self._handle_job_acquired(event)
                elif isinstance(event, JobResult):
                    self._handle_job_result(event)
            except queue.Empty:
                break

    def _handle_job_acquired(self, event: JobAcquired) -> None:
        """Record in-flight ownership of a job attempt by a specific worker."""
        self._total_execution_attempts += 1
        orig_job = self._jobs_by_id.get(event.job_id)
        if orig_job is None:
            return

        current_job = Job(
            job_id=orig_job.job_id,
            work_units=orig_job.work_units,
            created_at=orig_job.created_at,
            attempt=event.attempt,
            max_retries=self.max_retries,
        )

        # If the worker is already known to be dead, immediately recover/requeue
        if event.worker_id in self._handled_dead_workers:
            if event.job_id not in self._completed_jobs:
                if current_job.attempt < self.max_retries:
                    self._total_retries += 1
                    self._jobs_recovered += 1
                    retry_job = current_job.create_retry_job()
                    self._job_queue.put(retry_job)
                else:
                    self._failed_jobs[event.job_id] = JobResult(
                        job_id=current_job.job_id,
                        worker_id=event.worker_id,
                        status=JobStatus.FAILED,
                        attempt=current_job.attempt,
                        submitted_at=current_job.created_at,
                        started_at=current_job.created_at,
                        completed_at=time.perf_counter(),
                        processing_duration=0.0,
                        total_latency=time.perf_counter() - current_job.created_at,
                        result=None,
                        error=f"Worker {event.worker_id} terminated and max retries ({self.max_retries}) exceeded.",
                    )
                    self._jobs_permanently_failed += 1
            return

        if event.worker_id not in self._in_flight:
            self._in_flight[event.worker_id] = {}
        self._in_flight[event.worker_id][event.job_id] = current_job

    def _handle_job_result(self, result: JobResult) -> None:
        """Process an execution result with deduplication and retry enforcement."""
        # Release in-flight ownership
        if result.worker_id in self._in_flight:
            self._in_flight[result.worker_id].pop(result.job_id, None)

        # Deduplication: If already completed, ignore duplicate / stale completion
        if result.job_id in self._completed_jobs:
            self._duplicate_results_ignored += 1
            return

        if result.status == JobStatus.COMPLETED:
            self._completed_jobs[result.job_id] = result
            if self._recovery_start_time is not None:
                self._recovery_end_time = time.perf_counter()
        elif result.status == JobStatus.FAILED:
            # Worker failed execution; evaluate retry policy
            if result.attempt < self.max_retries:
                self._total_retries += 1
                self._jobs_recovered += 1
                orig_job = self._jobs_by_id[result.job_id]
                retry_job = Job(
                    job_id=orig_job.job_id,
                    work_units=orig_job.work_units,
                    created_at=orig_job.created_at,
                    attempt=result.attempt + 1,
                    max_retries=self.max_retries,
                )
                self._job_queue.put(retry_job)
            else:
                self._failed_jobs[result.job_id] = result
                self._jobs_permanently_failed += 1

    def _check_worker_health(self) -> None:
        """Detect worker process terminations, recover in-flight work, and manage replacements."""
        for worker_id, process in list(self._workers.items()):
            if not process.is_alive():
                if worker_id in self._handled_dead_workers:
                    continue
                self._handled_dead_workers.add(worker_id)
                self._worker_failures += 1

                if self._recovery_start_time is None:
                    self._recovery_start_time = time.perf_counter()

                # Identify all in-flight jobs owned by this dead worker
                in_flight_jobs = list(self._in_flight.get(worker_id, {}).values())
                for job in in_flight_jobs:
                    # Skip if already completed by a parallel or earlier attempt
                    if job.job_id in self._completed_jobs:
                        continue

                    if job.attempt < self.max_retries:
                        self._total_retries += 1
                        self._jobs_recovered += 1
                        retry_job = job.create_retry_job()
                        self._job_queue.put(retry_job)
                    else:
                        # Retry limit exceeded; mark permanently failed
                        fail_res = JobResult(
                            job_id=job.job_id,
                            worker_id=worker_id,
                            status=JobStatus.FAILED,
                            attempt=job.attempt,
                            submitted_at=job.created_at,
                            started_at=job.created_at,
                            completed_at=time.perf_counter(),
                            processing_duration=0.0,
                            total_latency=time.perf_counter() - job.created_at,
                            result=None,
                            error=f"Worker {worker_id} terminated unexpectedly; max retries ({self.max_retries}) exceeded.",
                        )
                        self._failed_jobs[job.job_id] = fail_res
                        self._jobs_permanently_failed += 1

                # Clear ownership for the dead worker
                self._in_flight.pop(worker_id, None)

                # Replace worker if configured to maintain pool capacity
                if self.replace_failed_workers and self._is_running:
                    self._spawn_replacement_worker(worker_id)

    def run_workload(
        self,
        jobs: Sequence[Job],
        timeout: float | None = None,
    ) -> tuple[RunMetrics, list[JobResult]]:
        """Execute a batch of jobs end-to-end with failure detection and recovery."""
        if not self._is_running:
            self.start()

        # Reset per-run accounting state
        self._in_flight.clear()
        self._completed_jobs.clear()
        self._failed_jobs.clear()
        self._jobs_by_id.clear()
        self._total_execution_attempts = 0
        self._total_retries = 0
        self._worker_failures = 0
        self._jobs_recovered = 0
        self._jobs_permanently_failed = 0
        self._duplicate_results_ignored = 0
        self._recovery_start_time = None
        self._recovery_end_time = None

        wall_clock_start = time.perf_counter()

        # Handle zero-job edge case immediately
        if not jobs:
            wall_clock_end = time.perf_counter()
            metrics = RunMetrics.calculate(
                total_unique_submitted=0,
                completed_jobs={},
                failed_jobs={},
                total_execution_attempts=0,
                total_retries=0,
                worker_failures=0,
                jobs_recovered=0,
                jobs_permanently_failed=0,
                recovery_time_sec=0.0,
                duplicate_results_ignored=0,
                wall_clock_duration=max(0.000001, wall_clock_end - wall_clock_start),
            )
            return metrics, []

        # Producer: Enqueue all workload jobs
        for job in jobs:
            self._jobs_by_id[job.job_id] = job
            self._job_queue.put(job)

        deadline = (wall_clock_start + timeout) if timeout is not None else None

        # Collector: Drain events and monitor worker process health
        while (len(self._completed_jobs) + len(self._failed_jobs)) < len(jobs):
            if deadline is not None and time.perf_counter() > deadline:
                break

            # If all workers are dead and cannot be replaced, stop draining
            if self.active_worker_count == 0 and self._event_queue.empty():
                break

            self._drain_events(timeout=0.02)
            self._check_worker_health()

        # Final drain of any buffered events before computing metrics
        self._drain_events(timeout=0.05)
        self._check_worker_health()

        wall_clock_end = time.perf_counter()
        wall_clock_duration = max(0.000001, wall_clock_end - wall_clock_start)

        # Compute recovery duration
        recovery_time = 0.0
        if self._recovery_start_time is not None:
            end_t = self._recovery_end_time or wall_clock_end
            recovery_time = max(0.0, end_t - self._recovery_start_time)

        metrics = RunMetrics.calculate(
            total_unique_submitted=len(jobs),
            completed_jobs=self._completed_jobs,
            failed_jobs=self._failed_jobs,
            total_execution_attempts=self._total_execution_attempts,
            total_retries=self._total_retries,
            worker_failures=self._worker_failures,
            jobs_recovered=self._jobs_recovered,
            jobs_permanently_failed=self._jobs_permanently_failed,
            recovery_time_sec=recovery_time,
            duplicate_results_ignored=self._duplicate_results_ignored,
            wall_clock_duration=wall_clock_duration,
        )

        all_results = list(self._completed_jobs.values()) + list(self._failed_jobs.values())
        return metrics, all_results
