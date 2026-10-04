"""Metric extraction, definitions, and formulas for Titan recovery-policy experiments.

Defines exact formulas, units, scope, and technical boundaries for all reported metrics,
ensuring strict adherence to the Metric Honesty Rule (no fabricated or proxy values).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from titan.analysis import AnalysisReport
from titan.metrics import RunMetrics
from titan.replay import ReplayResult
from titan.trace import EventType, ExecutionTrace


@dataclass(frozen=True)
class MetricDefinition:
    """Formal specification and boundary documentation for an experimental metric."""

    name: str
    formula: str
    units: str
    scope: str
    description: str
    limitations: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "formula": self.formula,
            "units": self.units,
            "scope": self.scope,
            "description": self.description,
            "limitations": self.limitations,
        }


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "recovery_rate": MetricDefinition(
        name="recovery_rate",
        formula="1.0 if (analysis_status in ('CLEAN', 'RECOVERED') and failed_jobs == 0) else 0.0",
        units="ratio [0.0 - 1.0]",
        scope="Trial / Policy Summary",
        description="Proportion of trials in which all injected or encountered failures were fully resolved.",
        limitations="Binary per-trial indicator; partial job completion with unrecovered failures counts as 0.0.",
    ),
    "unrecovered_failure_rate": MetricDefinition(
        name="unrecovered_failure_rate",
        formula="1.0 - recovery_rate",
        units="ratio [0.0 - 1.0]",
        scope="Trial / Policy Summary",
        description="Proportion of trials in which at least one failure remained unrecovered or terminal job failure occurred.",
        limitations="Complement of recovery_rate.",
    ),
    "useful_completions": MetricDefinition(
        name="useful_completions",
        formula="count(distinct jobs reaching COMPLETED)",
        units="jobs",
        scope="Workload run",
        description="Unique logical jobs that completed successfully.",
        limitations="Ignores duplicate completions of the same job.",
    ),
    "total_attempts": MetricDefinition(
        name="total_attempts",
        formula="count(all execution attempts dispatched)",
        units="attempts",
        scope="Workload run",
        description="Total physical attempts executed across all worker processes.",
        limitations="Includes initial attempts and retries.",
    ),
    "retry_count": MetricDefinition(
        name="retry_count",
        formula="count(EventType.RETRY_SCHEDULED events)",
        units="retries",
        scope="Workload run",
        description="Number of re-execution attempts initiated following failure or loss.",
        limitations="Counts scheduled retries, regardless of whether the retry succeeds or subsequently fails.",
    ),
    "duplicate_work": MetricDefinition(
        name="duplicate_work",
        formula="max(0, total_attempts - useful_completions)",
        units="executions",
        scope="Workload run",
        description="Physical execution attempts spent beyond the 1-to-1 required for unique completions.",
        limitations="Does not measure sub-job CPU instructions; counts discrete attempt dispatches.",
    ),
    "retry_overhead": MetricDefinition(
        name="retry_overhead",
        formula="retry_count / useful_completions if useful_completions > 0 else 0.0",
        units="retries/job",
        scope="Workload run",
        description="Ratio of retries initiated per successfully completed unique job.",
        limitations="Undefined if 0 jobs complete (evaluates to 0.0).",
    ),
    "lost_work": MetricDefinition(
        name="lost_work",
        formula="count(EventType.JOB_LOST events)",
        units="attempts",
        scope="Workload run",
        description="Number of in-flight execution attempts interrupted and aborted mid-run by worker crashes.",
        limitations="Counts discarded attempts. Intra-attempt partial progress is not measured because jobs are atomic.",
    ),
    "worker_failures": MetricDefinition(
        name="worker_failures",
        formula="count(EventType.WORKER_FAILED events)",
        units="workers",
        scope="Workload run",
        description="Number of worker process termination events detected by the coordinator.",
        limitations="Measures process exit detection; does not distinguish OS signal types beyond exit codes.",
    ),
    "worker_replacements": MetricDefinition(
        name="worker_replacements",
        formula="count(EventType.WORKER_REPLACED events)",
        units="workers",
        scope="Workload run",
        description="Number of replacement worker processes successfully spawned to restore capacity.",
        limitations="Only increments when replace_failed_workers is enabled.",
    ),
    "wall_clock_duration_sec": MetricDefinition(
        name="wall_clock_duration_sec",
        formula="coordinator_stop_timestamp - coordinator_start_timestamp",
        units="seconds",
        scope="Workload run",
        description="Total elapsed wall-clock execution duration for the entire workload.",
        limitations="Subject to host OS scheduler jitter and subprocess spawning latency.",
    ),
    "recovery_duration_sec": MetricDefinition(
        name="recovery_duration_sec",
        formula="workload_completion_timestamp - first_failure_detected_timestamp if failure occurred else 0.0",
        units="seconds",
        scope="Failure interval",
        description="Elapsed time in seconds from initial failure detection to workload completion.",
        limitations="If subsequent jobs run after the failed job is retried, includes execution time of remaining workload.",
    ),
    "goodput_jobs_per_sec": MetricDefinition(
        name="goodput_jobs_per_sec",
        formula="useful_completions / wall_clock_duration_sec if wall_clock_duration_sec > 0 else 0.0",
        units="jobs/s",
        scope="Workload run",
        description="Useful logical completed work achieved per elapsed wall-clock second.",
        limitations="Excludes failed or redundant retry executions from the numerator.",
    ),
    "avg_latency_ms": MetricDefinition(
        name="avg_latency_ms",
        formula="mean(job_completion_time - job_submission_time) * 1000.0",
        units="milliseconds",
        scope="Completed jobs",
        description="Mean end-to-end elapsed latency from job submission to final completion.",
        limitations="Only computed across completed jobs.",
    ),
}

UNAVAILABLE_METRICS: dict[str, str] = {
    "cpu_utilization_pct": "Hardware CPU utilization is not sampled in-process to avoid measurement distortion.",
    "memory_rss_bytes": "Subprocess memory consumption is not continuously polled in the static multi-process runtime.",
    "network_io_bytes": "Communication uses standard library multiprocessing queues and pipes; no socket network layer exists.",
    "intra_job_partial_work_lost": "Titan jobs are atomic units; partial progress inside an uncompleted job is uncommitted and discarded.",
    "failure_detection_latency": "Absolute time delta between OS process termination and coordinator queue poll is not separately captured.",
}


@dataclass(frozen=True)
class ExperimentMetrics:
    """Rigorous, empirically measured metrics extracted for an experiment trial."""

    # Reliability
    recovery_rate: float
    unrecovered_failure_rate: float
    invariant_violations: int

    # Work
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_attempts: int
    retries: int
    duplicate_work: int
    lost_work: int
    retry_overhead: float
    duplicate_completions_ignored: int

    # Recovery
    worker_failures: int
    worker_replacements: int
    recovery_classification: str
    recovery_duration_sec: float

    # Performance
    wall_clock_duration_sec: float
    goodput_jobs_per_sec: float

    # Latency
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "recovery_rate": round(self.recovery_rate, 4),
            "unrecovered_failure_rate": round(self.unrecovered_failure_rate, 4),
            "invariant_violations": self.invariant_violations,
            "total_jobs": self.total_jobs,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": self.failed_jobs,
            "total_attempts": self.total_attempts,
            "retries": self.retries,
            "duplicate_work": self.duplicate_work,
            "lost_work": self.lost_work,
            "retry_overhead": round(self.retry_overhead, 4),
            "duplicate_completions_ignored": self.duplicate_completions_ignored,
            "worker_failures": self.worker_failures,
            "worker_replacements": self.worker_replacements,
            "recovery_classification": self.recovery_classification,
            "recovery_duration_sec": round(self.recovery_duration_sec, 6),
            "wall_clock_duration_sec": round(self.wall_clock_duration_sec, 6),
            "goodput_jobs_per_sec": round(self.goodput_jobs_per_sec, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "p99_latency_ms": round(self.p99_latency_ms, 3),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Convert metrics to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


def extract_experiment_metrics(
    trace: ExecutionTrace | None,
    metrics: RunMetrics,
    replay: ReplayResult,
    analysis: AnalysisReport,
) -> ExperimentMetrics:
    """Extract rigorous, non-fabricated metrics from execution, replay, and analysis records."""
    # Reliability
    is_recovered = (
        analysis.overall_status in ("CLEAN", "RECOVERED")
        and metrics.jobs_permanently_failed == 0
    )
    rec_rate = 1.0 if is_recovered else 0.0
    unrec_rate = 1.0 - rec_rate
    inv_violations = len(replay.validation_errors) + len(analysis.validation_errors)

    # Work
    completed = metrics.total_completed_unique
    attempts = metrics.total_execution_attempts
    retries = metrics.total_retries
    dup_work = max(0, attempts - completed)
    lost_work = (
        len([e for e in trace.events if e.event_type == EventType.JOB_LOST])
        if trace is not None
        else 0
    )
    retry_overhead = (retries / completed) if completed > 0 else 0.0

    # Recovery
    recovery_class = analysis.overall_status
    replacements = replay.worker_replacements
    rec_duration = metrics.recovery_time_sec

    # Performance
    wall_clock = metrics.wall_clock_duration
    goodput = (completed / wall_clock) if wall_clock > 0 else 0.0

    # Latency (converted to ms)
    avg_lat = metrics.avg_latency * 1000.0
    p50_lat = metrics.p50_latency * 1000.0
    p95_lat = metrics.p95_latency * 1000.0
    p99_lat = metrics.p99_latency * 1000.0

    return ExperimentMetrics(
        recovery_rate=rec_rate,
        unrecovered_failure_rate=unrec_rate,
        invariant_violations=inv_violations,
        total_jobs=metrics.total_unique_submitted,
        completed_jobs=completed,
        failed_jobs=metrics.jobs_permanently_failed,
        total_attempts=attempts,
        retries=retries,
        duplicate_work=dup_work,
        lost_work=lost_work,
        retry_overhead=retry_overhead,
        duplicate_completions_ignored=metrics.duplicate_results_ignored,
        worker_failures=metrics.worker_failures,
        worker_replacements=replacements,
        recovery_classification=recovery_class,
        recovery_duration_sec=rec_duration,
        wall_clock_duration_sec=wall_clock,
        goodput_jobs_per_sec=goodput,
        avg_latency_ms=avg_lat,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        p99_latency_ms=p99_lat,
    )
