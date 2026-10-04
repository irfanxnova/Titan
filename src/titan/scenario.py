"""Deterministic scenario and fault-injection definitions for Titan.

Provides explicit, reproducible workload scenarios, deterministic workload generators,
and fault-injection specifications that execute atop the Titan runtime.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from titan.job import Job
from titan.metrics import RunMetrics
from titan.runtime import FailureConfig, StaticRuntime
from titan.trace import ExecutionTrace


@dataclass(frozen=True)
class FaultConfig:
    """Explicit specification for deterministic worker failure injection."""

    target_worker_id: str
    kill_after_jobs: int = 0
    target_job_id: str | None = None

    def validate(self, num_workers: int, total_jobs: int) -> None:
        """Validate fault injection parameters against scenario topology."""
        if not self.target_worker_id or not self.target_worker_id.strip():
            raise ValueError("target_worker_id cannot be empty")

        # Check target worker format and bounds
        normalized = self.target_worker_id.strip()
        if normalized.startswith("worker-"):
            suffix = normalized[len("worker-"):]
            if suffix.isdigit():
                w_idx = int(suffix)
                if w_idx < 0 or w_idx >= num_workers:
                    raise ValueError(
                        f"target_worker_id '{self.target_worker_id}' is out of range for "
                        f"{num_workers} workers (expected worker-0 to worker-{num_workers - 1})"
                    )
        elif normalized.isdigit():
            w_idx = int(normalized)
            if w_idx < 0 or w_idx >= num_workers:
                raise ValueError(
                    f"target_worker_id index '{self.target_worker_id}' is out of range for "
                    f"{num_workers} workers (expected 0 to {num_workers - 1})"
                )

        if self.kill_after_jobs < 0:
            raise ValueError(f"kill_after_jobs cannot be negative, got {self.kill_after_jobs}")

        if total_jobs > 0 and self.kill_after_jobs >= total_jobs:
            raise ValueError(
                f"kill_after_jobs ({self.kill_after_jobs}) must be strictly less than "
                f"total jobs ({total_jobs})"
            )

    def to_failure_config(self) -> FailureConfig:
        """Convert to runtime FailureConfig with normalized worker ID."""
        target_id = (
            self.target_worker_id
            if self.target_worker_id.startswith("worker-")
            else f"worker-{self.target_worker_id}"
        )
        return FailureConfig(
            target_worker_id=target_id,
            kill_after_jobs=self.kill_after_jobs,
            target_job_id=self.target_job_id,
        )


@dataclass(frozen=True)
class Scenario:
    """Deterministic, repeatable workload and fault configuration."""

    name: str
    num_workers: int = 2
    num_jobs: int = 20
    work_units: int = 1000
    pattern: str = "uniform"  # "uniform", "linear", "bimodal"
    seed: int | None = 42
    max_retries: int = 3
    replace_failed_workers: bool = True
    fault_config: FaultConfig | None = None
    fault_configs: tuple[FaultConfig, ...] = ()
    duplicate_jobs: tuple[str, ...] = ()
    timeout: float | None = None
    enable_tracing: bool = True

    @property
    def all_fault_configs(self) -> tuple[FaultConfig, ...]:
        """Aggregate all defined fault injection configurations."""
        configs: list[FaultConfig] = []
        if self.fault_config is not None:
            configs.append(self.fault_config)
        if self.fault_configs:
            configs.extend(self.fault_configs)
        return tuple(configs)

    def validate(self) -> None:
        """Validate scenario configuration prior to execution."""
        if not self.name or not self.name.strip():
            raise ValueError("Scenario name cannot be empty")
        if self.num_workers < 1:
            raise ValueError(f"num_workers must be at least 1, got {self.num_workers}")
        if self.num_jobs < 0:
            raise ValueError(f"num_jobs cannot be negative, got {self.num_jobs}")
        if self.work_units < 1:
            raise ValueError(f"work_units must be at least 1, got {self.work_units}")
        if self.max_retries < 1:
            raise ValueError(f"max_retries must be at least 1, got {self.max_retries}")
        if self.pattern not in ("uniform", "linear", "bimodal"):
            raise ValueError(
                f"Invalid pattern '{self.pattern}'. Allowed: 'uniform', 'linear', 'bimodal'"
            )
        for fc in self.all_fault_configs:
            fc.validate(self.num_workers, self.num_jobs)

    def generate_jobs(self) -> list[Job]:
        """Generate a strictly deterministic sequence of jobs based on configuration and seed."""
        self.validate()
        if self.num_jobs == 0:
            return []

        jobs: list[Job] = []

        if self.pattern == "uniform":
            for i in range(self.num_jobs):
                jobs.append(
                    Job.create(
                        job_id=f"job-{i:06d}",
                        work_units=self.work_units,
                        max_retries=self.max_retries,
                    )
                )
        elif self.pattern == "linear":
            step = max(1, self.work_units // max(1, self.num_jobs))
            for i in range(self.num_jobs):
                units = self.work_units + (i * step)
                jobs.append(
                    Job.create(
                        job_id=f"job-{i:06d}",
                        work_units=max(1, units),
                        max_retries=self.max_retries,
                    )
                )
        elif self.pattern == "bimodal":
            rng = random.Random(self.seed if self.seed is not None else 42)
            for i in range(self.num_jobs):
                is_large = rng.random() > 0.5
                units = self.work_units * 3 if is_large else max(1, self.work_units // 2)
                jobs.append(
                    Job.create(
                        job_id=f"job-{i:06d}",
                        work_units=units,
                        max_retries=self.max_retries,
                    )
                )

        return jobs


@dataclass(frozen=True)
class ScenarioResult:
    """Execution outcome and observability telemetry for a completed scenario."""

    scenario: Scenario
    metrics: RunMetrics
    fault_injected: bool
    fault_target: str | None
    fault_point: int | None
    trace: ExecutionTrace | None = None

    def to_dict(self) -> dict:
        """Serialize scenario result to dictionary."""
        fault_payload = None
        if self.fault_injected and self.scenario.all_fault_configs:
            fc = self.scenario.all_fault_configs[0]
            fault_payload = {
                "enabled": True,
                "target_worker": self.fault_target,
                "kill_after_jobs": self.fault_point,
                "target_job_id": fc.target_job_id,
            }

        return {
            "scenario": {
                "name": self.scenario.name,
                "workers": self.scenario.num_workers,
                "jobs": self.scenario.num_jobs,
                "work_units": self.scenario.work_units,
                "pattern": self.scenario.pattern,
                "seed": self.scenario.seed,
                "max_retries": self.scenario.max_retries,
                "replace_failed_workers": self.scenario.replace_failed_workers,
                "fault": fault_payload,
                "faults": [
                    {
                        "target_worker": fc.target_worker_id,
                        "kill_after_jobs": fc.kill_after_jobs,
                        "target_job_id": fc.target_job_id,
                    }
                    for fc in self.scenario.all_fault_configs
                ]
                if self.scenario.all_fault_configs
                else [],
                "duplicate_jobs": list(self.scenario.duplicate_jobs),
                "enable_tracing": self.scenario.enable_tracing,
            },
            "metrics": self.metrics.to_dict(),
            "trace": self.trace.to_list() if self.trace is not None else [],
        }


def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Execute a deterministic scenario end-to-end using the Titan runtime."""
    scenario.validate()
    jobs = scenario.generate_jobs()

    all_cfgs = scenario.all_fault_configs
    failure_cfg = [fc.to_failure_config() for fc in all_cfgs] if all_cfgs else None

    runtime = StaticRuntime(
        num_workers=scenario.num_workers,
        max_retries=scenario.max_retries,
        replace_failed_workers=scenario.replace_failed_workers,
        failure_config=failure_cfg,
        duplicate_jobs=scenario.duplicate_jobs,
        enable_tracing=scenario.enable_tracing,
    )
    trace = None
    try:
        metrics, _ = runtime.run_workload(jobs, timeout=scenario.timeout)
        trace = runtime.trace
    finally:
        runtime.stop()

    return ScenarioResult(
        scenario=scenario,
        metrics=metrics,
        fault_injected=len(all_cfgs) > 0,
        fault_target=all_cfgs[0].target_worker_id if all_cfgs else None,
        fault_point=all_cfgs[0].kill_after_jobs if all_cfgs else None,
        trace=trace,
    )


# -----------------------------------------------------------------------------
# Predefined Standard Scenarios
# -----------------------------------------------------------------------------

PREDEFINED_SCENARIOS: dict[str, Scenario] = {
    "baseline": Scenario(
        name="baseline",
        num_workers=2,
        num_jobs=20,
        work_units=1000,
        pattern="uniform",
    ),
    "worker-crash": Scenario(
        name="worker-crash",
        num_workers=2,
        num_jobs=20,
        work_units=1000,
        pattern="uniform",
        fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=3),
    ),
    "stress-recovery": Scenario(
        name="stress-recovery",
        num_workers=4,
        num_jobs=50,
        work_units=2000,
        pattern="uniform",
        fault_config=FaultConfig(target_worker_id="worker-1", kill_after_jobs=5),
    ),
}


def get_scenario(name: str) -> Scenario:
    """Lookup a predefined scenario by name."""
    if name not in PREDEFINED_SCENARIOS:
        available = ", ".join(sorted(PREDEFINED_SCENARIOS.keys()))
        raise ValueError(f"Unknown scenario '{name}'. Available scenarios: {available}")
    return PREDEFINED_SCENARIOS[name]
