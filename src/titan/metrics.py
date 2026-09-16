"""Telemetry and metrics calculation for Titan benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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

    total_submitted: int
    total_completed: int
    total_failed: int
    wall_clock_duration: float
    throughput: float
    avg_latency: float
    p50_latency: float
    p95_latency: float
    p99_latency: float
    avg_processing_time: float

    @classmethod
    def calculate(
        cls,
        total_submitted: int,
        results: Sequence[JobResult],
        wall_clock_duration: float,
    ) -> RunMetrics:
        """Calculate metrics from raw job results and overall wall-clock time."""
        completed_results = [r for r in results if r.status == JobStatus.COMPLETED]
        failed_results = [r for r in results if r.status == JobStatus.FAILED]

        # Account for lost jobs (jobs submitted but never reported in results)
        unreported_count = max(0, total_submitted - len(results))
        total_failed = len(failed_results) + unreported_count
        total_completed = len(completed_results)

        latencies = [r.total_latency for r in completed_results]
        durations = [r.processing_duration for r in completed_results]

        throughput = (total_completed / wall_clock_duration) if wall_clock_duration > 0 else 0.0
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        avg_processing_time = (sum(durations) / len(durations)) if durations else 0.0

        p50 = compute_percentile(latencies, 50.0)
        p95 = compute_percentile(latencies, 95.0)
        p99 = compute_percentile(latencies, 99.0)

        return cls(
            total_submitted=total_submitted,
            total_completed=total_completed,
            total_failed=total_failed,
            wall_clock_duration=wall_clock_duration,
            throughput=throughput,
            avg_latency=avg_latency,
            p50_latency=p50,
            p95_latency=p95,
            p99_latency=p99,
            avg_processing_time=avg_processing_time,
        )

    def to_dict(self) -> dict[str, float | int]:
        """Convert metrics to a serializable dictionary."""
        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "wall_clock_duration_sec": round(self.wall_clock_duration, 6),
            "throughput_jobs_per_sec": round(self.throughput, 2),
            "avg_latency_sec": round(self.avg_latency, 6),
            "p50_latency_sec": round(self.p50_latency, 6),
            "p95_latency_sec": round(self.p95_latency, 6),
            "p99_latency_sec": round(self.p99_latency, 6),
            "avg_processing_time_sec": round(self.avg_processing_time, 6),
        }
