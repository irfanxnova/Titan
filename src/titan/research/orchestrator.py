"""Master Research Orchestrator for Titan Empirical Evaluations.

Coordinates the complete research evaluation pipeline:
    Plans -> Live Suite Execution -> Raw Artifacts -> Summaries -> Tables -> Figures -> Report -> Verification
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from titan.research.ablations import AblationRunner, AblationStudyResult
from titan.research.environment import EnvironmentMetadata
from titan.research.figures import FigureGenerator
from titan.research.plan import EvaluationPlan, ResearchPlanRegistry
from titan.research.report import ReportGenerator
from titan.research.reproducibility import ReproducibilityReport, verify_reproducibility
from titan.research.suites import (
    E1ReplayFidelityEvaluator,
    E1ReplayFidelityResult,
    E2FailureDiagnosisEvaluator,
    E2FailureDiagnosisResult,
    E3RecoveryPolicyEvaluator,
    E3RecoveryPolicyResult,
    E4TracingOverheadEvaluator,
    E5ReplayCostEvaluator,
    E6FailureComplexityEvaluator,
)
from titan.research.tables import TableGenerator


class ResearchOrchestrator:
    """Master orchestrator executing Titan research evaluations and generating deliverables."""

    def __init__(self, base_dir: str | Path = "research") -> None:
        self.base_dir = Path(base_dir)

    def init_directory_structure(self) -> None:
        """Create standard research package directories."""
        subdirs = [
            "plans",
            "runs",
            "raw",
            "summaries",
            "tables",
            "figures",
            "reports",
        ]
        for sub in subdirs:
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)

    def export_plans(self) -> list[str]:
        """Save all canonical evaluation plans to research/plans/."""
        self.init_directory_structure()
        plans_dir = self.base_dir / "plans"
        saved = []
        for plan in ResearchPlanRegistry.list_all():
            dest = plans_dir / f"{plan.evaluation_id.lower()}.json"
            plan.save(dest)
            saved.append(str(dest))
        return saved

    def run_all(
        self,
        e1_trials: int = 5,
        e2_trials: int = 3,
        e3_trials: int = 2,
        e4_trials: int = 5,
        e5_trials: int = 5,
    ) -> dict[str, Any]:
        """Execute all evaluation suites (E1-E6), run ablations, emit tables/figures, and compile report."""
        self.init_directory_structure()

        # 1. Export canonical plans
        self.export_plans()

        # 2. Capture environment metadata
        env_meta = EnvironmentMetadata.capture()
        runs_dir = self.base_dir / "runs"
        (runs_dir / "run_environment.json").write_text(env_meta.to_json(indent=2), encoding="utf-8")

        # 3. Suite E1: Replay Fidelity (RQ1)
        e1_res = E1ReplayFidelityEvaluator.run(
            repetitions=e1_trials,
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 4. Suite E2: Failure Diagnosis (RQ2)
        e2_res = E2FailureDiagnosisEvaluator.run(
            repetitions=e2_trials,
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 5. Suite E3: Recovery Policies (RQ3, RQ6)
        e3_res = E3RecoveryPolicyEvaluator.run(
            repetitions=e3_trials,
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 6. Suite E4: Tracing Overhead (RQ4)
        e4_res = E4TracingOverheadEvaluator.run(
            repetitions=e4_trials,
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 7. Suite E5: Replay Cost (RQ4, RQ5)
        e5_res = E5ReplayCostEvaluator.run(
            repetitions=e5_trials,
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 8. Suite E6: Failure Complexity & Stress (RQ5)
        e6_res = E6FailureComplexityEvaluator.run(
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 9. Suite E7: Architecture Mechanism Ablations (RQ6)
        ablation_res = AblationRunner.run_all(
            save_artifacts=True,
            output_dir=self.base_dir,
        )

        # 10. Write aggregate summaries
        sum_dir = self.base_dir / "summaries"
        (sum_dir / "e1_fidelity_summary.json").write_text(e1_res.to_json(indent=2), encoding="utf-8")
        (sum_dir / "e2_diagnosis_summary.json").write_text(e2_res.to_json(indent=2), encoding="utf-8")
        (sum_dir / "e3_policies_summary.json").write_text(e3_res.to_json(indent=2), encoding="utf-8")
        (sum_dir / "e4_overhead_summary.json").write_text(
            json.dumps([r.to_dict() for r in e4_res], indent=2), encoding="utf-8"
        )
        (sum_dir / "e5_replay_summary.json").write_text(
            json.dumps([r.to_dict() for r in e5_res], indent=2), encoding="utf-8"
        )
        (sum_dir / "e6_stress_summary.json").write_text(
            json.dumps([r.to_dict() for r in e6_res], indent=2), encoding="utf-8"
        )
        (sum_dir / "ablation_summary.json").write_text(ablation_res.to_json(indent=2), encoding="utf-8")

        # 11. Generate Tables (Table 1 through Table 8 in MD and CSV)
        tables_map = TableGenerator.write_all_tables(
            output_dir=self.base_dir / "tables",
            fidelity_result=e1_res,
            diagnosis_result=e2_res,
            policy_result=e3_res,
            overhead_results=e4_res,
            replay_results=e5_res,
            stress_results=e6_res,
            ablation_result=ablation_res,
        )

        # 12. Render Figures (Figure 1 through Figure 5 in vector SVG)
        figures_map = FigureGenerator.render_all_figures(
            output_dir=self.base_dir / "figures",
            policy_result=e3_res,
            overhead_results=e4_res,
            replay_results=e5_res,
            stress_results=e6_res,
            ablation_result=ablation_res,
        )

        # 13. Compile Markdown Research Report
        report_path = self.base_dir / "reports" / "titan_research_report.md"
        ReportGenerator.generate_report(
            env_meta=env_meta,
            fidelity_res=e1_res,
            diagnosis_res=e2_res,
            policy_res=e3_res,
            overhead_res=e4_res,
            replay_res=e5_res,
            stress_res=e6_res,
            ablation_res=ablation_res,
            output_path=report_path,
        )

        # 14. Run Reproducibility Check
        repro_report = verify_reproducibility(self.base_dir)

        return {
            "environment": env_meta.to_dict(),
            "tables": tables_map,
            "figures": figures_map,
            "report_path": str(report_path),
            "reproducibility": repro_report.to_dict(),
            "e1_fidelity": e1_res.to_dict(),
            "e2_diagnosis": e2_res.to_dict(),
            "e3_policies": e3_res.to_dict(),
            "ablation": ablation_res.to_dict(),
        }
