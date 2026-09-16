"""Job data models and lifecycle states for Titan."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states of a job in the Titan runtime."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Job:
    """Immutable unit of work submitted to the runtime queue."""

    job_id: str
    work_units: int
    created_at: float

    @classmethod
    def create(cls, job_id: str, work_units: int) -> Job:
        """Factory method capturing monotonic creation timestamp."""
        return cls(
            job_id=job_id,
            work_units=work_units,
            created_at=time.perf_counter(),
        )


@dataclass(frozen=True)
class JobResult:
    """Immutable execution outcome and telemetry for a single job."""

    job_id: str
    worker_id: str
    status: JobStatus
    submitted_at: float
    started_at: float
    completed_at: float
    processing_duration: float
    total_latency: float
    result: int | None = None
    error: str | None = None
