"""Trial, result, aggregation, and comparison models for recovery-policy experiments.

Provides structured, serializable experiment models representing individual trials,
aggregated multi-trial results, and side-by-side policy comparisons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from titan.experiment.metrics import ExperimentMetrics


@dataclass(frozen=True)
class ExperimentTrial:
    """Individual execution outcome of a (Scenario × Policy × Repetition) trial."""

    experiment_id: str
    scenario_id: str
    scenario_class: str
    policy_id: str
    policy_config: dict[str, Any]
    repetition: int
    execution_status: str
    replay_valid: bool
    analysis_status: str
    metrics: ExperimentMetrics
    artifacts: dict[str, str] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize trial result to dictionary matching Prompt 9 specification."""
        return {
            "experiment_id": self.experiment_id,
            "scenario_id": self.scenario_id,
            "scenario_class": self.scenario_class,
            "policy_id": self.policy_id,
            "policy_config": self.policy_config,
            "repetition": self.repetition,
            "execution_status": self.execution_status,
            "replay_valid": self.replay_valid,
            "analysis_status": self.analysis_status,
            "total_jobs": self.metrics.total_jobs,
            "completed_jobs": self.metrics.completed_jobs,
            "failed_jobs": self.metrics.failed_jobs,
            "total_attempts": self.metrics.total_attempts,
            "retries": self.metrics.retries,
            "duplicate_executions": self.metrics.duplicate_work,
            "duplicate_completions_ignored": self.metrics.duplicate_completions_ignored,
            "worker_failures": self.metrics.worker_failures,
            "worker_replacements": self.metrics.worker_replacements,
            "lost_work": self.metrics.lost_work,
            "recovery_classification": self.metrics.recovery_classification,
            "execution_duration": self.metrics.wall_clock_duration_sec,
            "failure_detection_timing": None,
            "recovery_completion_timing": self.metrics.recovery_duration_sec,
            "metrics": self.metrics.to_dict(),
            "artifacts": dict(self.artifacts),
            "validation_errors": list(self.validation_errors),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize trial result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentTrial:
        """Reconstruct ExperimentTrial from serialized dictionary."""
        mdata = data["metrics"]
        metrics = ExperimentMetrics(
            recovery_rate=float(mdata["recovery_rate"]),
            unrecovered_failure_rate=float(mdata["unrecovered_failure_rate"]),
            invariant_violations=int(mdata["invariant_violations"]),
            total_jobs=int(mdata["total_jobs"]),
            completed_jobs=int(mdata["completed_jobs"]),
            failed_jobs=int(mdata["failed_jobs"]),
            total_attempts=int(mdata["total_attempts"]),
            retries=int(mdata["retries"]),
            duplicate_work=int(mdata["duplicate_work"]),
            lost_work=int(mdata["lost_work"]),
            retry_overhead=float(mdata["retry_overhead"]),
            duplicate_completions_ignored=int(mdata["duplicate_completions_ignored"]),
            worker_failures=int(mdata["worker_failures"]),
            worker_replacements=int(mdata["worker_replacements"]),
            recovery_classification=str(mdata["recovery_classification"]),
            recovery_duration_sec=float(mdata["recovery_duration_sec"]),
            wall_clock_duration_sec=float(mdata["wall_clock_duration_sec"]),
            goodput_jobs_per_sec=float(mdata["goodput_jobs_per_sec"]),
            avg_latency_ms=float(mdata["avg_latency_ms"]),
            p50_latency_ms=float(mdata["p50_latency_ms"]),
            p95_latency_ms=float(mdata["p95_latency_ms"]),
            p99_latency_ms=float(mdata["p99_latency_ms"]),
        )
        return cls(
            experiment_id=data["experiment_id"],
            scenario_id=data["scenario_id"],
            scenario_class=data["scenario_class"],
            policy_id=data["policy_id"],
            policy_config=data["policy_config"],
            repetition=int(data["repetition"]),
            execution_status=data["execution_status"],
            replay_valid=bool(data["replay_valid"]),
            analysis_status=data["analysis_status"],
            metrics=metrics,
            artifacts=data.get("artifacts", {}),
            validation_errors=data.get("validation_errors", []),
        )


@dataclass(frozen=True)
class MetricStats:
    """Summary statistics (count, mean, median, min, max) for numeric experiment metrics."""

    count: int
    mean: float
    median: float = 0.0
    min: float = 0.0
    max: float = 0.0

    @classmethod
    def compute(cls, values: Sequence[float | int]) -> MetricStats:
        """Compute count, mean, median, min, max from a sequence of numeric values."""
        if not values:
            return cls(count=0, mean=0.0, median=0.0, min=0.0, max=0.0)
        float_vals = [float(v) for v in values]
        import statistics
        return cls(
            count=len(float_vals),
            mean=sum(float_vals) / len(float_vals),
            median=float(statistics.median(float_vals)),
            min=min(float_vals),
            max=max(float_vals),
        )

    def to_dict(self) -> dict[str, float | int]:
        """Convert stats to dictionary."""
        return {
            "count": self.count,
            "mean": round(self.mean, 4),
            "median": round(self.median, 4),
            "min": round(self.min, 4),
            "max": round(self.max, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricStats:
        """Reconstruct MetricStats from dictionary."""
        return cls(
            count=int(data["count"]),
            mean=float(data["mean"]),
            median=float(data.get("median", data["mean"])),
            min=float(data["min"]),
            max=float(data["max"]),
        )


@dataclass(frozen=True)
class ExperimentResult:
    """Aggregated experimental evaluation across repeated trials for (Scenario × Policy)."""

    experiment_id: str
    scenario_id: str
    scenario_class: str
    policy_id: str
    policy_config: dict[str, Any]
    repetitions: int
    successful_trials: int
    failed_trials: int
    recovery_rate: float
    trials: list[ExperimentTrial]
    metric_summaries: dict[str, MetricStats]
    base_scenario_config: dict[str, Any] = field(default_factory=dict)
    effective_scenario_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def aggregate(
        cls,
        experiment_id: str,
        scenario_id: str,
        scenario_class: str,
        policy_id: str,
        policy_config: dict[str, Any],
        trials: list[ExperimentTrial],
        base_scenario_config: dict[str, Any] | None = None,
        effective_scenario_config: dict[str, Any] | None = None,
    ) -> ExperimentResult:
        """Aggregate multiple trials into a structured ExperimentResult."""
        total = len(trials)
        if total == 0:
            return cls(
                experiment_id=experiment_id,
                scenario_id=scenario_id,
                scenario_class=scenario_class,
                policy_id=policy_id,
                policy_config=policy_config,
                repetitions=0,
                successful_trials=0,
                failed_trials=0,
                recovery_rate=0.0,
                trials=[],
                metric_summaries={},
            )

        successful = sum(1 for t in trials if t.metrics.recovery_rate > 0.0)
        failed = total - successful
        rec_rate = successful / total

        metric_names = [
            "wall_clock_duration_sec",
            "recovery_duration_sec",
            "goodput_jobs_per_sec",
            "avg_latency_ms",
            "total_attempts",
            "retries",
            "duplicate_work",
            "lost_work",
            "completed_jobs",
            "failed_jobs",
            "worker_replacements",
        ]
        summaries: dict[str, MetricStats] = {}
        for mname in metric_names:
            vals = [getattr(t.metrics, mname) for t in trials]
            summaries[mname] = MetricStats.compute(vals)

        return cls(
            experiment_id=experiment_id,
            scenario_id=scenario_id,
            scenario_class=scenario_class,
            policy_id=policy_id,
            policy_config=policy_config,
            repetitions=total,
            successful_trials=successful,
            failed_trials=failed,
            recovery_rate=round(rec_rate, 4),
            trials=trials,
            metric_summaries=summaries,
            base_scenario_config=base_scenario_config or {},
            effective_scenario_config=effective_scenario_config or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert experiment result to dictionary."""
        return {
            "experiment_id": self.experiment_id,
            "scenario_id": self.scenario_id,
            "scenario_class": self.scenario_class,
            "policy_id": self.policy_id,
            "policy_config": self.policy_config,
            "repetitions": self.repetitions,
            "successful_trials": self.successful_trials,
            "failed_trials": self.failed_trials,
            "recovery_rate": self.recovery_rate,
            "metric_summaries": {k: v.to_dict() for k, v in self.metric_summaries.items()},
            "base_scenario_config": self.base_scenario_config,
            "effective_scenario_config": self.effective_scenario_config,
            "trials": [t.to_dict() for t in self.trials],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Convert experiment result to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentResult:
        """Reconstruct ExperimentResult from dictionary."""
        trials = [ExperimentTrial.from_dict(t) for t in data.get("trials", [])]
        summaries = {
            k: MetricStats.from_dict(v)
            for k, v in data.get("metric_summaries", {}).items()
        }
        return cls(
            experiment_id=data["experiment_id"],
            scenario_id=data["scenario_id"],
            scenario_class=data["scenario_class"],
            policy_id=data["policy_id"],
            policy_config=data["policy_config"],
            repetitions=int(data["repetitions"]),
            successful_trials=int(data["successful_trials"]),
            failed_trials=int(data["failed_trials"]),
            recovery_rate=float(data["recovery_rate"]),
            trials=trials,
            metric_summaries=summaries,
            base_scenario_config=data.get("base_scenario_config", {}),
            effective_scenario_config=data.get("effective_scenario_config", {}),
        )


@dataclass(frozen=True)
class PolicyComparison:
    """Comparative evaluation across multiple recovery policies for the same benchmark scenario."""

    scenario_id: str
    scenario_class: str
    policies: list[str]
    results: dict[str, ExperimentResult]
    observed_differences: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        scenario_id: str,
        scenario_class: str,
        results: Mapping[str, ExperimentResult],
    ) -> PolicyComparison:
        """Create a PolicyComparison from experiment results across policies on the same scenario."""
        policies = sorted(results.keys())
        observed: list[str] = []

        for pid in policies:
            res = results[pid]
            rec_pct = res.recovery_rate * 100.0
            comp = res.metric_summaries.get("completed_jobs")
            fail = res.metric_summaries.get("failed_jobs")
            retries = res.metric_summaries.get("retries")
            replacements = res.metric_summaries.get("worker_replacements")
            duration = res.metric_summaries.get("wall_clock_duration_sec")
            goodput = res.metric_summaries.get("goodput_jobs_per_sec")

            comp_val = int(comp.mean) if comp else 0
            fail_val = int(fail.mean) if fail else 0
            ret_val = retries.mean if retries else 0.0
            rep_val = int(replacements.mean) if replacements else 0
            goodput_val = goodput.mean if goodput else 0.0
            dur_val = duration.mean if duration else 0.0

            desc = (
                f"Policy {pid} ({res.policy_config.get('name', '')}): "
                f"Recovery Rate = {rec_pct:.1f}% ({comp_val} completed, {fail_val} failed); "
                f"Retries = {ret_val:.1f}; Replacements = {rep_val}; "
                f"Mean Goodput = {goodput_val:.2f} jobs/s (Duration = {dur_val:.4f}s)."
            )
            observed.append(desc)

        return cls(
            scenario_id=scenario_id,
            scenario_class=scenario_class,
            policies=policies,
            results=dict(results),
            observed_differences=observed,
        )

    def to_table(self) -> str:
        """Format comparison as a clear ASCII table."""
        lines = []
        header = f"| {'Metric':<30} |" + "".join(f" {p:<16} |" for p in self.policies)
        separator = f"|{'-' * 32}|" + "".join(f"{'-' * 18}|" for _ in self.policies)
        lines.append(header)
        lines.append(separator)

        rows = [
            ("Recovery Rate (%)", lambda r: f"{r.recovery_rate * 100.0:.1f}%"),
            (
                "Completed Jobs (mean)",
                lambda r: f"{r.metric_summaries.get('completed_jobs', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Failed Jobs (mean)",
                lambda r: f"{r.metric_summaries.get('failed_jobs', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Total Attempts (mean)",
                lambda r: f"{r.metric_summaries.get('total_attempts', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Retries (mean)",
                lambda r: f"{r.metric_summaries.get('retries', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Duplicate Work (mean)",
                lambda r: f"{r.metric_summaries.get('duplicate_work', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Lost Work (mean)",
                lambda r: f"{r.metric_summaries.get('lost_work', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Worker Replacements (mean)",
                lambda r: f"{r.metric_summaries.get('worker_replacements', MetricStats(0, 0, 0, 0)).mean:.1f}",
            ),
            (
                "Recovery Duration (mean s)",
                lambda r: f"{r.metric_summaries.get('recovery_duration_sec', MetricStats(0, 0, 0, 0)).mean:.4f}s",
            ),
            (
                "Goodput (mean jobs/s)",
                lambda r: f"{r.metric_summaries.get('goodput_jobs_per_sec', MetricStats(0, 0, 0, 0)).mean:.2f}",
            ),
            (
                "Wall-Clock Time (mean s)",
                lambda r: f"{r.metric_summaries.get('wall_clock_duration_sec', MetricStats(0, 0, 0, 0)).mean:.4f}s",
            ),
            (
                "Avg Latency (mean ms)",
                lambda r: f"{r.metric_summaries.get('avg_latency_ms', MetricStats(0, 0, 0, 0)).mean:.2f}ms",
            ),
        ]

        for label, extractor in rows:
            row_str = f"| {label:<30} |"
            for p in self.policies:
                res = self.results[p]
                val = extractor(res)
                row_str += f" {val:<16} |"
            lines.append(row_str)

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert comparison to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_class": self.scenario_class,
            "policies": self.policies,
            "observed_differences": self.observed_differences,
            "results": {k: v.to_dict() for k, v in self.results.items()},
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Convert comparison to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
