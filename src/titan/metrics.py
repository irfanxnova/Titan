"""Telemetry and metrics calculation for Titan benchmark runs with failure recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from titan.job import JobResult, JobStatus


def compute_percentile(data: Sequence[float], percentile: float) -> float:
    """Compute a percentile from a sequence of floats using linear interpolation.

    Args:
        data: Sequence of numerical values.
        percentile: Float between 0.0 and 100.0.

    Returns:
        The interpolated percentile value, or 0.0 if data is empty.
    """
    if not data:
        return 0.0
    if len(data) == 1:
        return float(data[0])

    sorted_data = sorted(data)
    rank = (percentile / 100.0) * (len(sorted_data) - 1)
    low_idx = int(rank)
    high_idx = min(low_idx + 1, len(sorted_data) - 1)
    weight = rank - low_idx
    return float(sorted_data[low_idx] * (1.0 - weight) + sorted_data[high_idx] * weight)


@dataclass(frozen=True)
class RunMetrics:
    """Aggregated empirical metrics for a completed runtime workload execution."""

    total_unique_submitted: int
    total_execution_attempts: int
    total_completed_unique: int
    total_failed_unique: int
    total_retries: int
    worker_failures: int
    jobs_recovered: int
    jobs_permanently_failed: int
    recovery_time_sec: float
    avg_attempts_per_completed_job: float
    duplicate_results_ignored: int
    wall_clock_duration: float
    throughput: float
    attempt_throughput: float
    avg_latency: float
    p50_latency: float
    p95_latency: float
    p99_latency: float
    avg_processing_time: float

    # Backward compatibility properties for Milestone 2 API
    @property
    def total_submitted(self) -> int:
        return self.total_unique_submitted

    @property
    def total_completed(self) -> int:
        return self.total_completed_unique

    @property
    def total_failed(self) -> int:
        return self.total_failed_unique

    @classmethod
    def calculate(
        cls,
        total_unique_submitted: int | None = None,
        completed_jobs: Mapping[str, JobResult] | None = None,
        failed_jobs: Mapping[str, JobResult] | None = None,
        total_execution_attempts: int | None = None,
        total_retries: int = 0,
        worker_failures: int = 0,
        jobs_recovered: int = 0,
        jobs_permanently_failed: int = 0,
        recovery_time_sec: float = 0.0,
        duplicate_results_ignored: int = 0,
        wall_clock_duration: float = 0.0,
        # Milestone 2 backwards compatibility parameters:
        total_submitted: int | None = None,
        results: Sequence[JobResult] | None = None,
    ) -> RunMetrics:
        """Calculate verified metrics enforcing terminal accounting:
        completed_unique + failed_unique == total_unique_submitted.
        Supports both Milestone 2 and Milestone 3 callers.
        """
        # Resolve submitted count
        submitted = total_unique_submitted if total_unique_submitted is not None else (total_submitted or 0)

        # Resolve completed and failed jobs mappings
        comp_dict: dict[str, JobResult] = {}
        fail_dict: dict[str, JobResult] = {}

        if results is not None:
            for r in results:
                if r.status == JobStatus.COMPLETED and r.job_id not in comp_dict:
                    comp_dict[r.job_id] = r
                elif r.status == JobStatus.FAILED:
                    fail_dict[r.job_id] = r
        if completed_jobs is not None:
            comp_dict.update(completed_jobs)
        if failed_jobs is not None:
            fail_dict.update(failed_jobs)

        completed_unique = len(comp_dict)
        failed_unique = len(fail_dict)

        # Enforce terminal accounting: any unaccounted job is marked failed
        unaccounted = max(0, submitted - (completed_unique + failed_unique))
        if unaccounted > 0:
            failed_unique += unaccounted
            jobs_permanently_failed += unaccounted

        attempts = total_execution_attempts if total_execution_attempts is not None else (completed_unique + failed_unique)

        latencies = [r.total_latency for r in comp_dict.values()]
        durations = [r.processing_duration for r in comp_dict.values()]

        # Primary throughput: unique completed jobs per wall-clock second
        throughput = (completed_unique / wall_clock_duration) if wall_clock_duration > 0 else 0.0
        # Secondary attempt throughput: total execution attempts per second
        attempt_throughput = (attempts / wall_clock_duration) if wall_clock_duration > 0 else 0.0

        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        avg_processing_time = (sum(durations) / len(durations)) if durations else 0.0

        p50 = compute_percentile(latencies, 50.0)
        p95 = compute_percentile(latencies, 95.0)
        p99 = compute_percentile(latencies, 99.0)

        if completed_unique > 0:
            completed_attempts = sum(r.attempt for r in comp_dict.values())
            avg_attempts = completed_attempts / completed_unique
        else:
            avg_attempts = 0.0

        return cls(
            total_unique_submitted=submitted,
            total_execution_attempts=attempts,
            total_completed_unique=completed_unique,
            total_failed_unique=failed_unique,
            total_retries=total_retries,
            worker_failures=worker_failures,
            jobs_recovered=jobs_recovered,
            jobs_permanently_failed=jobs_permanently_failed,
            recovery_time_sec=recovery_time_sec,
            avg_attempts_per_completed_job=round(avg_attempts, 3),
            duplicate_results_ignored=duplicate_results_ignored,
            wall_clock_duration=wall_clock_duration,
            throughput=throughput,
            attempt_throughput=attempt_throughput,
            avg_latency=avg_latency,
            p50_latency=p50,
            p95_latency=p95,
            p99_latency=p99,
            avg_processing_time=avg_processing_time,
        )

    def to_dict(self) -> dict[str, float | int]:
        """Convert metrics to a serializable dictionary."""
        return {
            "total_unique_submitted": self.total_unique_submitted,
            "total_execution_attempts": self.total_execution_attempts,
            "total_completed_unique": self.total_completed_unique,
            "total_failed_unique": self.total_failed_unique,
            "total_retries": self.total_retries,
            "worker_failures": self.worker_failures,
            "jobs_recovered": self.jobs_recovered,
            "jobs_permanently_failed": self.jobs_permanently_failed,
            "recovery_time_sec": round(self.recovery_time_sec, 6),
            "avg_attempts_per_completed_job": self.avg_attempts_per_completed_job,
            "duplicate_results_ignored": self.duplicate_results_ignored,
            "wall_clock_duration_sec": round(self.wall_clock_duration, 6),
            "throughput_jobs_per_sec": round(self.throughput, 2),
            "attempt_throughput_per_sec": round(self.attempt_throughput, 2),
            "avg_latency_sec": round(self.avg_latency, 6),
            "p50_latency_sec": round(self.p50_latency, 6),
            "p95_latency_sec": round(self.p95_latency, 6),
            "p99_latency_sec": round(self.p99_latency, 6),
            "avg_processing_time_sec": round(self.avg_processing_time, 6),
        }
