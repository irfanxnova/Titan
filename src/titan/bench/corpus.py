"""TitanBench canonical failure corpus and scenario specifications.

Defines the structured benchmark scenario model, oracle expected behaviors,
canonical scenario classes (A through I), and the benchmark corpus registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from titan.analysis import AnalysisReport, FailureClass, RecoveryOutcome
from titan.metrics import RunMetrics
from titan.replay import ReplayResult
from titan.scenario import FaultConfig, Scenario


class ScenarioClass(str, Enum):
    """Categorical classification of failure scenarios in TitanBench."""

    CLASS_A_BASELINE = "CLASS_A_BASELINE"
    CLASS_B_SINGLE_WORKER_FAILURE = "CLASS_B_SINGLE_WORKER_FAILURE"
    CLASS_C_IN_FLIGHT_FAILURE = "CLASS_C_IN_FLIGHT_FAILURE"
    CLASS_D_REPEATED_FAILURE = "CLASS_D_REPEATED_FAILURE"
    CLASS_E_RETRY_PRESSURE = "CLASS_E_RETRY_PRESSURE"
    CLASS_F_DUPLICATE_STALE = "CLASS_F_DUPLICATE_STALE"
    CLASS_G_CAPACITY_LOSS = "CLASS_G_CAPACITY_LOSS"
    CLASS_H_ADVERSARIAL_TIMING = "CLASS_H_ADVERSARIAL_TIMING"
    CLASS_I_LARGE_WORKLOAD = "CLASS_I_LARGE_WORKLOAD"


@dataclass(frozen=True)
class ExpectedBehavior:
    """Explicit deterministic oracle assertions for a benchmark scenario."""

    expected_replay_valid: bool = True
    expected_run_state: str = "COMPLETED"
    expected_overall_status: str | None = None  # "CLEAN", "RECOVERED", "UNRECOVERED"
    expected_root_failures: int | None = None
    expected_root_class: str | None = None
    expected_recovery_outcome: str | None = None
    expected_worker_failures: int | None = None
    expected_worker_replacements: int | None = None
    min_retries: int = 0
    max_retries: int | None = None
    expected_completed_jobs: int | None = None
    expected_failed_jobs: int = 0
    expected_duplicate_ignored: int = 0

    def evaluate(
        self,
        metrics: RunMetrics,
        replay_res: ReplayResult,
        analysis_rep: AnalysisReport,
    ) -> tuple[bool, str]:
        """Evaluate observed execution, replay, and analysis against expected assertions.

        Returns:
            Tuple of (passed: bool, reason: str).
        """
        reasons: list[str] = []

        # 1. Replay validity
        if replay_res.valid != self.expected_replay_valid:
            reasons.append(
                f"Replay valid mismatch: expected {self.expected_replay_valid}, got {replay_res.valid} "
                f"(errors: {replay_res.validation_errors})"
            )

        # 2. Overall run state
        if (
            self.expected_run_state
            and analysis_rep.reconstructed_run_state != self.expected_run_state
        ):
            reasons.append(
                f"Run state mismatch: expected {self.expected_run_state}, got {analysis_rep.reconstructed_run_state}"
            )

        # 3. Overall failure analysis status (CLEAN, RECOVERED, UNRECOVERED)
        if (
            self.expected_overall_status is not None
            and analysis_rep.overall_status != self.expected_overall_status
        ):
            reasons.append(
                f"Overall status mismatch: expected {self.expected_overall_status}, got {analysis_rep.overall_status}"
            )

        # 4. Root failure count
        if (
            self.expected_root_failures is not None
            and analysis_rep.root_failures_count != self.expected_root_failures
        ):
            reasons.append(
                f"Root failure count mismatch: expected {self.expected_root_failures}, got {analysis_rep.root_failures_count}"
            )

        # 5. Root failure classification
        if self.expected_root_class is not None:
            if not analysis_rep.root_failures:
                reasons.append(
                    f"Root failure class expected {self.expected_root_class}, but no root failures found"
                )
            else:
                first_root = analysis_rep.root_failures[0]
                rf_class = (
                    first_root.failure_class.value
                    if isinstance(first_root.failure_class, Enum)
                    else str(first_root.failure_class)
                )
                if rf_class != self.expected_root_class:
                    reasons.append(
                        f"Root failure class mismatch: expected {self.expected_root_class}, got {rf_class}"
                    )

        # 6. Recovery outcome
        if self.expected_recovery_outcome is not None:
            if not analysis_rep.root_failures:
                reasons.append(
                    f"Recovery outcome expected {self.expected_recovery_outcome}, but no root failures found"
                )
            else:
                first_root = analysis_rep.root_failures[0]
                rec_val = (
                    first_root.recovery_outcome.value
                    if isinstance(first_root.recovery_outcome, Enum)
                    else str(first_root.recovery_outcome)
                )
                if rec_val != self.expected_recovery_outcome:
                    reasons.append(
                        f"Recovery outcome mismatch: expected {self.expected_recovery_outcome}, got {rec_val}"
                    )

        # 7. Worker failures detected
        if (
            self.expected_worker_failures is not None
            and metrics.worker_failures != self.expected_worker_failures
        ):
            reasons.append(
                f"Worker failures mismatch: expected {self.expected_worker_failures}, got {metrics.worker_failures}"
            )

        # 8. Worker replacements
        if (
            self.expected_worker_replacements is not None
            and replay_res.worker_replacements != self.expected_worker_replacements
        ):
            reasons.append(
                f"Worker replacements mismatch: expected {self.expected_worker_replacements}, got {replay_res.worker_replacements}"
            )

        # 9. Retries bounds
        if metrics.total_retries < self.min_retries:
            reasons.append(
                f"Retries below minimum: expected >= {self.min_retries}, got {metrics.total_retries}"
            )
        if (
            self.max_retries is not None
            and metrics.total_retries > self.max_retries
        ):
            reasons.append(
                f"Retries exceeded maximum: expected <= {self.max_retries}, got {metrics.total_retries}"
            )

        # 10. Completed jobs
        if (
            self.expected_completed_jobs is not None
            and metrics.total_completed_unique != self.expected_completed_jobs
        ):
            reasons.append(
                f"Completed jobs mismatch: expected {self.expected_completed_jobs}, got {metrics.total_completed_unique}"
            )

        # 11. Permanently failed jobs
        if metrics.jobs_permanently_failed != self.expected_failed_jobs:
            reasons.append(
                f"Permanently failed jobs mismatch: expected {self.expected_failed_jobs}, got {metrics.jobs_permanently_failed}"
            )

        # 12. Duplicate results ignored
        if metrics.duplicate_results_ignored != self.expected_duplicate_ignored:
            reasons.append(
                f"Duplicate results ignored mismatch: expected {self.expected_duplicate_ignored}, got {metrics.duplicate_results_ignored}"
            )

        if reasons:
            return False, "; ".join(reasons)
        return True, "All oracle expectations satisfied"

    def to_dict(self) -> dict[str, Any]:
        """Serialize expected behavior to dictionary."""
        return {
            "expected_replay_valid": self.expected_replay_valid,
            "expected_run_state": self.expected_run_state,
            "expected_overall_status": self.expected_overall_status,
            "expected_root_failures": self.expected_root_failures,
            "expected_root_class": self.expected_root_class,
            "expected_recovery_outcome": self.expected_recovery_outcome,
            "expected_worker_failures": self.expected_worker_failures,
            "expected_worker_replacements": self.expected_worker_replacements,
            "min_retries": self.min_retries,
            "max_retries": self.max_retries,
            "expected_completed_jobs": self.expected_completed_jobs,
            "expected_failed_jobs": self.expected_failed_jobs,
            "expected_duplicate_ignored": self.expected_duplicate_ignored,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedBehavior:
        """Construct ExpectedBehavior from dictionary."""
        return cls(
            expected_replay_valid=data.get("expected_replay_valid", True),
            expected_run_state=data.get("expected_run_state", "COMPLETED"),
            expected_overall_status=data.get("expected_overall_status"),
            expected_root_failures=data.get("expected_root_failures"),
            expected_root_class=data.get("expected_root_class"),
            expected_recovery_outcome=data.get("expected_recovery_outcome"),
            expected_worker_failures=data.get("expected_worker_failures"),
            expected_worker_replacements=data.get("expected_worker_replacements"),
            min_retries=int(data.get("min_retries", 0)),
            max_retries=data.get("max_retries"),
            expected_completed_jobs=data.get("expected_completed_jobs"),
            expected_failed_jobs=int(data.get("expected_failed_jobs", 0)),
            expected_duplicate_ignored=int(data.get("expected_duplicate_ignored", 0)),
        )


@dataclass(frozen=True)
class BenchmarkScenario:
    """Explicit, versioned failure scenario in the TitanBench corpus.

    Combines metadata, category classification, and deterministic oracle assertions
    with an authoritative Titan Scenario specification.
    """

    scenario_id: str
    name: str
    scenario_class: ScenarioClass
    description: str
    scenario: Scenario
    expected_behavior: ExpectedBehavior

    def validate(self) -> None:
        """Validate benchmark scenario integrity and configuration."""
        if not self.scenario_id or not self.scenario_id.strip():
            raise ValueError("Scenario ID cannot be empty")
        if not self.name or not self.name.strip():
            raise ValueError("Scenario name cannot be empty")
        self.scenario.validate()

    def to_dict(self) -> dict[str, Any]:
        """Serialize benchmark scenario to dictionary representation."""
        faults_payload = [
            {
                "target_worker": fc.target_worker_id,
                "kill_after_jobs": fc.kill_after_jobs,
                "target_job_id": fc.target_job_id,
            }
            for fc in self.scenario.all_fault_configs
        ]
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "scenario_class": (
                self.scenario_class.value
                if isinstance(self.scenario_class, ScenarioClass)
                else str(self.scenario_class)
            ),
            "description": self.description,
            "scenario": {
                "name": self.scenario.name,
                "num_workers": self.scenario.num_workers,
                "num_jobs": self.scenario.num_jobs,
                "work_units": self.scenario.work_units,
                "pattern": self.scenario.pattern,
                "seed": self.scenario.seed,
                "max_retries": self.scenario.max_retries,
                "replace_failed_workers": self.scenario.replace_failed_workers,
                "faults": faults_payload,
                "duplicate_jobs": list(self.scenario.duplicate_jobs),
                "timeout": self.scenario.timeout,
            },
            "expected_behavior": self.expected_behavior.to_dict(),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize benchmark scenario to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkScenario:
        """Construct BenchmarkScenario from dictionary."""
        sdata = data["scenario"]
        faults_data = sdata.get("faults", [])
        fault_configs = tuple(
            FaultConfig(
                target_worker_id=f["target_worker"],
                kill_after_jobs=f.get("kill_after_jobs", 0),
                target_job_id=f.get("target_job_id"),
            )
            for f in faults_data
        )

        scenario = Scenario(
            name=sdata["name"],
            num_workers=int(sdata.get("num_workers", 2)),
            num_jobs=int(sdata.get("num_jobs", 20)),
            work_units=int(sdata.get("work_units", 1000)),
            pattern=sdata.get("pattern", "uniform"),
            seed=sdata.get("seed", 42),
            max_retries=int(sdata.get("max_retries", 3)),
            replace_failed_workers=bool(sdata.get("replace_failed_workers", True)),
            fault_configs=fault_configs,
            duplicate_jobs=tuple(sdata.get("duplicate_jobs", ())),
            timeout=sdata.get("timeout"),
        )

        sclass_val = data["scenario_class"]
        sclass = (
            ScenarioClass(sclass_val)
            if sclass_val in ScenarioClass._value2member_map_
            else ScenarioClass[sclass_val]
        )

        return cls(
            scenario_id=data["scenario_id"],
            name=data["name"],
            scenario_class=sclass,
            description=data.get("description", ""),
            scenario=scenario,
            expected_behavior=ExpectedBehavior.from_dict(data.get("expected_behavior", {})),
        )


class CorpusRegistry:
    """Registry and query catalog for canonical TitanBench scenarios."""

    _registry: dict[str, BenchmarkScenario] = {}

    @classmethod
    def register(cls, scenario: BenchmarkScenario) -> None:
        """Register a benchmark scenario ensuring ID uniqueness and validity."""
        scenario.validate()
        if scenario.scenario_id in cls._registry:
            raise ValueError(f"Duplicate scenario ID '{scenario.scenario_id}' already registered")
        cls._registry[scenario.scenario_id] = scenario

    @classmethod
    def get(cls, scenario_id: str) -> BenchmarkScenario:
        """Retrieve a registered benchmark scenario by stable ID."""
        if scenario_id not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise KeyError(f"Unknown benchmark scenario ID '{scenario_id}'. Available: {available}")
        return cls._registry[scenario_id]

    @classmethod
    def list_all(cls) -> list[BenchmarkScenario]:
        """Return all registered benchmark scenarios ordered by ID."""
        return [cls._registry[k] for k in sorted(cls._registry.keys())]

    @classmethod
    def list_by_class(cls, scenario_class: ScenarioClass) -> list[BenchmarkScenario]:
        """Filter registered benchmark scenarios by category class."""
        return [
            s for s in cls.list_all()
            if s.scenario_class == scenario_class
        ]

    @classmethod
    def clear(cls) -> None:
        """Clear the registry (primarily for test isolation)."""
        cls._registry.clear()

    @classmethod
    def initialize_canonical_corpus(cls) -> None:
        """Populate the registry with the authoritative canonical TitanBench scenarios."""
        cls.clear()

        # CLASS A — BASELINE
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-A-001",
                name="baseline-normal-execution",
                scenario_class=ScenarioClass.CLASS_A_BASELINE,
                description="Baseline workload execution without faults; normal deterministic completion.",
                scenario=Scenario(
                    name="tb-baseline",
                    num_workers=2,
                    num_jobs=10,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="CLEAN",
                    expected_root_failures=0,
                    expected_worker_failures=0,
                    expected_worker_replacements=0,
                    min_retries=0,
                    max_retries=0,
                    expected_completed_jobs=10,
                    expected_failed_jobs=0,
                    expected_duplicate_ignored=0,
                ),
            )
        )

        # CLASS B — SINGLE WORKER FAILURE
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-B-001",
                name="single-worker-failure-recovery",
                scenario_class=ScenarioClass.CLASS_B_SINGLE_WORKER_FAILURE,
                description="Controlled failure of one worker process with replacement and full job recovery.",
                scenario=Scenario(
                    name="tb-single-worker-fail",
                    num_workers=2,
                    num_jobs=10,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                    replace_failed_workers=True,
                    fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="RECOVERED",
                    expected_root_failures=1,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="RECOVERED",
                    expected_worker_failures=1,
                    expected_worker_replacements=1,
                    min_retries=1,
                    expected_completed_jobs=10,
                    expected_failed_jobs=0,
                ),
            )
        )

        # CLASS C — IN-FLIGHT FAILURE
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-C-001",
                name="in-flight-worker-failure",
                scenario_class=ScenarioClass.CLASS_C_IN_FLIGHT_FAILURE,
                description="Worker terminates mid-execution while an attempt is in-flight; verifies lost attempt tracking and recovery.",
                scenario=Scenario(
                    name="tb-in-flight-fail",
                    num_workers=2,
                    num_jobs=8,
                    work_units=1000,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                    replace_failed_workers=True,
                    fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=1),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="RECOVERED",
                    expected_root_failures=1,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="RECOVERED",
                    expected_worker_failures=1,
                    expected_worker_replacements=1,
                    min_retries=1,
                    expected_completed_jobs=8,
                    expected_failed_jobs=0,
                ),
            )
        )

        # CLASS D — REPEATED FAILURE
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-D-001",
                name="repeated-sequential-failures",
                scenario_class=ScenarioClass.CLASS_D_REPEATED_FAILURE,
                description="Multiple controlled sequential worker failures across distinct worker processes with cumulative recovery.",
                scenario=Scenario(
                    name="tb-repeated-fail",
                    num_workers=3,
                    num_jobs=15,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                    replace_failed_workers=True,
                    fault_configs=(
                        FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
                        FaultConfig(target_worker_id="worker-1", kill_after_jobs=4),
                    ),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="RECOVERED",
                    expected_root_failures=2,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="RECOVERED",
                    expected_worker_failures=2,
                    expected_worker_replacements=2,
                    min_retries=2,
                    expected_completed_jobs=15,
                    expected_failed_jobs=0,
                ),
            )
        )

        # CLASS E — RETRY PRESSURE (EXPECTED UNRECOVERED RETRY EXHAUSTION)
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-E-001",
                name="retry-pressure-exhaustion",
                scenario_class=ScenarioClass.CLASS_E_RETRY_PRESSURE,
                description="Worker failure under max_retries=1 causing retry exhaustion and unrecovered job failure.",
                scenario=Scenario(
                    name="tb-retry-exhaustion",
                    num_workers=2,
                    num_jobs=6,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=1,
                    replace_failed_workers=True,
                    fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=1),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="UNRECOVERED",
                    expected_root_failures=1,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="UNRECOVERED",
                    expected_worker_failures=1,
                    expected_worker_replacements=1,
                    expected_completed_jobs=5,
                    expected_failed_jobs=1,
                ),
            )
        )

        # CLASS F — DUPLICATE / STALE COMPLETION
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-F-001",
                name="duplicate-result-suppression",
                scenario_class=ScenarioClass.CLASS_F_DUPLICATE_STALE,
                description="Simulates arrival of duplicate completed job results to verify coordinator deduplication and suppression.",
                scenario=Scenario(
                    name="tb-duplicate-suppression",
                    num_workers=2,
                    num_jobs=10,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    duplicate_jobs=("job-000000", "job-000001"),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="CLEAN",
                    expected_root_failures=0,
                    expected_worker_failures=0,
                    expected_completed_jobs=10,
                    expected_failed_jobs=0,
                    expected_duplicate_ignored=2,
                ),
            )
        )

        # CLASS G — WORKER CAPACITY LOSS
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-G-001",
                name="unreplaced-worker-capacity-loss",
                scenario_class=ScenarioClass.CLASS_G_CAPACITY_LOSS,
                description="Worker failure without replacement (replace_failed_workers=False); degraded pool completes workload.",
                scenario=Scenario(
                    name="tb-capacity-loss",
                    num_workers=2,
                    num_jobs=10,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                    replace_failed_workers=False,
                    fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=2),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="RECOVERED",
                    expected_root_failures=1,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="RECOVERED",
                    expected_worker_failures=1,
                    expected_worker_replacements=0,
                    min_retries=1,
                    expected_completed_jobs=10,
                    expected_failed_jobs=0,
                ),
            )
        )

        # CLASS H — ADVERSARIAL STATE-TIMING
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-H-001",
                name="adversarial-first-job-kill",
                scenario_class=ScenarioClass.CLASS_H_ADVERSARIAL_TIMING,
                description="Adversarial failure injected immediately on first job acquisition (kill_after_jobs=0) at lifecycle boundary.",
                scenario=Scenario(
                    name="tb-adversarial-timing",
                    num_workers=2,
                    num_jobs=8,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                    replace_failed_workers=True,
                    fault_config=FaultConfig(target_worker_id="worker-0", kill_after_jobs=0),
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="RECOVERED",
                    expected_root_failures=1,
                    expected_root_class="WORKER_FAILURE",
                    expected_recovery_outcome="RECOVERED",
                    expected_worker_failures=1,
                    expected_worker_replacements=1,
                    min_retries=1,
                    expected_completed_jobs=8,
                    expected_failed_jobs=0,
                ),
            )
        )

        # CLASS I — LARGE WORKLOAD
        cls.register(
            BenchmarkScenario(
                scenario_id="TB-I-001",
                name="large-scale-baseline-workload",
                scenario_class=ScenarioClass.CLASS_I_LARGE_WORKLOAD,
                description="Higher worker concurrency (4 workers) and higher job count (40 jobs) deterministic benchmark run.",
                scenario=Scenario(
                    name="tb-large-workload",
                    num_workers=4,
                    num_jobs=40,
                    work_units=500,
                    pattern="uniform",
                    seed=42,
                    max_retries=3,
                ),
                expected_behavior=ExpectedBehavior(
                    expected_replay_valid=True,
                    expected_run_state="COMPLETED",
                    expected_overall_status="CLEAN",
                    expected_root_failures=0,
                    expected_worker_failures=0,
                    expected_worker_replacements=0,
                    min_retries=0,
                    max_retries=0,
                    expected_completed_jobs=40,
                    expected_failed_jobs=0,
                ),
            )
        )


# Automatically initialize the canonical corpus upon module import
CorpusRegistry.initialize_canonical_corpus()
