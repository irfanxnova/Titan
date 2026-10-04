"""Evaluation Plan model and registry for research-grade empirical studies in Titan.

Provides a structured, serializable specification for experimental evaluation plans.
A reader can understand what is being tested, why, which variables are controlled,
and how metrics are evaluated without reading implementation code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EvaluationPlan:
    """Rigorous specification of an experimental evaluation plan."""

    evaluation_id: str
    research_question: str
    title: str
    hypothesis: str
    dataset_source: str
    scenario_set: list[str]
    policies_or_baselines: list[str]
    independent_variables: dict[str, Any]
    controlled_variables: dict[str, Any]
    dependent_metrics: list[str]
    trial_count: int
    seed_policy: str
    output_artifact_dir: str
    notes: str = ""

    def validate(self) -> None:
        """Validate evaluation plan integrity."""
        if not self.evaluation_id or not self.evaluation_id.strip():
            raise ValueError("EvaluationPlan evaluation_id cannot be empty")
        if not self.research_question or not self.research_question.strip():
            raise ValueError("EvaluationPlan research_question cannot be empty")
        if not self.title or not self.title.strip():
            raise ValueError("EvaluationPlan title cannot be empty")
        if not self.hypothesis or not self.hypothesis.strip():
            raise ValueError("EvaluationPlan hypothesis cannot be empty")
        if not self.scenario_set:
            raise ValueError("EvaluationPlan scenario_set must contain at least one scenario")
        if self.trial_count < 1:
            raise ValueError(f"EvaluationPlan trial_count must be >= 1, got {self.trial_count}")

    def to_dict(self) -> dict[str, Any]:
        """Convert evaluation plan to dictionary."""
        return {
            "evaluation_id": self.evaluation_id,
            "research_question": self.research_question,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "dataset_source": self.dataset_source,
            "scenario_set": list(self.scenario_set),
            "policies_or_baselines": list(self.policies_or_baselines),
            "independent_variables": dict(self.independent_variables),
            "controlled_variables": dict(self.controlled_variables),
            "dependent_metrics": list(self.dependent_metrics),
            "trial_count": self.trial_count,
            "seed_policy": self.seed_policy,
            "output_artifact_dir": self.output_artifact_dir,
            "notes": self.notes,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize plan to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvaluationPlan:
        """Construct EvaluationPlan from dictionary."""
        plan = cls(
            evaluation_id=str(data["evaluation_id"]),
            research_question=str(data["research_question"]),
            title=str(data["title"]),
            hypothesis=str(data["hypothesis"]),
            dataset_source=str(data["dataset_source"]),
            scenario_set=list(data["scenario_set"]),
            policies_or_baselines=list(data.get("policies_or_baselines", [])),
            independent_variables=dict(data.get("independent_variables", {})),
            controlled_variables=dict(data.get("controlled_variables", {})),
            dependent_metrics=list(data.get("dependent_metrics", [])),
            trial_count=int(data["trial_count"]),
            seed_policy=str(data.get("seed_policy", "deterministic: seed=42")),
            output_artifact_dir=str(data.get("output_artifact_dir", "research")),
            notes=str(data.get("notes", "")),
        )
        plan.validate()
        return plan

    @classmethod
    def from_json(cls, json_str: str) -> EvaluationPlan:
        """Deserialize EvaluationPlan from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def save(self, path: str | Path) -> None:
        """Write evaluation plan to JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> EvaluationPlan:
        """Load evaluation plan from JSON file."""
        content = Path(path).read_text(encoding="utf-8")
        return cls.from_json(content)


class ResearchPlanRegistry:
    """Authoritative registry of canonical evaluation plans for Titan research questions."""

    _registry: dict[str, EvaluationPlan] = {}

    @classmethod
    def register(cls, plan: EvaluationPlan) -> None:
        """Register an evaluation plan ensuring valid configuration and unique ID."""
        plan.validate()
        cls._registry[plan.evaluation_id] = plan

    @classmethod
    def get(cls, evaluation_id: str) -> EvaluationPlan:
        """Retrieve evaluation plan by ID."""
        if evaluation_id not in cls._registry:
            avail = ", ".join(sorted(cls._registry.keys()))
            raise KeyError(f"Unknown evaluation plan '{evaluation_id}'. Available: {avail}")
        return cls._registry[evaluation_id]

    @classmethod
    def list_all(cls) -> list[EvaluationPlan]:
        """Return all registered evaluation plans sorted by evaluation ID."""
        return [cls._registry[k] for k in sorted(cls._registry.keys())]

    @classmethod
    def clear(cls) -> None:
        """Clear registry."""
        cls._registry.clear()

    @classmethod
    def initialize_canonical_plans(cls) -> None:
        """Register the authoritative canonical evaluation plans."""
        cls.clear()

        # E1: Replay Fidelity (RQ1)
        cls.register(
            EvaluationPlan(
                evaluation_id="E1_REPLAY_FIDELITY",
                research_question="RQ1",
                title="Deterministic Replay Equivalence and Divergence Localization",
                hypothesis="Under identical execution inputs and recorded traces, deterministic replay reconstructs identical logical states with 100% equivalence, while synthetic divergences are localized to the exact sequence, category, and entity.",
                dataset_source="Titan Canonical Execution Traces (Clean, Single Crash, Multi-Crash)",
                scenario_set=["TB-A-001", "TB-B-001", "TB-D-001"],
                policies_or_baselines=["BASELINE-B1"],
                independent_variables={
                    "trace_condition": ["clean_trace", "worker_crash_trace", "repeated_failure_trace", "tampered_divergence_trace", "malformed_trace"],
                },
                controlled_variables={
                    "replay_engine": "titan.replay.ReplayEngine",
                    "fidelity_engine": "titan.replay.ReplayFidelityEngine",
                    "divergence_detector": "titan.replay.TraceDivergenceDetector",
                },
                dependent_metrics=[
                    "replay_validity_rate",
                    "trace_equivalence_rate",
                    "divergence_detection_rate",
                    "first_divergence_consistency",
                    "divergence_category_counts",
                ],
                trial_count=5,
                seed_policy="fixed: seed=42 across all runs",
                output_artifact_dir="research/raw/e1_replay_fidelity",
                notes="Tests exact state reconstruction, corruption detection, and divergence localization.",
            )
        )

        # E2: Failure Diagnosis Accuracy (RQ2)
        cls.register(
            EvaluationPlan(
                evaluation_id="E2_FAILURE_DIAGNOSIS",
                research_question="RQ2",
                title="Automated Failure Classification and Root-Cause Localization Accuracy",
                hypothesis="Structured event traces analyzed via Titan's FailureAnalyzer correctly identify injected ground-truth root causes, affected entities, and recovery outcomes without human subjective inspection.",
                dataset_source="TitanBench Canonical Failure Corpus (Classes A, B, C, D, E, G)",
                scenario_set=["TB-A-001", "TB-B-001", "TB-C-001", "TB-D-001", "TB-E-001", "TB-G-001"],
                policies_or_baselines=["BASELINE-B1"],
                independent_variables={
                    "failure_scenario": ["baseline_clean", "single_worker_crash", "in_flight_crash", "repeated_worker_crash", "retry_exhaustion", "capacity_loss"],
                },
                controlled_variables={
                    "failure_analyzer": "titan.analysis.FailureAnalyzer",
                    "ground_truth_oracle": "titan.bench.corpus.ExpectedBehavior",
                },
                dependent_metrics=[
                    "root_class_classification_accuracy",
                    "affected_entity_localization_accuracy",
                    "recovery_status_assessment_accuracy",
                    "diagnosis_consistency_across_trials",
                ],
                trial_count=3,
                seed_policy="deterministic: seed=42",
                output_artifact_dir="research/raw/e2_failure_diagnosis",
                notes="Evaluates diagnostic correctness against known injected ground-truth failures.",
            )
        )

        # E3: Recovery Policy Comparison (RQ3 & RQ6)
        cls.register(
            EvaluationPlan(
                evaluation_id="E3_RECOVERY_POLICIES",
                research_question="RQ3, RQ6",
                title="Comparative Empirical Evaluation of Recovery Policies under Controlled Failures",
                hypothesis="Dynamic worker replacement and bounded retries (Policy R0) maintain 100% completed goodput under worker crashes, whereas disabling replacement (R1) degrades capacity and restricting retries (R2) yields unrecovered failures.",
                dataset_source="TitanBench Canonical Scenarios",
                scenario_set=["TB-B-001", "TB-C-001", "TB-D-001", "TB-E-001", "TB-G-001"],
                policies_or_baselines=["BASELINE-B1", "BASELINE-B3"],
                independent_variables={
                    "recovery_policy": ["R0 (baseline-full-recovery)", "R1 (no-worker-replacement)", "R2 (limited-retry)", "R3 (minimal-recovery)"],
                },
                controlled_variables={
                    "workload_jobs": "scenario-defined",
                    "worker_processes": "scenario-defined",
                    "work_units_per_job": 500,
                    "seed": 42,
                    "fault_injection_timing": "identical per scenario",
                },
                dependent_metrics=[
                    "recovery_rate",
                    "unrecovered_failure_rate",
                    "total_execution_attempts",
                    "retries_initiated",
                    "lost_work_attempts",
                    "duplicate_work_ignored",
                    "goodput_jobs_per_sec",
                    "wall_clock_duration_sec",
                    "recovery_duration_sec",
                ],
                trial_count=3,
                seed_policy="fixed: seed=42 across all policies",
                output_artifact_dir="research/raw/e3_recovery_policies",
                notes="Fair comparison holding all non-policy variables strictly constant.",
            )
        )

        # E4: Tracing Overhead (RQ4)
        cls.register(
            EvaluationPlan(
                evaluation_id="E4_TRACING_OVERHEAD",
                research_question="RQ4",
                title="Runtime and Disk Overhead of Deterministic Structured Tracing",
                hypothesis="Structured event tracing introduces bounded wall-clock overhead (<20% on multi-job batches) while generating compact chronological JSON logs with strict linear scaling per lifecycle event.",
                dataset_source="Standard Scaled Workload Matrix",
                scenario_set=["overhead-small", "overhead-medium", "overhead-large"],
                policies_or_baselines=["BASELINE-B0", "BASELINE-B2"],
                independent_variables={
                    "tracing_mode": ["no_trace (BASELINE-B2)", "with_trace (Mode B)"],
                    "workload_scale": ["small (10 jobs, 2 workers)", "medium (50 jobs, 2 workers)", "large (100 jobs, 4 workers)"],
                },
                controlled_variables={
                    "work_units": 500,
                    "pattern": "uniform",
                    "seed": 42,
                    "failure_injection": "none",
                },
                dependent_metrics=[
                    "no_trace_duration_sec",
                    "with_trace_duration_sec",
                    "absolute_overhead_sec",
                    "relative_overhead_pct",
                    "trace_event_count",
                    "trace_size_bytes",
                    "bytes_per_event",
                ],
                trial_count=5,
                seed_policy="fixed: seed=42, 5 repeated trials with warm-up run",
                output_artifact_dir="research/raw/e4_tracing_overhead",
                notes="Measures instrumentation runtime penalty and byte footprint.",
            )
        )

        # E5: Replay Cost & Performance (RQ4, RQ5)
        cls.register(
            EvaluationPlan(
                evaluation_id="E5_REPLAY_COST",
                research_question="RQ4, RQ5",
                title="Deterministic Replay Execution Duration and Throughput Scaling",
                hypothesis="Offline trace replay processes lifecycle events in sub-millisecond durations with throughput exceeding 200,000 events/sec, scaling linearly with trace length.",
                dataset_source="Execution Traces from Clean, Crash, and Repeated Crash Scenarios",
                scenario_set=["tb_a_baseline", "tb_b_worker_crash", "tb_d_repeated_failure"],
                policies_or_baselines=["BASELINE-B1"],
                independent_variables={
                    "trace_size_and_complexity": ["clean_trace (46 events)", "worker_crash_trace (53 events)", "repeated_failure_trace (82 events)"],
                },
                controlled_variables={
                    "replay_engine": "titan.replay.ReplayEngine",
                    "validation_mode": "strict",
                },
                dependent_metrics=[
                    "trace_event_count",
                    "trace_size_bytes",
                    "replay_duration_sec",
                    "replay_events_per_sec",
                    "replay_validity",
                ],
                trial_count=5,
                seed_policy="deterministic offline replay (no external randomness)",
                output_artifact_dir="research/raw/e5_replay_cost",
                notes="Quantifies offline verification speed and computational scalability.",
            )
        )

        # E6: Failure Complexity & System Stress (RQ5)
        cls.register(
            EvaluationPlan(
                evaluation_id="E6_FAILURE_COMPLEXITY",
                research_question="RQ5",
                title="System Stress, Concurrency Scaling, and Failure Intensity Matrix",
                hypothesis="The coordinator maintains job invariants and safe recovery across scaling worker counts (2 to 4), job counts (10 to 100), and multiple sequential worker crashes without deadlocks.",
                dataset_source="Stress & Scaling Workload Matrix",
                scenario_set=[
                    "stress-scale-small",
                    "stress-scale-medium",
                    "stress-scale-large",
                    "stress-single-failure",
                    "stress-repeated-failure",
                    "stress-retry-pressure",
                ],
                policies_or_baselines=["BASELINE-B1"],
                independent_variables={
                    "dimension": ["concurrency_scaling", "workload_scaling", "failure_intensity", "retry_pressure"],
                },
                controlled_variables={
                    "timeout_seconds": 30.0,
                    "seed": 42,
                    "work_units": 500,
                },
                dependent_metrics=[
                    "execution_status",
                    "recovery_outcome",
                    "completed_jobs",
                    "failed_jobs",
                    "total_attempts",
                    "retries",
                    "worker_failures",
                    "worker_replacements",
                    "goodput_jobs_per_sec",
                    "wall_clock_duration_sec",
                    "replay_valid",
                ],
                trial_count=1,
                seed_policy="deterministic: seed=42",
                output_artifact_dir="research/raw/e6_failure_complexity",
                notes="Bounds system behavior under concurrency and sequential fault stress.",
            )
        )

        # E7: System Mechanism Ablation Study (RQ6)
        cls.register(
            EvaluationPlan(
                evaluation_id="E7_SYSTEM_ABLATIONS",
                research_question="RQ6",
                title="Systematic Mechanism Ablation: Quantifying the Impact of Titan Architecture Components",
                hypothesis="Ablating core mechanisms (worker replacement, retry budget, deterministic tracing, replay validation) measurably changes recovery outcomes, throughput, or diagnostic auditability.",
                dataset_source="TitanBench Controlled Scenarios & Synthetic Workloads",
                scenario_set=["TB-B-001", "TB-D-001", "TB-E-001", "overhead-medium"],
                policies_or_baselines=["BASELINE-B1"],
                independent_variables={
                    "ablated_mechanism": [
                        "A1: No Worker Replacement (replace_failed_workers=False)",
                        "A2: Limited Retries (max_retries=1)",
                        "A3: No Deterministic Tracing (enable_tracing=False)",
                        "A4: Relaxed Replay Verification (no invariant state checking)",
                        "A5: Alternative Fail-Fast Recovery (Policy R3)",
                    ],
                },
                controlled_variables={
                    "scenario_workload": "held identical per ablation pair",
                    "fault_injection": "held identical per ablation pair",
                    "seed": 42,
                },
                dependent_metrics=[
                    "recovery_rate_delta",
                    "attempt_overhead_delta",
                    "duration_delta_sec",
                    "diagnostic_fidelity_loss",
                ],
                trial_count=3,
                seed_policy="fixed: seed=42",
                output_artifact_dir="research/raw/e7_ablations",
                notes="Answers 'Which Titan mechanisms actually matter?' under controlled comparison.",
            )
        )


# Initialize canonical plans at import time
ResearchPlanRegistry.initialize_canonical_plans()
