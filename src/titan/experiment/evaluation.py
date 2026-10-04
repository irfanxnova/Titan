"""Replay / Tracing Overhead and System Stress Evaluation Framework.

Provides rigorous, reproducible evaluation of:
1. Tracing instrumentation runtime and memory/disk overhead (RQ4).
2. Deterministic replay runtime and trace-size cost (RQ5).
3. System scaling and stress behavior under controlled concurrency, workload size,
   failure intensity, and retry pressure.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from titan import __version__
from titan.analysis import FailureAnalyzer
from titan.bench.corpus import CorpusRegistry
from titan.experiment.policy import PolicyRegistry, RecoveryPolicy
from titan.experiment.trial import MetricStats
from titan.replay import ReplayEngine, ReplayResult
from titan.runtime import FailureConfig, StaticRuntime
from titan.scenario import FaultConfig, Scenario, ScenarioResult, run_scenario
from titan.trace import ExecutionTrace, TraceEvent


class EvaluationMode(str, Enum):
    """Execution and evaluation mode for overhead and scaling studies."""

    NO_TRACE = "no_trace"        # Mode A: Execution with trace collection disabled
    WITH_TRACE = "with_trace"    # Mode B: Execution with structured trace collection active
    REPLAY_ONLY = "replay_only"  # Mode C: Offline deterministic replay of an existing trace


# -----------------------------------------------------------------------------
# Metric Calculation Utilities with Safe Zero-Denominator Handling
# -----------------------------------------------------------------------------


def safe_div(numerator: float | int, denominator: float | int, fallback: float = 0.0) -> float:
    """Perform division with strict zero-denominator safeguard."""
    if denominator == 0.0 or denominator == 0:
        return fallback
    return float(numerator) / float(denominator)


def compute_relative_overhead(with_trace: float, no_trace: float) -> float:
    """Compute relative tracing overhead percentage: ((with - no) / no) * 100."""
    if no_trace <= 0.0:
        return 0.0
    return ((with_trace - no_trace) / no_trace) * 100.0


# -----------------------------------------------------------------------------
# Trace Overhead Data Models
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceOverheadTrial:
    """Individual trial comparing no-trace vs. trace-enabled execution on the same workload."""

    workload_name: str
    trial_index: int
    workers: int
    jobs: int
    work_units: int
    pattern: str
    seed: int | None
    no_trace_duration_sec: float
    with_trace_duration_sec: float
    trace_event_count: int
    trace_size_bytes: int
    trace_serialization_time_sec: float
    absolute_overhead_sec: float
    relative_overhead_pct: float
    bytes_per_event: float
    useful_completed_jobs: int
    total_attempts: int
    retries: int
    worker_failures: int
    worker_replacements: int

    def to_dict(self) -> dict[str, Any]:
        """Convert trial measurements to dictionary."""
        return {
            "workload_name": self.workload_name,
            "trial_index": self.trial_index,
            "workers": self.workers,
            "jobs": self.jobs,
            "work_units": self.work_units,
            "pattern": self.pattern,
            "seed": self.seed,
            "no_trace_duration_sec": round(self.no_trace_duration_sec, 6),
            "with_trace_duration_sec": round(self.with_trace_duration_sec, 6),
            "trace_event_count": self.trace_event_count,
            "trace_size_bytes": self.trace_size_bytes,
            "trace_serialization_time_sec": round(self.trace_serialization_time_sec, 6),
            "absolute_overhead_sec": round(self.absolute_overhead_sec, 6),
            "relative_overhead_pct": round(self.relative_overhead_pct, 4),
            "bytes_per_event": round(self.bytes_per_event, 2),
            "useful_completed_jobs": self.useful_completed_jobs,
            "total_attempts": self.total_attempts,
            "retries": self.retries,
            "worker_failures": self.worker_failures,
            "worker_replacements": self.worker_replacements,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceOverheadTrial:
        """Construct trial from dictionary."""
        return cls(
            workload_name=data["workload_name"],
            trial_index=int(data["trial_index"]),
            workers=int(data["workers"]),
            jobs=int(data["jobs"]),
            work_units=int(data["work_units"]),
            pattern=data.get("pattern", "uniform"),
            seed=data.get("seed"),
            no_trace_duration_sec=float(data["no_trace_duration_sec"]),
            with_trace_duration_sec=float(data["with_trace_duration_sec"]),
            trace_event_count=int(data["trace_event_count"]),
            trace_size_bytes=int(data["trace_size_bytes"]),
            trace_serialization_time_sec=float(data.get("trace_serialization_time_sec", 0.0)),
            absolute_overhead_sec=float(data["absolute_overhead_sec"]),
            relative_overhead_pct=float(data["relative_overhead_pct"]),
            bytes_per_event=float(data.get("bytes_per_event", 0.0)),
            useful_completed_jobs=int(data.get("useful_completed_jobs", 0)),
            total_attempts=int(data.get("total_attempts", 0)),
            retries=int(data.get("retries", 0)),
            worker_failures=int(data.get("worker_failures", 0)),
            worker_replacements=int(data.get("worker_replacements", 0)),
        )


@dataclass(frozen=True)
class TraceOverheadResult:
    """Aggregated tracing overhead measurement across multiple repetitions of a workload."""

    workload_name: str
    workers: int
    jobs: int
    work_units: int
    pattern: str
    repetitions: int
    trials: list[TraceOverheadTrial]
    no_trace_duration_stats: MetricStats
    with_trace_duration_stats: MetricStats
    absolute_overhead_stats: MetricStats
    relative_overhead_stats: MetricStats
    event_count: int
    trace_size_bytes: int
    trace_serialization_stats: MetricStats
    bytes_per_event: float
    useful_completed_jobs: int
    total_attempts: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "workload_name": self.workload_name,
            "workers": self.workers,
            "jobs": self.jobs,
            "work_units": self.work_units,
            "pattern": self.pattern,
            "repetitions": self.repetitions,
            "no_trace_duration_stats": self.no_trace_duration_stats.to_dict(),
            "with_trace_duration_stats": self.with_trace_duration_stats.to_dict(),
            "absolute_overhead_stats": self.absolute_overhead_stats.to_dict(),
            "relative_overhead_stats": self.relative_overhead_stats.to_dict(),
            "event_count": self.event_count,
            "trace_size_bytes": self.trace_size_bytes,
            "trace_serialization_stats": self.trace_serialization_stats.to_dict(),
            "bytes_per_event": round(self.bytes_per_event, 2),
            "useful_completed_jobs": self.useful_completed_jobs,
            "total_attempts": self.total_attempts,
            "trials": [t.to_dict() for t in self.trials],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceOverheadResult:
        """Construct TraceOverheadResult from dictionary."""
        return cls(
            workload_name=data["workload_name"],
            workers=int(data["workers"]),
            jobs=int(data["jobs"]),
            work_units=int(data["work_units"]),
            pattern=data.get("pattern", "uniform"),
            repetitions=int(data["repetitions"]),
            trials=[TraceOverheadTrial.from_dict(t) for t in data.get("trials", [])],
            no_trace_duration_stats=MetricStats.from_dict(data["no_trace_duration_stats"]),
            with_trace_duration_stats=MetricStats.from_dict(data["with_trace_duration_stats"]),
            absolute_overhead_stats=MetricStats.from_dict(data["absolute_overhead_stats"]),
            relative_overhead_stats=MetricStats.from_dict(data["relative_overhead_stats"]),
            event_count=int(data["event_count"]),
            trace_size_bytes=int(data["trace_size_bytes"]),
            trace_serialization_stats=MetricStats.from_dict(data["trace_serialization_stats"]),
            bytes_per_event=float(data["bytes_per_event"]),
            useful_completed_jobs=int(data.get("useful_completed_jobs", 0)),
            total_attempts=int(data.get("total_attempts", 0)),
        )


# -----------------------------------------------------------------------------
# Replay Evaluation Data Models
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayEvaluationTrial:
    """Single timing measurement of replaying a structured trace."""

    trace_name: str
    trial_index: int
    trace_event_count: int
    trace_size_bytes: int
    replay_duration_sec: float
    replay_events_per_sec: float
    replay_valid: bool
    validation_error_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert trial measurements to dictionary."""
        return {
            "trace_name": self.trace_name,
            "trial_index": self.trial_index,
            "trace_event_count": self.trace_event_count,
            "trace_size_bytes": self.trace_size_bytes,
            "replay_duration_sec": round(self.replay_duration_sec, 6),
            "replay_events_per_sec": round(self.replay_events_per_sec, 2),
            "replay_valid": self.replay_valid,
            "validation_error_count": self.validation_error_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReplayEvaluationTrial:
        """Construct trial from dictionary."""
        return cls(
            trace_name=data["trace_name"],
            trial_index=int(data["trial_index"]),
            trace_event_count=int(data["trace_event_count"]),
            trace_size_bytes=int(data["trace_size_bytes"]),
            replay_duration_sec=float(data["replay_duration_sec"]),
            replay_events_per_sec=float(data["replay_events_per_sec"]),
            replay_valid=bool(data["replay_valid"]),
            validation_error_count=int(data["validation_error_count"]),
        )


@dataclass(frozen=True)
class ReplayEvaluationResult:
    """Aggregated replay runtime and throughput evaluation for a trace."""

    trace_name: str
    trace_source: str
    trace_event_count: int
    trace_size_bytes: int
    repetitions: int
    trials: list[ReplayEvaluationTrial]
    replay_duration_stats: MetricStats
    replay_throughput_stats: MetricStats
    replay_valid: bool
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "trace_name": self.trace_name,
            "trace_source": self.trace_source,
            "trace_event_count": self.trace_event_count,
            "trace_size_bytes": self.trace_size_bytes,
            "repetitions": self.repetitions,
            "replay_duration_stats": self.replay_duration_stats.to_dict(),
            "replay_throughput_stats": self.replay_throughput_stats.to_dict(),
            "replay_valid": self.replay_valid,
            "validation_errors": list(self.validation_errors),
            "trials": [t.to_dict() for t in self.trials],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReplayEvaluationResult:
        """Construct ReplayEvaluationResult from dictionary."""
        return cls(
            trace_name=data["trace_name"],
            trace_source=data["trace_source"],
            trace_event_count=int(data["trace_event_count"]),
            trace_size_bytes=int(data["trace_size_bytes"]),
            repetitions=int(data["repetitions"]),
            trials=[ReplayEvaluationTrial.from_dict(t) for t in data.get("trials", [])],
            replay_duration_stats=MetricStats.from_dict(data["replay_duration_stats"]),
            replay_throughput_stats=MetricStats.from_dict(data["replay_throughput_stats"]),
            replay_valid=bool(data["replay_valid"]),
            validation_errors=list(data.get("validation_errors", [])),
        )


# -----------------------------------------------------------------------------
# Stress / Scaling Evaluation Data Models
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class StressWorkloadConfig:
    """Explicit configuration for stress and scalability evaluation."""

    name: str
    category: str  # "concurrency_scaling", "workload_scaling", "failure_stress", "retry_stress"
    workers: int
    jobs: int
    work_units: int
    pattern: str = "uniform"
    seed: int | None = 42
    fault_config: FaultConfig | None = None
    fault_configs: tuple[FaultConfig, ...] = ()
    max_retries: int = 3
    replace_failed_workers: bool = True
    timeout: float | None = 30.0

    def to_scenario(self) -> Scenario:
        """Convert stress config to an executable Scenario."""
        return Scenario(
            name=self.name,
            num_workers=self.workers,
            num_jobs=self.jobs,
            work_units=self.work_units,
            pattern=self.pattern,
            seed=self.seed,
            max_retries=self.max_retries,
            replace_failed_workers=self.replace_failed_workers,
            fault_config=self.fault_config,
            fault_configs=self.fault_configs,
            timeout=self.timeout,
            enable_tracing=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "name": self.name,
            "category": self.category,
            "workers": self.workers,
            "jobs": self.jobs,
            "work_units": self.work_units,
            "pattern": self.pattern,
            "seed": self.seed,
            "max_retries": self.max_retries,
            "replace_failed_workers": self.replace_failed_workers,
            "timeout": self.timeout,
            "has_fault": self.fault_config is not None or len(self.fault_configs) > 0,
        }


@dataclass(frozen=True)
class StressTrial:
    """Individual execution outcome of a stress workload trial."""

    config_name: str
    category: str
    trial_index: int
    workers: int
    jobs: int
    work_units: int
    execution_status: str  # "COMPLETED", "TIMEOUT", "FAILED"
    recovery_outcome: str  # "RECOVERED", "CLEAN", "UNRECOVERED", "TIMEOUT", "ERROR"
    completed_jobs: int
    failed_jobs: int
    total_attempts: int
    retries: int
    worker_failures: int
    worker_replacements: int
    trace_event_count: int
    trace_size_bytes: int
    replay_valid: bool
    replay_duration_sec: float
    wall_clock_duration_sec: float
    goodput_jobs_per_sec: float

    def to_dict(self) -> dict[str, Any]:
        """Convert trial measurements to dictionary."""
        return {
            "config_name": self.config_name,
            "category": self.category,
            "trial_index": self.trial_index,
            "workers": self.workers,
            "jobs": self.jobs,
            "work_units": self.work_units,
            "execution_status": self.execution_status,
            "recovery_outcome": self.recovery_outcome,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": self.failed_jobs,
            "total_attempts": self.total_attempts,
            "retries": self.retries,
            "worker_failures": self.worker_failures,
            "worker_replacements": self.worker_replacements,
            "trace_event_count": self.trace_event_count,
            "trace_size_bytes": self.trace_size_bytes,
            "replay_valid": self.replay_valid,
            "replay_duration_sec": round(self.replay_duration_sec, 6),
            "wall_clock_duration_sec": round(self.wall_clock_duration_sec, 6),
            "goodput_jobs_per_sec": round(self.goodput_jobs_per_sec, 4),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StressTrial:
        """Construct trial from dictionary."""
        return cls(
            config_name=data["config_name"],
            category=data["category"],
            trial_index=int(data["trial_index"]),
            workers=int(data["workers"]),
            jobs=int(data["jobs"]),
            work_units=int(data["work_units"]),
            execution_status=data["execution_status"],
            recovery_outcome=data["recovery_outcome"],
            completed_jobs=int(data["completed_jobs"]),
            failed_jobs=int(data["failed_jobs"]),
            total_attempts=int(data["total_attempts"]),
            retries=int(data["retries"]),
            worker_failures=int(data["worker_failures"]),
            worker_replacements=int(data["worker_replacements"]),
            trace_event_count=int(data["trace_event_count"]),
            trace_size_bytes=int(data["trace_size_bytes"]),
            replay_valid=bool(data["replay_valid"]),
            replay_duration_sec=float(data["replay_duration_sec"]),
            wall_clock_duration_sec=float(data["wall_clock_duration_sec"]),
            goodput_jobs_per_sec=float(data["goodput_jobs_per_sec"]),
        )


@dataclass(frozen=True)
class StressEvaluationResult:
    """Aggregated stress evaluation across repetitions of a stress configuration."""

    config: StressWorkloadConfig
    repetitions: int
    trials: list[StressTrial]
    execution_duration_stats: MetricStats
    replay_duration_stats: MetricStats
    goodput_stats: MetricStats
    successful_trials: int
    recovery_rate: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "config": self.config.to_dict(),
            "repetitions": self.repetitions,
            "successful_trials": self.successful_trials,
            "recovery_rate": round(self.recovery_rate, 4),
            "execution_duration_stats": self.execution_duration_stats.to_dict(),
            "replay_duration_stats": self.replay_duration_stats.to_dict(),
            "goodput_stats": self.goodput_stats.to_dict(),
            "trials": [t.to_dict() for t in self.trials],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StressEvaluationResult:
        """Construct StressEvaluationResult from dictionary."""
        cfg_d = data["config"]
        config = StressWorkloadConfig(
            name=cfg_d["name"],
            category=cfg_d["category"],
            workers=int(cfg_d["workers"]),
            jobs=int(cfg_d["jobs"]),
            work_units=int(cfg_d["work_units"]),
            pattern=cfg_d.get("pattern", "uniform"),
            seed=cfg_d.get("seed"),
            max_retries=int(cfg_d.get("max_retries", 3)),
            replace_failed_workers=bool(cfg_d.get("replace_failed_workers", True)),
            timeout=float(cfg_d["timeout"]) if cfg_d.get("timeout") is not None else None,
        )
        return cls(
            config=config,
            repetitions=int(data["repetitions"]),
            trials=[StressTrial.from_dict(t) for t in data.get("trials", [])],
            execution_duration_stats=MetricStats.from_dict(data["execution_duration_stats"]),
            replay_duration_stats=MetricStats.from_dict(data["replay_duration_stats"]),
            goodput_stats=MetricStats.from_dict(data["goodput_stats"]),
            successful_trials=int(data["successful_trials"]),
            recovery_rate=float(data["recovery_rate"]),
        )


# -----------------------------------------------------------------------------
# System Evaluation Suite Model
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemEvaluationSuite:
    """Comprehensive container aggregating overhead, replay, and stress measurements."""

    timestamp: float
    platform_info: dict[str, Any]
    trace_overhead_results: list[TraceOverheadResult]
    replay_results: list[ReplayEvaluationResult]
    stress_results: list[StressEvaluationResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialize suite to dictionary."""
        return {
            "timestamp": self.timestamp,
            "platform_info": self.platform_info,
            "trace_overhead": [r.to_dict() for r in self.trace_overhead_results],
            "replay_overhead": [r.to_dict() for r in self.replay_results],
            "stress_evaluation": [r.to_dict() for r in self.stress_results],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize suite to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SystemEvaluationSuite:
        """Construct SystemEvaluationSuite from dictionary."""
        return cls(
            timestamp=float(data["timestamp"]),
            platform_info=dict(data.get("platform_info", {})),
            trace_overhead_results=[
                TraceOverheadResult.from_dict(d) for d in data.get("trace_overhead", [])
            ],
            replay_results=[
                ReplayEvaluationResult.from_dict(d) for d in data.get("replay_overhead", [])
            ],
            stress_results=[
                StressEvaluationResult.from_dict(d) for d in data.get("stress_evaluation", [])
            ],
        )


# -----------------------------------------------------------------------------
# Evaluation Runner
# -----------------------------------------------------------------------------


class EvaluationRunner:
    """Orchestrator for tracing overhead, replay performance, and stress evaluations."""

    def __init__(self, output_base_dir: str | Path = "experiments/results") -> None:
        self.output_base_dir = Path(output_base_dir)

    @staticmethod
    def get_platform_info() -> dict[str, Any]:
        """Collect local execution environment context for research transparency."""
        return {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count() or 1,
            "titan_version": __version__,
        }

    # -------------------------------------------------------------------------
    # 1. Tracing Overhead Evaluation
    # -------------------------------------------------------------------------

    def run_trace_overhead(
        self,
        scenario: Scenario,
        repetitions: int = 3,
        warmup: bool = True,
        save_artifacts: bool = True,
    ) -> TraceOverheadResult:
        """Measure tracing overhead by comparing identical workloads with and without tracing."""
        scenario.validate()

        # Step 1: Optional warm-up run (excluded from reported measurements)
        # Allows OS process spawning and module importing caches to stabilize.
        if warmup:
            warmup_scenario = Scenario(
                name="warmup",
                num_workers=scenario.num_workers,
                num_jobs=min(5, max(1, scenario.num_jobs // 4)),
                work_units=scenario.work_units,
                pattern=scenario.pattern,
                seed=scenario.seed,
                max_retries=scenario.max_retries,
                replace_failed_workers=scenario.replace_failed_workers,
                enable_tracing=False,
            )
            try:
                run_scenario(warmup_scenario)
            except Exception:
                pass

        trials: list[TraceOverheadTrial] = []
        no_trace_durations: list[float] = []
        with_trace_durations: list[float] = []
        abs_overheads: list[float] = []
        rel_overheads: list[float] = []
        ser_times: list[float] = []

        last_event_count = 0
        last_trace_size = 0
        last_bytes_per_event = 0.0
        useful_completions = 0
        total_attempts = 0

        for trial_idx in range(1, repetitions + 1):
            # A. Execute without trace collection (Mode A)
            no_trace_scenario = Scenario(
                name=f"{scenario.name}_notrace",
                num_workers=scenario.num_workers,
                num_jobs=scenario.num_jobs,
                work_units=scenario.work_units,
                pattern=scenario.pattern,
                seed=scenario.seed,
                max_retries=scenario.max_retries,
                replace_failed_workers=scenario.replace_failed_workers,
                fault_config=scenario.fault_config,
                fault_configs=scenario.fault_configs,
                duplicate_jobs=scenario.duplicate_jobs,
                timeout=scenario.timeout,
                enable_tracing=False,
            )
            t0 = time.perf_counter()
            res_notrace = run_scenario(no_trace_scenario)
            no_trace_dur = time.perf_counter() - t0

            # B. Execute with canonical structured trace collection (Mode B)
            with_trace_scenario = Scenario(
                name=f"{scenario.name}_withtrace",
                num_workers=scenario.num_workers,
                num_jobs=scenario.num_jobs,
                work_units=scenario.work_units,
                pattern=scenario.pattern,
                seed=scenario.seed,
                max_retries=scenario.max_retries,
                replace_failed_workers=scenario.replace_failed_workers,
                fault_config=scenario.fault_config,
                fault_configs=scenario.fault_configs,
                duplicate_jobs=scenario.duplicate_jobs,
                timeout=scenario.timeout,
                enable_tracing=True,
            )
            t0 = time.perf_counter()
            res_withtrace = run_scenario(with_trace_scenario)
            with_trace_dur = time.perf_counter() - t0

            # Trace serialization and size measurement
            trace = res_withtrace.trace
            event_count = len(trace) if trace is not None else 0

            t_ser0 = time.perf_counter()
            trace_json_str = trace.to_json(indent=None) if trace is not None else "[]"
            ser_dur = time.perf_counter() - t_ser0

            trace_bytes = len(trace_json_str.encode("utf-8"))
            bytes_per_ev = safe_div(trace_bytes, event_count)

            abs_ovh = with_trace_dur - no_trace_dur
            rel_ovh = compute_relative_overhead(with_trace_dur, no_trace_dur)

            no_trace_durations.append(no_trace_dur)
            with_trace_durations.append(with_trace_dur)
            abs_overheads.append(abs_ovh)
            rel_overheads.append(rel_ovh)
            ser_times.append(ser_dur)

            last_event_count = event_count
            last_trace_size = trace_bytes
            last_bytes_per_event = bytes_per_ev
            useful_completions = res_withtrace.metrics.total_completed_unique
            total_attempts = res_withtrace.metrics.total_execution_attempts

            trial = TraceOverheadTrial(
                workload_name=scenario.name,
                trial_index=trial_idx,
                workers=scenario.num_workers,
                jobs=scenario.num_jobs,
                work_units=scenario.work_units,
                pattern=scenario.pattern,
                seed=scenario.seed,
                no_trace_duration_sec=no_trace_dur,
                with_trace_duration_sec=with_trace_dur,
                trace_event_count=event_count,
                trace_size_bytes=trace_bytes,
                trace_serialization_time_sec=ser_dur,
                absolute_overhead_sec=abs_ovh,
                relative_overhead_pct=rel_ovh,
                bytes_per_event=bytes_per_ev,
                useful_completed_jobs=useful_completions,
                total_attempts=total_attempts,
                retries=res_withtrace.metrics.total_retries,
                worker_failures=res_withtrace.metrics.worker_failures,
                worker_replacements=res_withtrace.metrics.jobs_recovered,
            )
            trials.append(trial)

        result = TraceOverheadResult(
            workload_name=scenario.name,
            workers=scenario.num_workers,
            jobs=scenario.num_jobs,
            work_units=scenario.work_units,
            pattern=scenario.pattern,
            repetitions=repetitions,
            trials=trials,
            no_trace_duration_stats=MetricStats.compute(no_trace_durations),
            with_trace_duration_stats=MetricStats.compute(with_trace_durations),
            absolute_overhead_stats=MetricStats.compute(abs_overheads),
            relative_overhead_stats=MetricStats.compute(rel_overheads),
            event_count=last_event_count,
            trace_size_bytes=last_trace_size,
            trace_serialization_stats=MetricStats.compute(ser_times),
            bytes_per_event=last_bytes_per_event,
            useful_completed_jobs=useful_completions,
            total_attempts=total_attempts,
        )

        if save_artifacts:
            out_dir = self.output_base_dir / "overhead"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"overhead_{scenario.name}.json"
            out_file.write_text(result.to_json(indent=2), encoding="utf-8")

        return result

    # -------------------------------------------------------------------------
    # 2. Replay Runtime & Throughput Evaluation
    # -------------------------------------------------------------------------

    def run_replay_evaluation(
        self,
        trace: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path,
        trace_name: str = "trace",
        trace_source: str = "generated",
        repetitions: int = 5,
        warmup: bool = True,
        save_artifacts: bool = True,
    ) -> ReplayEvaluationResult:
        """Measure deterministic replay duration and event throughput across repeated trials."""
        # Normalize trace
        if isinstance(trace, (str, Path)):
            tr = ExecutionTrace.load_from_file(trace)
        elif isinstance(trace, ExecutionTrace):
            tr = trace
        else:
            tr = ExecutionTrace(
                [e if isinstance(e, TraceEvent) else TraceEvent.from_dict(e) for e in trace]
            )

        event_count = len(tr)
        json_bytes = len(tr.to_json(indent=None).encode("utf-8"))

        # Warm-up replay iteration
        if warmup:
            try:
                ReplayEngine.replay(tr)
            except Exception:
                pass

        trials: list[ReplayEvaluationTrial] = []
        durations: list[float] = []
        throughputs: list[float] = []
        all_valid = True
        all_errors: list[str] = []

        for trial_idx in range(1, repetitions + 1):
            t0 = time.perf_counter()
            replay_res = ReplayEngine.replay(tr)
            dur = time.perf_counter() - t0

            if not replay_res.valid:
                all_valid = False
                all_errors.extend(replay_res.validation_errors)

            throughput = safe_div(event_count, dur)
            durations.append(dur)
            throughputs.append(throughput)

            trial = ReplayEvaluationTrial(
                trace_name=trace_name,
                trial_index=trial_idx,
                trace_event_count=event_count,
                trace_size_bytes=json_bytes,
                replay_duration_sec=dur,
                replay_events_per_sec=throughput,
                replay_valid=replay_res.valid,
                validation_error_count=len(replay_res.validation_errors),
            )
            trials.append(trial)

        result = ReplayEvaluationResult(
            trace_name=trace_name,
            trace_source=trace_source,
            trace_event_count=event_count,
            trace_size_bytes=json_bytes,
            repetitions=repetitions,
            trials=trials,
            replay_duration_stats=MetricStats.compute(durations),
            replay_throughput_stats=MetricStats.compute(throughputs),
            replay_valid=all_valid,
            validation_errors=sorted(list(set(all_errors))),
        )

        if save_artifacts:
            out_dir = self.output_base_dir / "replay"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"replay_{trace_name}.json"
            out_file.write_text(result.to_json(indent=2), encoding="utf-8")

        return result

    # -------------------------------------------------------------------------
    # 3. Stress & Scalability Evaluation
    # -------------------------------------------------------------------------

    def run_stress_evaluation(
        self,
        config: StressWorkloadConfig,
        repetitions: int = 1,
        save_artifacts: bool = True,
    ) -> StressEvaluationResult:
        """Evaluate Titan execution, replay, and recovery behavior under stress/scaling."""
        trials: list[StressTrial] = []
        exec_durations: list[float] = []
        replay_durations: list[float] = []
        goodputs: list[float] = []
        successful_trials = 0

        scenario = config.to_scenario()

        for trial_idx in range(1, repetitions + 1):
            t0 = time.perf_counter()
            exec_status = "COMPLETED"
            recovery_outcome = "CLEAN"
            completed = 0
            failed = 0
            attempts = 0
            retries = 0
            w_failures = 0
            w_replacements = 0
            event_count = 0
            trace_bytes = 0
            replay_valid = False
            replay_dur = 0.0

            try:
                res = run_scenario(scenario)
                wall_dur = time.perf_counter() - t0
                completed = res.metrics.total_completed_unique
                failed = res.metrics.jobs_permanently_failed
                attempts = res.metrics.total_execution_attempts
                retries = res.metrics.total_retries
                w_failures = res.metrics.worker_failures
                w_replacements = res.metrics.jobs_recovered

                trace = res.trace
                if trace is not None:
                    event_count = len(trace)
                    trace_bytes = len(trace.to_json(indent=None).encode("utf-8"))

                    # Replay verification
                    t_rep0 = time.perf_counter()
                    rep_res = ReplayEngine.replay(trace)
                    replay_dur = time.perf_counter() - t_rep0
                    replay_valid = rep_res.valid

                    # Failure analysis for ground-truth classification
                    ana_rep = FailureAnalyzer.analyze(trace)
                    recovery_outcome = ana_rep.overall_status
                else:
                    recovery_outcome = "NO_TRACE"

                if failed == 0 and completed == config.jobs:
                    successful_trials += 1

            except Exception as exc:
                wall_dur = time.perf_counter() - t0
                exec_status = "FAILED"
                recovery_outcome = f"ERROR: {exc}"

            goodput = safe_div(completed, wall_dur)
            exec_durations.append(wall_dur)
            replay_durations.append(replay_dur)
            goodputs.append(goodput)

            trial = StressTrial(
                config_name=config.name,
                category=config.category,
                trial_index=trial_idx,
                workers=config.workers,
                jobs=config.jobs,
                work_units=config.work_units,
                execution_status=exec_status,
                recovery_outcome=recovery_outcome,
                completed_jobs=completed,
                failed_jobs=failed,
                total_attempts=attempts,
                retries=retries,
                worker_failures=w_failures,
                worker_replacements=w_replacements,
                trace_event_count=event_count,
                trace_size_bytes=trace_bytes,
                replay_valid=replay_valid,
                replay_duration_sec=replay_dur,
                wall_clock_duration_sec=wall_dur,
                goodput_jobs_per_sec=goodput,
            )
            trials.append(trial)

        recovery_rate = safe_div(successful_trials, repetitions)

        result = StressEvaluationResult(
            config=config,
            repetitions=repetitions,
            trials=trials,
            execution_duration_stats=MetricStats.compute(exec_durations),
            replay_duration_stats=MetricStats.compute(replay_durations),
            goodput_stats=MetricStats.compute(goodputs),
            successful_trials=successful_trials,
            recovery_rate=recovery_rate,
        )

        if save_artifacts:
            out_dir = self.output_base_dir / "stress"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"stress_{config.name}.json"
            out_file.write_text(result.to_json(indent=2), encoding="utf-8")

        return result

    # -------------------------------------------------------------------------
    # 4. Standard Evaluation Suites
    # -------------------------------------------------------------------------

    def run_overhead_suite(
        self,
        repetitions: int = 3,
        warmup: bool = True,
    ) -> list[TraceOverheadResult]:
        """Execute standard trace overhead progression: Small, Medium, Large."""
        workloads = [
            Scenario(name="overhead-small", num_workers=2, num_jobs=10, work_units=500),
            Scenario(name="overhead-medium", num_workers=2, num_jobs=50, work_units=500),
            Scenario(name="overhead-large", num_workers=4, num_jobs=100, work_units=500),
        ]
        results: list[TraceOverheadResult] = []
        for wl in workloads:
            res = self.run_trace_overhead(wl, repetitions=repetitions, warmup=warmup)
            results.append(res)
        return results

    def run_replay_suite(
        self,
        repetitions: int = 5,
        warmup: bool = True,
    ) -> list[ReplayEvaluationResult]:
        """Execute replay evaluation across clean baseline, single crash, and complex traces."""
        # 1. Baseline trace (TB-A-001)
        tb_a = CorpusRegistry.get("TB-A-001")
        res_a = run_scenario(tb_a.scenario)
        trace_a = res_a.trace or ExecutionTrace()

        # 2. Worker crash / recovery trace (TB-B-001)
        tb_b = CorpusRegistry.get("TB-B-001")
        res_b = run_scenario(tb_b.scenario)
        trace_b = res_b.trace or ExecutionTrace()

        # 3. Repeated failure trace (TB-D-001)
        tb_d = CorpusRegistry.get("TB-D-001")
        res_d = run_scenario(tb_d.scenario)
        trace_d = res_d.trace or ExecutionTrace()

        results = [
            self.run_replay_evaluation(
                trace_a,
                trace_name="tb_a_baseline",
                trace_source="TB-A-001",
                repetitions=repetitions,
                warmup=warmup,
            ),
            self.run_replay_evaluation(
                trace_b,
                trace_name="tb_b_worker_crash",
                trace_source="TB-B-001",
                repetitions=repetitions,
                warmup=warmup,
            ),
            self.run_replay_evaluation(
                trace_d,
                trace_name="tb_d_repeated_failure",
                trace_source="TB-D-001",
                repetitions=repetitions,
                warmup=warmup,
            ),
        ]
        return results

    def run_stress_suite(
        self,
        timeout: float = 30.0,
    ) -> list[StressEvaluationResult]:
        """Execute focused stress evaluation matrix across scaling, failure, and retry pressure."""
        configs = [
            # A. Concurrency & Workload Scaling
            StressWorkloadConfig(
                name="stress-scale-small",
                category="concurrency_scaling",
                workers=2,
                jobs=10,
                work_units=500,
                timeout=timeout,
            ),
            StressWorkloadConfig(
                name="stress-scale-medium",
                category="concurrency_scaling",
                workers=2,
                jobs=50,
                work_units=500,
                timeout=timeout,
            ),
            StressWorkloadConfig(
                name="stress-scale-large",
                category="concurrency_scaling",
                workers=4,
                jobs=100,
                work_units=500,
                timeout=timeout,
            ),
            # B. Single Failure Intensity
            StressWorkloadConfig(
                name="stress-single-failure",
                category="failure_intensity",
                workers=2,
                jobs=20,
                work_units=500,
                fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=3),
                timeout=timeout,
            ),
            # C. Repeated Failure Intensity
            StressWorkloadConfig(
                name="stress-repeated-failure",
                category="failure_intensity",
                workers=4,
                jobs=40,
                work_units=500,
                fault_configs=(
                    FaultConfig(target_worker_id="worker-0", kill_after_jobs=3),
                    FaultConfig(target_worker_id="worker-1", kill_after_jobs=6),
                ),
                timeout=timeout,
            ),
            # D. Retry Pressure / Fail-Fast
            StressWorkloadConfig(
                name="stress-retry-pressure",
                category="retry_pressure",
                workers=2,
                jobs=10,
                work_units=500,
                max_retries=1,  # Limited retry
                fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
                timeout=timeout,
            ),
        ]
        results: list[StressEvaluationResult] = []
        for cfg in configs:
            res = self.run_stress_evaluation(cfg, repetitions=1)
            results.append(res)
        return results

    def run_full_system_evaluation(
        self,
        overhead_repetitions: int = 3,
        replay_repetitions: int = 5,
        save_artifacts: bool = True,
    ) -> SystemEvaluationSuite:
        """Execute full Prompt 10 system evaluation suite: overhead + replay + stress."""
        overhead_res = self.run_overhead_suite(repetitions=overhead_repetitions)
        replay_res = self.run_replay_suite(repetitions=replay_repetitions)
        stress_res = self.run_stress_suite()

        suite = SystemEvaluationSuite(
            timestamp=time.time(),
            platform_info=self.get_platform_info(),
            trace_overhead_results=overhead_res,
            replay_results=replay_res,
            stress_results=stress_res,
        )

        if save_artifacts:
            out_dir = self.output_base_dir / "evaluations"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "system_evaluation_suite.json"
            out_file.write_text(suite.to_json(indent=2), encoding="utf-8")

        return suite
