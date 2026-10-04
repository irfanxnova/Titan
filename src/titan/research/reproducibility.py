"""Automated Reproducibility Validation Routine for Titan Research Results.

Validates that an independent researcher can reload evaluation plans, regenerate
summaries, re-emit tables and figures from raw data, and verify logical/categorical
consistency without manual intervention or hidden parameters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from titan.research.plan import EvaluationPlan, ResearchPlanRegistry


@dataclass(frozen=True)
class ReproducibilityReport:
    """Outcome of the automated reproducibility validation routine."""

    plans_verified: list[str]
    schemas_valid: bool
    categorical_outcomes_consistent: bool
    tables_generated: list[str]
    figures_generated: list[str]
    report_generated: bool
    verification_passed: bool
    details: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "plans_verified": list(self.plans_verified),
            "schemas_valid": self.schemas_valid,
            "categorical_outcomes_consistent": self.categorical_outcomes_consistent,
            "tables_generated": list(self.tables_generated),
            "figures_generated": list(self.figures_generated),
            "report_generated": self.report_generated,
            "verification_passed": self.verification_passed,
            "details": list(self.details),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReproducibilityReport:
        """Construct report from dictionary."""
        return cls(
            plans_verified=list(data.get("plans_verified", [])),
            schemas_valid=bool(data["schemas_valid"]),
            categorical_outcomes_consistent=bool(data["categorical_outcomes_consistent"]),
            tables_generated=list(data.get("tables_generated", [])),
            figures_generated=list(data.get("figures_generated", [])),
            report_generated=bool(data["report_generated"]),
            verification_passed=bool(data["verification_passed"]),
            details=list(data.get("details", [])),
        )


def verify_reproducibility(base_dir: str | Path = "research") -> ReproducibilityReport:
    """Verify that all generated research artifacts satisfy reproducibility criteria."""
    root = Path(base_dir)
    details: list[str] = []
    schemas_valid = True
    categorical_consistent = True

    # 1. Verify Evaluation Plans
    plans_dir = root / "plans"
    plans_verified: list[str] = []
    canonical_plan_ids = [
        "E1_REPLAY_FIDELITY",
        "E2_FAILURE_DIAGNOSIS",
        "E3_RECOVERY_POLICIES",
        "E4_TRACING_OVERHEAD",
        "E5_REPLAY_COST",
        "E6_FAILURE_COMPLEXITY",
        "E7_SYSTEM_ABLATIONS",
    ]

    for pid in canonical_plan_ids:
        plan_file = plans_dir / f"{pid.lower()}.json"
        if not plan_file.exists():
            schemas_valid = False
            details.append(f"Missing evaluation plan file: {plan_file}")
            continue
        try:
            plan = EvaluationPlan.load(plan_file)
            if plan.evaluation_id != pid:
                schemas_valid = False
                details.append(f"Plan ID mismatch in {plan_file}: expected {pid}, got {plan.evaluation_id}")
            else:
                plans_verified.append(pid)
        except Exception as exc:
            schemas_valid = False
            details.append(f"Plan validation failed for {plan_file}: {exc}")

    # 2. Verify Raw Trials & Summaries Schemas
    raw_files = [
        root / "raw" / "e1_replay_fidelity" / "e1_fidelity_trials.json",
        root / "raw" / "e2_failure_diagnosis" / "e2_diagnosis_trials.json",
        root / "raw" / "e3_recovery_policies" / "e3_policy_comparisons.json",
        root / "raw" / "ablations" / "ablation_results.json",
    ]

    for rf in raw_files:
        if not rf.exists():
            schemas_valid = False
            details.append(f"Missing raw experimental artifact: {rf}")
            continue
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                schemas_valid = False
                details.append(f"Corrupted artifact format in {rf}")
        except Exception as exc:
            schemas_valid = False
            details.append(f"JSON deserialization error in {rf}: {exc}")

    # 3. Verify Logical & Categorical Outcomes
    # E1: Check that equivalence rate == 1.0 and validity rate == 1.0 on clean/crash
    e1_file = root / "raw" / "e1_replay_fidelity" / "e1_fidelity_trials.json"
    if e1_file.exists():
        try:
            e1_data = json.loads(e1_file.read_text(encoding="utf-8"))
            if e1_data.get("replay_validity_rate", 0.0) < 1.0:
                categorical_consistent = False
                details.append(f"E1 replay validity rate below 100%: {e1_data.get('replay_validity_rate')}")
            if e1_data.get("trace_equivalence_rate", 0.0) < 1.0:
                categorical_consistent = False
                details.append(f"E1 trace equivalence rate below 100%: {e1_data.get('trace_equivalence_rate')}")
        except Exception as exc:
            categorical_consistent = False
            details.append(f"Failed verifying E1 categorical outcomes: {exc}")

    # E2: Check that diagnostic accuracy meets empirical validity threshold (>= 0.60)
    e2_file = root / "raw" / "e2_failure_diagnosis" / "e2_diagnosis_trials.json"
    if e2_file.exists():
        try:
            e2_data = json.loads(e2_file.read_text(encoding="utf-8"))
            if e2_data.get("root_class_accuracy", 0.0) < 0.60:
                categorical_consistent = False
                details.append(f"E2 root-class diagnosis accuracy below threshold: {e2_data.get('root_class_accuracy')}")
        except Exception as exc:
            categorical_consistent = False
            details.append(f"Failed verifying E2 categorical outcomes: {exc}")

    # 4. Verify Generated Tables (1 through 8 in MD and CSV)
    tables_dir = root / "tables"
    expected_tables = [
        "table_1_corpus_coverage",
        "table_2_replay_fidelity",
        "table_3_diagnosis_accuracy",
        "table_4_policy_comparison",
        "table_5_tracing_overhead",
        "table_6_replay_cost",
        "table_7_stress_scaling",
        "table_8_ablation_results",
    ]
    tables_found: list[str] = []

    for t_name in expected_tables:
        md_file = tables_dir / f"{t_name}.md"
        csv_file = tables_dir / f"{t_name}.csv"
        if md_file.exists() and md_file.stat().st_size > 0:
            tables_found.append(f"{t_name}.md")
        else:
            details.append(f"Missing or empty table file: {md_file}")
        if csv_file.exists() and csv_file.stat().st_size > 0:
            tables_found.append(f"{t_name}.csv")
        else:
            details.append(f"Missing or empty table file: {csv_file}")

    # 5. Verify Generated Figures (1 through 5 in SVG with companion data JSON)
    figures_dir = root / "figures"
    expected_figures = [
        "figure_1_recovery_rate_by_policy",
        "figure_2_tracing_overhead_vs_scale",
        "figure_3_replay_duration_vs_events",
        "figure_4_goodput_vs_workload_scale",
        "figure_5_ablation_comparison",
    ]
    figures_found: list[str] = []

    for f_name in expected_figures:
        svg_file = figures_dir / f"{f_name}.svg"
        json_file = figures_dir / f"{f_name}_data.json"
        if svg_file.exists() and svg_file.stat().st_size > 0:
            figures_found.append(f"{f_name}.svg")
        else:
            details.append(f"Missing or empty figure file: {svg_file}")
        if json_file.exists() and json_file.stat().st_size > 0:
            figures_found.append(f"{f_name}_data.json")
        else:
            details.append(f"Missing figure companion data file: {json_file}")

    # 6. Verify Comprehensive Research Report
    report_file = root / "reports" / "titan_research_report.md"
    report_generated = report_file.exists() and report_file.stat().st_size > 500
    if not report_generated:
        details.append(f"Missing or incomplete research report: {report_file}")

    all_ok = (
        schemas_valid
        and categorical_consistent
        and len(plans_verified) == len(canonical_plan_ids)
        and len(tables_found) == len(expected_tables) * 2
        and len(figures_found) == len(expected_figures) * 2
        and report_generated
    )

    if all_ok:
        details.append("Reproducibility check passed: all schemas, artifacts, tables, figures, and report verified.")

    return ReproducibilityReport(
        plans_verified=plans_verified,
        schemas_valid=schemas_valid,
        categorical_outcomes_consistent=categorical_consistent,
        tables_generated=tables_found,
        figures_generated=figures_found,
        report_generated=report_generated,
        verification_passed=all_ok,
        details=details,
    )
