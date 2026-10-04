"""Job data models, execution attempts, ownership events, and lifecycle states for Titan."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states of a logical job in the Titan runtime."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    # Compatibility alias for earlier REQUEUED state
    REQUEUED = "RETRY_PENDING"


class AttemptStatus(str, Enum):
    """Lifecycle states of a concrete execution attempt in the Titan runtime."""

    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    LOST = "LOST"
    RETRY_PENDING = "RETRY_PENDING"


class CompletionCategory(str, Enum):
    """Classification of an incoming attempt completion report."""

    VALID = "VALID"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AttemptKey:
    """Composite unique identifier for a concrete execution attempt: (job_id, attempt_id)."""

    job_id: str
    attempt_id: int

    def __str__(self) -> str:
        return f"{self.job_id}:att-{self.attempt_id}"

    def to_tuple(self) -> tuple[str, int]:
        return (self.job_id, self.attempt_id)

    @classmethod
    def from_tuple(cls, val: tuple[str, int]) -> AttemptKey:
        return cls(job_id=val[0], attempt_id=val[1])


@dataclass(frozen=True)
class ExecutionAttempt:
    """A concrete execution of a logical job.

    Every attempt has an identity distinguishable from the logical job.
    """

    job_id: str
    attempt_id: int
    work_units: int
    created_at: float
    max_retries: int = 3

    @property
    def key(self) -> AttemptKey:
        """Composite identifier for this execution attempt."""
        return AttemptKey(self.job_id, self.attempt_id)

    @property
    def attempt(self) -> int:
        """Sequential attempt index (backward compatibility alias)."""
        return self.attempt_id

    def create_retry_attempt(self) -> ExecutionAttempt:
        """Create the next sequential execution attempt for this logical job."""
        return ExecutionAttempt(
            job_id=self.job_id,
            attempt_id=self.attempt_id + 1,
            work_units=self.work_units,
            created_at=self.created_at,
            max_retries=self.max_retries,
        )


@dataclass(frozen=True)
class Job:
    """Logical unit of work submitted to the Titan runtime.

    A job has a stable identity (job_id) that remains unchanged across retries.
    """

    job_id: str
    work_units: int
    created_at: float
    max_retries: int = 3

    @classmethod
    def create(cls, job_id: str, work_units: int, max_retries: int = 3) -> Job:
        """Factory method capturing monotonic creation timestamp."""
        return cls(
            job_id=job_id,
            work_units=work_units,
            created_at=time.perf_counter(),
            max_retries=max_retries,
        )

    def create_attempt(self, attempt_id: int = 1) -> ExecutionAttempt:
        """Create a concrete execution attempt for this logical job."""
        return ExecutionAttempt(
            job_id=self.job_id,
            attempt_id=attempt_id,
            work_units=self.work_units,
            created_at=self.created_at,
            max_retries=self.max_retries,
        )

    @property
    def attempt(self) -> int:
        """Compatibility property representing the initial attempt index."""
        return 1

    def create_retry_job(self) -> ExecutionAttempt:
        """Compatibility helper returning a new execution attempt (attempt 2)."""
        return self.create_attempt(attempt_id=2)


@dataclass(frozen=True)
class JobAcquired:
    """Ownership event emitted immediately when a worker acquires an execution attempt."""

    job_id: str
    worker_id: str
    attempt_id: int
    acquired_at: float

    def __init__(
        self,
        job_id: str,
        worker_id: str,
        attempt_id: int | None = None,
        acquired_at: float = 0.0,
        attempt: int | None = None,
    ) -> None:
        resolved = attempt_id if attempt_id is not None else (attempt if attempt is not None else 1)
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "attempt_id", resolved)
        object.__setattr__(self, "acquired_at", acquired_at)

    @property
    def attempt(self) -> int:
        """Sequential attempt index (backward compatibility alias)."""
        return self.attempt_id

    @property
    def key(self) -> AttemptKey:
        """Composite identifier for the acquired execution attempt."""
        return AttemptKey(self.job_id, self.attempt_id)


@dataclass(frozen=True)
class JobResult:
    """Immutable execution outcome and telemetry for a single execution attempt."""

    job_id: str
    worker_id: str
    status: JobStatus
    attempt_id: int
    submitted_at: float
    started_at: float
    completed_at: float
    processing_duration: float
    total_latency: float
    result: int | None = None
    error: str | None = None

    def __init__(
        self,
        job_id: str,
        worker_id: str,
        status: JobStatus,
        attempt_id: int | None = None,
        submitted_at: float = 0.0,
        started_at: float = 0.0,
        completed_at: float = 0.0,
        processing_duration: float = 0.0,
        total_latency: float = 0.0,
        result: int | None = None,
        error: str | None = None,
        attempt: int | None = None,
    ) -> None:
        resolved = attempt_id if attempt_id is not None else (attempt if attempt is not None else 1)
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "attempt_id", resolved)
        object.__setattr__(self, "submitted_at", submitted_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "processing_duration", processing_duration)
        object.__setattr__(self, "total_latency", total_latency)
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "error", error)

    @property
    def attempt(self) -> int:
        """Sequential attempt index (backward compatibility alias)."""
        return self.attempt_id

    @property
    def key(self) -> AttemptKey:
        """Composite identifier for this execution attempt."""
        return AttemptKey(self.job_id, self.attempt_id)


@dataclass(frozen=True)
class WorkerRecord:
    """Execution entity tracking for a worker process across its lifecycle."""

    worker_id: str
    is_replacement: bool = False
    replaced_worker_id: str | None = None
    spawned_at: float = 0.0
    terminated_at: float | None = None
