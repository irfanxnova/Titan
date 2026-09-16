"""Job data models, acquisition events, and lifecycle states for Titan."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states of a job in the Titan runtime."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REQUEUED = "REQUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Job:
    """Immutable unit of work submitted to the runtime queue."""

    job_id: str
    work_units: int
    created_at: float
    attempt: int = 1
    max_retries: int = 3

    @classmethod
    def create(cls, job_id: str, work_units: int, max_retries: int = 3) -> Job:
        """Factory method capturing monotonic creation timestamp."""
        return cls(
            job_id=job_id,
            work_units=work_units,
            created_at=time.perf_counter(),
            attempt=1,
            max_retries=max_retries,
        )

    def create_retry_job(self) -> Job:
        """Create a new attempt of this job while preserving original created_at."""
        return Job(
            job_id=self.job_id,
            work_units=self.work_units,
            created_at=self.created_at,
            attempt=self.attempt + 1,
            max_retries=self.max_retries,
        )


@dataclass(frozen=True)
class JobAcquired:
    """Ownership event emitted immediately when a worker dequeues a job."""

    job_id: str
    worker_id: str
    attempt: int
    acquired_at: float


@dataclass(frozen=True)
class JobResult:
    """Immutable execution outcome and telemetry for a single job attempt."""

    job_id: str
    worker_id: str
    status: JobStatus
    attempt: int
    submitted_at: float
    started_at: float
    completed_at: float
    processing_duration: float
    total_latency: float
    result: int | None = None
    error: str | None = None
