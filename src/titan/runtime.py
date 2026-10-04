"""Failure-aware distributed runtime for Titan with explicit execution model.

Coordinates the Producer -> Queue -> Workers -> Collector -> Metrics pipeline
with explicit distinction between logical jobs and execution attempts, unambiguous
worker ownership tracking, attempt lifecycle management, deterministic failure recovery,
and coordinator-authoritative completion deduplication.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time
from dataclasses import dataclass
from typing import Sequence

from titan.job import (
    AttemptKey,
    AttemptStatus,
    CompletionCategory,
    ExecutionAttempt,
    Job,
    JobAcquired,
    JobResult,
    JobStarted,
    JobStatus,
    WorkerRecord,
)
from titan.metrics import RunMetrics
from titan.trace import EventType, ExecutionTrace, TraceEvent
from titan.worker import worker_process_main


@dataclass(frozen=True)
class FailureConfig:
    """Configuration for deterministic worker failure injection."""

    target_worker_id: str
    kill_after_jobs: int
    target_job_id: str | None = None


class StaticRuntime:
    """Titan runtime with explicit execution model, ownership, and recovery semantics."""

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
        self._worker_registry: dict[str, WorkerRecord] = {}
        self._handled_dead_workers: set[str] = set()
        self._replacement_counter = 0
        self._is_running = False

        # Explicit Execution Model State Tracking (Authoritative at Coordinator)
        self._jobs_by_id: dict[str, Job] = {}
        self._job_states: dict[str, JobStatus] = {}
        self._attempts_by_job: dict[str, list[ExecutionAttempt]] = {}
        self._attempt_states: dict[AttemptKey, AttemptStatus] = {}
        self._attempt_ownership: dict[AttemptKey, str] = {}
        self._active_attempt_for_job: dict[str, AttemptKey] = {}

        # In-flight ownership and terminal result accounting
        self._in_flight: dict[str, dict[str, ExecutionAttempt]] = {}
        self._completed_jobs: dict[str, JobResult] = {}
        self._failed_jobs: dict[str, JobResult] = {}

        # Telemetry counters
        self._total_execution_attempts = 0
        self._total_retries = 0
        self._worker_failures = 0
        self._jobs_recovered = 0
        self._jobs_permanently_failed = 0
        self._duplicate_results_ignored = 0
        self._recovery_start_time: float | None = None
        self._recovery_end_time: float | None = None

        # Structured Execution Event Tracing (Observational)
        self._trace = ExecutionTrace()

    @property
    def is_running(self) -> bool:
        """Indicate whether worker processes are currently active."""
        return self._is_running

    @property
    def active_worker_count(self) -> int:
        """Count of currently alive worker processes."""
        return sum(1 for p in self._workers.values() if p.is_alive())

    @property
    def trace(self) -> ExecutionTrace:
        """Observational execution trace for the current/most recent run."""
        return self._trace

    # -------------------------------------------------------------------------
    # Coordinator Query Interface (Authoritative State Access)
    # -------------------------------------------------------------------------

    def get_job(self, job_id: str) -> Job | None:
        """Return the logical job definition by job_id, if known."""
        return self._jobs_by_id.get(job_id)

    def get_job_status(self, job_id: str) -> JobStatus | None:
        """Return the current logical state of a job."""
        return self._job_states.get(job_id)

    def get_all_jobs(self) -> list[Job]:
        """Return all logical jobs submitted to this coordinator."""
        return list(self._jobs_by_id.values())

    def get_attempts(self, job_id: str) -> list[ExecutionAttempt]:
        """Return all execution attempts created for a logical job."""
        return list(self._attempts_by_job.get(job_id, []))

    def get_attempt(self, key: AttemptKey) -> ExecutionAttempt | None:
        """Return a specific execution attempt by key."""
        for att in self._attempts_by_job.get(key.job_id, []):
            if att.attempt_id == key.attempt_id:
                return att
        return None

    def get_attempt_status(self, key: AttemptKey) -> AttemptStatus | None:
        """Return lifecycle state of an execution attempt."""
        return self._attempt_states.get(key)

    def get_attempt_owner(self, key: AttemptKey) -> str | None:
        """Return worker ID currently owning an execution attempt, or None."""
        return self._attempt_ownership.get(key)

    def is_attempt_active(self, key: AttemptKey) -> bool:
        """Indicate whether an attempt is currently active (created, assigned, or running)."""
        status = self._attempt_states.get(key)
        return status in (AttemptStatus.CREATED, AttemptStatus.ASSIGNED, AttemptStatus.RUNNING)

    def is_job_terminal(self, job_id: str) -> bool:
        """Indicate whether a logical job has reached a terminal outcome (COMPLETED or FAILED)."""
        status = self._job_states.get(job_id)
        return status in (JobStatus.COMPLETED, JobStatus.FAILED)

    def is_job_completed(self, job_id: str) -> bool:
        """Indicate whether a logical job is successfully completed."""
        return self._job_states.get(job_id) == JobStatus.COMPLETED

    def is_job_failed(self, job_id: str) -> bool:
        """Indicate whether a logical job is permanently failed."""
        return self._job_states.get(job_id) == JobStatus.FAILED

    def can_retry_job(self, job_id: str) -> bool:
        """Check if a logical job has attempts remaining under its max_retries ceiling."""
        job = self._jobs_by_id.get(job_id)
        if not job or self.is_job_terminal(job_id):
            return False
        attempts = self._attempts_by_job.get(job_id, [])
        return len(attempts) < job.max_retries

    def get_worker_record(self, worker_id: str) -> WorkerRecord | None:
        """Return worker registry metadata by worker_id."""
        return self._worker_registry.get(worker_id)

    def get_all_workers(self) -> list[WorkerRecord]:
        """Return historical and current records of all worker entities."""
        return list(self._worker_registry.values())

    # -------------------------------------------------------------------------
    # Process & Worker Pool Lifecycle
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Spawn and start all configured worker OS processes."""
        if self._is_running:
            return

        self._workers.clear()
        self._worker_registry.clear()
        self._handled_dead_workers.clear()

        for i in range(self.num_workers):
            worker_id = f"worker-{i}"
            fail_target = None
            kill_after = None
            target_job = None
            if self.failure_config and self.failure_config.target_worker_id == worker_id:
                fail_target = self.failure_config.target_worker_id
                kill_after = self.failure_config.kill_after_jobs
                target_job = self.failure_config.target_job_id

            process = self._ctx.Process(
                target=worker_process_main,
                args=(worker_id, self._job_queue, self._event_queue, fail_target, kill_after, target_job),
                name=f"TitanWorker-{worker_id}",
                daemon=True,
            )
            process.start()
            self._workers[worker_id] = process
            self._worker_registry[worker_id] = WorkerRecord(
                worker_id=worker_id,
                is_replacement=False,
                replaced_worker_id=None,
                spawned_at=time.perf_counter(),
            )
            self._trace.emit(
                EventType.WORKER_STARTED,
                worker_id=worker_id,
                data={"is_replacement": False},
            )

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
        for worker_id, process in list(self._workers.items()):
            remaining = max(0.01, deadline - time.perf_counter())
            process.join(timeout=remaining)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)

            if worker_id in self._worker_registry:
                rec = self._worker_registry[worker_id]
                if rec.terminated_at is None:
                    self._worker_registry[worker_id] = WorkerRecord(
                        worker_id=rec.worker_id,
                        is_replacement=rec.is_replacement,
                        replaced_worker_id=rec.replaced_worker_id,
                        spawned_at=rec.spawned_at,
                        terminated_at=time.perf_counter(),
                    )
                self._trace.emit(
                    EventType.WORKER_EXITED,
                    worker_id=worker_id,
                    data={"clean_shutdown": True},
                )

        self._is_running = False

    def kill_worker(self, worker_id: str) -> None:
        """Explicitly terminate a worker process for failure testing."""
        process = self._workers.get(worker_id)
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=2.0)

    def _spawn_replacement_worker(self, dead_worker_id: str) -> None:
        """Spawn a replacement worker with distinct identity to restore pool capacity."""
        self._replacement_counter += 1
        new_worker_id = f"{dead_worker_id}-r{self._replacement_counter}"
        process = self._ctx.Process(
            target=worker_process_main,
            args=(new_worker_id, self._job_queue, self._event_queue, None, None, None),
            name=f"TitanWorker-{new_worker_id}",
            daemon=True,
        )
        process.start()
        self._workers[new_worker_id] = process
        self._worker_registry[new_worker_id] = WorkerRecord(
            worker_id=new_worker_id,
            is_replacement=True,
            replaced_worker_id=dead_worker_id,
            spawned_at=time.perf_counter(),
        )
        self._trace.emit(
            EventType.WORKER_REPLACED,
            worker_id=new_worker_id,
            data={"replaced_worker_id": dead_worker_id},
        )
        self._trace.emit(
            EventType.WORKER_STARTED,
            worker_id=new_worker_id,
            data={"is_replacement": True, "replaced_worker_id": dead_worker_id},
        )

    # -------------------------------------------------------------------------
    # Work Submission & Attempt Registration
    # -------------------------------------------------------------------------

    def submit_job(self, job: Job | ExecutionAttempt) -> None:
        """Enqueue a single job or attempt for processing."""
        if not self._is_running:
            raise RuntimeError("Runtime must be started before submitting jobs.")

        if isinstance(job, ExecutionAttempt):
            if job.job_id not in self._jobs_by_id:
                logical_job = Job(
                    job_id=job.job_id,
                    work_units=job.work_units,
                    created_at=job.created_at,
                    max_retries=job.max_retries,
                )
                self._jobs_by_id[job.job_id] = logical_job
                self._job_states[job.job_id] = JobStatus.PENDING
                self._trace.emit(
                    EventType.JOB_CREATED,
                    job_id=job.job_id,
                    data={"work_units": job.work_units, "max_retries": job.max_retries},
                )
            self._register_and_enqueue_attempt(job)
        else:
            self._jobs_by_id[job.job_id] = job
            self._job_states[job.job_id] = JobStatus.PENDING
            self._trace.emit(
                EventType.JOB_CREATED,
                job_id=job.job_id,
                data={"work_units": job.work_units, "max_retries": job.max_retries},
            )
            attempt = job.create_attempt(attempt_id=1)
            self._register_and_enqueue_attempt(attempt)

    def _register_and_enqueue_attempt(self, attempt: ExecutionAttempt) -> None:
        """Register a new attempt in coordinator tracking tables and put on queue."""
        self._attempts_by_job.setdefault(attempt.job_id, []).append(attempt)
        self._attempt_states[attempt.key] = AttemptStatus.CREATED
        self._active_attempt_for_job[attempt.job_id] = attempt.key
        self._job_queue.put(attempt)

    # -------------------------------------------------------------------------
    # Event Draining & State Transition Handling
    # -------------------------------------------------------------------------

    def _drain_events(self, timeout: float = 0.02) -> None:
        """Drain all pending events from the event queue."""
        try:
            event = self._event_queue.get(timeout=timeout)
            self._dispatch_event(event)
        except queue.Empty:
            pass

        # Drain any further events available in buffer
        while True:
            try:
                event = self._event_queue.get_nowait()
                self._dispatch_event(event)
            except queue.Empty:
                break

    def _dispatch_event(self, event: Any) -> None:
        """Route incoming worker event to appropriate coordinator handler."""
        if isinstance(event, JobAcquired):
            self._handle_job_acquired(event)
        elif isinstance(event, JobStarted):
            self._handle_job_started(event)
        elif isinstance(event, JobResult):
            self._handle_job_result(event)

    def _handle_job_started(self, event: JobStarted) -> None:
        """Handle notification that a worker has begun computation on an attempt."""
        attempt_key = AttemptKey(event.job_id, event.attempt_id)
        if self._attempt_states.get(attempt_key) not in (
            AttemptStatus.COMPLETED,
            AttemptStatus.FAILED,
            AttemptStatus.LOST,
        ):
            self._attempt_states[attempt_key] = AttemptStatus.RUNNING

        self._trace.emit(
            EventType.JOB_STARTED,
            job_id=event.job_id,
            attempt_id=event.attempt_id,
            worker_id=event.worker_id,
            timestamp=event.started_at,
        )

    def _handle_job_acquired(self, event: JobAcquired) -> None:
        """Record in-flight ownership of an execution attempt by a specific worker."""
        self._total_execution_attempts += 1
        orig_job = self._jobs_by_id.get(event.job_id)
        if orig_job is None:
            orig_job = Job(
                job_id=event.job_id,
                work_units=1,
                created_at=event.acquired_at,
                max_retries=self.max_retries,
            )
            self._jobs_by_id[event.job_id] = orig_job
            self._job_states[event.job_id] = JobStatus.PENDING

        attempt_key = AttemptKey(event.job_id, event.attempt_id)
        attempt = self.get_attempt(attempt_key)
        if attempt is None:
            attempt = ExecutionAttempt(
                job_id=orig_job.job_id,
                attempt_id=event.attempt_id,
                work_units=orig_job.work_units,
                created_at=orig_job.created_at,
                max_retries=orig_job.max_retries,
            )
            self._attempts_by_job.setdefault(event.job_id, []).append(attempt)
            self._active_attempt_for_job[event.job_id] = attempt_key

        # If the worker is already known to be dead, immediately recover/requeue
        if event.worker_id in self._handled_dead_workers:
            self._attempt_states[attempt_key] = AttemptStatus.LOST
            self._trace.emit(
                EventType.JOB_LOST,
                job_id=event.job_id,
                attempt_id=attempt.attempt_id,
                worker_id=event.worker_id,
                data={"reason": f"Worker {event.worker_id} already terminated"},
                timestamp=event.acquired_at,
            )
            if event.job_id not in self._completed_jobs:
                if attempt.attempt_id < orig_job.max_retries:
                    self._job_states[event.job_id] = JobStatus.RETRY_PENDING
                    self._total_retries += 1
                    self._jobs_recovered += 1
                    retry_attempt = orig_job.create_attempt(attempt_id=attempt.attempt_id + 1)
                    self._register_and_enqueue_attempt(retry_attempt)
                    self._trace.emit(
                        EventType.RETRY_SCHEDULED,
                        job_id=orig_job.job_id,
                        attempt_id=retry_attempt.attempt_id,
                        data={"previous_attempt": attempt.attempt_id, "reason": "worker_failure"},
                    )
                else:
                    self._job_states[event.job_id] = JobStatus.FAILED
                    fail_res = JobResult(
                        job_id=orig_job.job_id,
                        worker_id=event.worker_id,
                        status=JobStatus.FAILED,
                        attempt_id=attempt.attempt_id,
                        submitted_at=orig_job.created_at,
                        started_at=orig_job.created_at,
                        completed_at=time.perf_counter(),
                        processing_duration=0.0,
                        total_latency=time.perf_counter() - orig_job.created_at,
                        result=None,
                        error=f"Worker {event.worker_id} terminated and max retries ({orig_job.max_retries}) exceeded.",
                    )
                    self._failed_jobs[event.job_id] = fail_res
                    self._jobs_permanently_failed += 1
                    self._trace.emit(
                        EventType.JOB_FAILED,
                        job_id=orig_job.job_id,
                        attempt_id=attempt.attempt_id,
                        worker_id=event.worker_id,
                        data={"error": fail_res.error, "max_retries_exceeded": True},
                        timestamp=fail_res.completed_at,
                    )
            return

        # Normal ownership establishment
        self._attempt_ownership[attempt_key] = event.worker_id
        self._attempt_states[attempt_key] = AttemptStatus.RUNNING
        self._job_states[event.job_id] = JobStatus.RUNNING

        if event.worker_id not in self._in_flight:
            self._in_flight[event.worker_id] = {}
        self._in_flight[event.worker_id][event.job_id] = attempt

        if event.attempt_id == 1:
            self._trace.emit(
                EventType.JOB_ASSIGNED,
                job_id=event.job_id,
                attempt_id=event.attempt_id,
                worker_id=event.worker_id,
                timestamp=event.acquired_at,
            )
        else:
            self._trace.emit(
                EventType.JOB_REASSIGNED,
                job_id=event.job_id,
                attempt_id=event.attempt_id,
                worker_id=event.worker_id,
                timestamp=event.acquired_at,
            )

    def _handle_job_result(self, result: JobResult) -> CompletionCategory:
        """Process an execution result with deduplication and retry enforcement."""
        attempt_key = AttemptKey(result.job_id, result.attempt_id)

        # Release in-flight ownership
        if result.worker_id in self._in_flight:
            self._in_flight[result.worker_id].pop(result.job_id, None)
        if self._attempt_ownership.get(attempt_key) == result.worker_id:
            del self._attempt_ownership[attempt_key]

        # 1. Deduplication: If logical job already reached terminal completion
        if result.job_id in self._completed_jobs:
            self._duplicate_results_ignored += 1
            if self._completed_jobs[result.job_id].attempt_id == result.attempt_id:
                return CompletionCategory.DUPLICATE
            return CompletionCategory.STALE

        # 2. Terminal failure: if job already permanently failed
        if result.job_id in self._failed_jobs:
            self._duplicate_results_ignored += 1
            return CompletionCategory.STALE

        # 3. Check for stale result from an earlier attempt when newer attempt is active
        active_key = self._active_attempt_for_job.get(result.job_id)
        if active_key is not None and result.attempt_id < active_key.attempt_id:
            # Result belongs to a superseded attempt
            self._duplicate_results_ignored += 1
            return CompletionCategory.STALE

        # 4. Valid completion
        if result.status == JobStatus.COMPLETED:
            self._completed_jobs[result.job_id] = result
            self._job_states[result.job_id] = JobStatus.COMPLETED
            self._attempt_states[attempt_key] = AttemptStatus.COMPLETED
            if self._recovery_start_time is not None:
                self._recovery_end_time = time.perf_counter()
            self._trace.emit(
                EventType.JOB_COMPLETED,
                job_id=result.job_id,
                attempt_id=result.attempt_id,
                worker_id=result.worker_id,
                data={
                    "result": result.result,
                    "processing_duration": round(result.processing_duration, 6),
                    "total_latency": round(result.total_latency, 6),
                },
                timestamp=result.completed_at,
            )
            return CompletionCategory.VALID

        elif result.status == JobStatus.FAILED:
            self._attempt_states[attempt_key] = AttemptStatus.FAILED
            orig_job = self._jobs_by_id.get(result.job_id)
            max_retries = orig_job.max_retries if orig_job else self.max_retries

            if result.attempt_id < max_retries:
                self._job_states[result.job_id] = JobStatus.RETRY_PENDING
                self._total_retries += 1
                self._jobs_recovered += 1
                next_attempt = (
                    orig_job.create_attempt(attempt_id=result.attempt_id + 1)
                    if orig_job
                    else ExecutionAttempt(
                        job_id=result.job_id,
                        attempt_id=result.attempt_id + 1,
                        work_units=1,
                        created_at=result.submitted_at,
                        max_retries=max_retries,
                    )
                )
                self._register_and_enqueue_attempt(next_attempt)
                self._trace.emit(
                    EventType.RETRY_SCHEDULED,
                    job_id=result.job_id,
                    attempt_id=next_attempt.attempt_id,
                    data={"previous_attempt": result.attempt_id, "reason": "job_failure"},
                )
                return CompletionCategory.VALID
            else:
                self._failed_jobs[result.job_id] = result
                self._job_states[result.job_id] = JobStatus.FAILED
                self._jobs_permanently_failed += 1
                self._trace.emit(
                    EventType.JOB_FAILED,
                    job_id=result.job_id,
                    attempt_id=result.attempt_id,
                    worker_id=result.worker_id,
                    data={"error": result.error, "max_retries_exceeded": True},
                    timestamp=result.completed_at,
                )
                return CompletionCategory.VALID

        return CompletionCategory.REJECTED

    def _check_worker_health(self) -> None:
        """Detect worker process terminations, recover in-flight work, and manage replacements."""
        for worker_id, process in list(self._workers.items()):
            if not process.is_alive():
                if worker_id in self._handled_dead_workers:
                    continue
                self._handled_dead_workers.add(worker_id)
                self._worker_failures += 1
                exit_code = process.exitcode

                self._trace.emit(
                    EventType.WORKER_FAILED,
                    worker_id=worker_id,
                    data={"exit_code": exit_code},
                )

                # Update worker record termination time
                if worker_id in self._worker_registry:
                    record = self._worker_registry[worker_id]
                    self._worker_registry[worker_id] = WorkerRecord(
                        worker_id=record.worker_id,
                        is_replacement=record.is_replacement,
                        replaced_worker_id=record.replaced_worker_id,
                        spawned_at=record.spawned_at,
                        terminated_at=time.perf_counter(),
                    )

                if self._recovery_start_time is None:
                    self._recovery_start_time = time.perf_counter()

                # Identify all in-flight attempts owned by this dead worker
                in_flight_attempts = list(self._in_flight.get(worker_id, {}).values())
                for attempt in in_flight_attempts:
                    attempt_key = AttemptKey(attempt.job_id, attempt.attempt_id)
                    self._attempt_ownership.pop(attempt_key, None)

                    # Skip if already completed by a parallel or earlier attempt
                    if attempt.job_id in self._completed_jobs:
                        continue

                    # Mark lost
                    self._attempt_states[attempt_key] = AttemptStatus.LOST
                    orig_job = self._jobs_by_id.get(attempt.job_id)
                    max_retries = orig_job.max_retries if orig_job else self.max_retries

                    self._trace.emit(
                        EventType.JOB_LOST,
                        job_id=attempt.job_id,
                        attempt_id=attempt.attempt_id,
                        worker_id=worker_id,
                        data={"reason": f"Worker {worker_id} terminated unexpectedly (exit code {exit_code})"},
                    )

                    if attempt.attempt_id < max_retries:
                        self._job_states[attempt.job_id] = JobStatus.RETRY_PENDING
                        self._total_retries += 1
                        self._jobs_recovered += 1
                        next_attempt = (
                            orig_job.create_attempt(attempt_id=attempt.attempt_id + 1)
                            if orig_job
                            else ExecutionAttempt(
                                job_id=attempt.job_id,
                                attempt_id=attempt.attempt_id + 1,
                                work_units=attempt.work_units,
                                created_at=attempt.created_at,
                                max_retries=max_retries,
                            )
                        )
                        self._register_and_enqueue_attempt(next_attempt)
                        self._trace.emit(
                            EventType.RETRY_SCHEDULED,
                            job_id=attempt.job_id,
                            attempt_id=next_attempt.attempt_id,
                            data={"previous_attempt": attempt.attempt_id, "reason": "worker_failure"},
                        )
                    else:
                        # Retry limit exceeded; mark permanently failed
                        self._job_states[attempt.job_id] = JobStatus.FAILED
                        fail_res = JobResult(
                            job_id=attempt.job_id,
                            worker_id=worker_id,
                            status=JobStatus.FAILED,
                            attempt_id=attempt.attempt_id,
                            submitted_at=attempt.created_at,
                            started_at=attempt.created_at,
                            completed_at=time.perf_counter(),
                            processing_duration=0.0,
                            total_latency=time.perf_counter() - attempt.created_at,
                            result=None,
                            error=f"Worker {worker_id} terminated unexpectedly; max retries ({max_retries}) exceeded.",
                        )
                        self._failed_jobs[attempt.job_id] = fail_res
                        self._jobs_permanently_failed += 1
                        self._trace.emit(
                            EventType.JOB_FAILED,
                            job_id=attempt.job_id,
                            attempt_id=attempt.attempt_id,
                            worker_id=worker_id,
                            data={"error": fail_res.error, "max_retries_exceeded": True},
                            timestamp=fail_res.completed_at,
                        )

                # Clear ownership for the dead worker
                self._in_flight.pop(worker_id, None)

                # Replace worker if configured to maintain pool capacity
                if self.replace_failed_workers and self._is_running:
                    self._spawn_replacement_worker(worker_id)

    # -------------------------------------------------------------------------
    # Workload Runner
    # -------------------------------------------------------------------------

    def run_workload(
        self,
        jobs: Sequence[Job | ExecutionAttempt],
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
        self._job_states.clear()
        self._attempts_by_job.clear()
        self._attempt_states.clear()
        self._attempt_ownership.clear()
        self._active_attempt_for_job.clear()
        self._total_execution_attempts = 0
        self._total_retries = 0
        self._worker_failures = 0
        self._jobs_recovered = 0
        self._jobs_permanently_failed = 0
        self._duplicate_results_ignored = 0
        self._recovery_start_time = None
        self._recovery_end_time = None
        self._trace.clear()

        wall_clock_start = time.perf_counter()

        self._trace.emit(
            EventType.RUN_STARTED,
            data={
                "total_jobs": len(jobs),
                "num_workers": self.num_workers,
                "max_retries": self.max_retries,
            },
        )

        # Record active workers present at start of run
        for wid, rec in self._worker_registry.items():
            if wid in self._workers and self._workers[wid].is_alive():
                self._trace.emit(
                    EventType.WORKER_STARTED,
                    worker_id=wid,
                    data={"is_replacement": rec.is_replacement, "replaced_worker_id": rec.replaced_worker_id},
                )

        # Handle zero-job edge case immediately
        if not jobs:
            wall_clock_end = time.perf_counter()
            self._trace.emit(
                EventType.RUN_COMPLETED,
                data={
                    "wall_clock_duration": max(0.000001, wall_clock_end - wall_clock_start),
                    "total_submitted": 0,
                    "completed": 0,
                    "failed": 0,
                    "retries": 0,
                    "worker_failures": 0,
                },
            )
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

        # Producer: Register and enqueue initial attempts
        for item in jobs:
            if isinstance(item, ExecutionAttempt):
                if item.job_id not in self._jobs_by_id:
                    self._jobs_by_id[item.job_id] = Job(
                        job_id=item.job_id,
                        work_units=item.work_units,
                        created_at=item.created_at,
                        max_retries=item.max_retries,
                    )
                self._job_states[item.job_id] = JobStatus.PENDING
                self._trace.emit(
                    EventType.JOB_CREATED,
                    job_id=item.job_id,
                    data={"work_units": item.work_units, "max_retries": item.max_retries},
                )
                self._register_and_enqueue_attempt(item)
            else:
                self._jobs_by_id[item.job_id] = item
                self._job_states[item.job_id] = JobStatus.PENDING
                self._trace.emit(
                    EventType.JOB_CREATED,
                    job_id=item.job_id,
                    data={"work_units": item.work_units, "max_retries": item.max_retries},
                )
                attempt_1 = item.create_attempt(attempt_id=1)
                self._register_and_enqueue_attempt(attempt_1)

        deadline = (wall_clock_start + timeout) if timeout is not None else None

        # Collector: Drain events and monitor worker process health
        while (len(self._completed_jobs) + len(self._failed_jobs)) < len(self._jobs_by_id):
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

        self._trace.emit(
            EventType.RUN_COMPLETED,
            data={
                "wall_clock_duration": round(wall_clock_duration, 6),
                "total_submitted": len(self._jobs_by_id),
                "completed": len(self._completed_jobs),
                "failed": len(self._failed_jobs),
                "retries": self._total_retries,
                "worker_failures": self._worker_failures,
            },
        )

        # Compute recovery duration
        recovery_time = 0.0
        if self._recovery_start_time is not None:
            end_t = self._recovery_end_time or wall_clock_end
            recovery_time = max(0.0, end_t - self._recovery_start_time)

        metrics = RunMetrics.calculate(
            total_unique_submitted=len(self._jobs_by_id),
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
