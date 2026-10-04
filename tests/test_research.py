"""Unit and integration tests for Titan research-grade evaluation layer (Prompt 11).

Tests evaluation plans, baselines, descriptive statistics, normalization,
environment capture, canonical suites (E1-E6), ablations (A1-A5), table generation,
figure generation, research report compilation, and reproducibility verification.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from titan.bench.corpus import CorpusRegistry
from titan.experiment.evaluation import (
    MetricStats,
    ReplayEvaluationResult,
    ReplayEvaluationTrial,
    StressEvaluationResult,
    StressTrial,
    StressWorkloadConfig,
    TraceOverheadResult,
    TraceOverheadTrial,
)
from titan.research.ablations import (
    AblationRecord,
    AblationRunner,
    AblationStudyResult,
)
from titan.research.baselines import (
    BASELINE_REGISTRY,
    BaselineDefinition,
    BaselineId,
)
from titan.research.environment import EnvironmentMetadata, sanitize_path
from titan.research.figures import FigureGenerator
from titan.research.orchestrator import ResearchOrchestrator
from titan.research.plan import EvaluationPlan, ResearchPlanRegistry
from titan.research.report import ReportGenerator
from titan.research.reproducibility import (
    ReproducibilityReport,
    verify_reproducibility,
)
from titan.research.stats import (
    DescriptiveStats,
    compute_normalized_ratio,
    compute_relative_change_pct,
    get_direction_label,
    is_higher_better,
    is_lower_better,
    safe_div,
)
from titan.research.suites import (
    E1ReplayFidelityEvaluator,
    E1ReplayFidelityResult,
    E1TrialRecord,
    E2DiagnosisTrialRecord,
    E2FailureDiagnosisEvaluator,
    E2FailureDiagnosisResult,
    E3RecoveryPolicyEvaluator,
    E3RecoveryPolicyResult,
    PolicyScenarioComparison,
)
from titan.research.tables import TableGenerator


class TestEvaluationPlan(unittest.TestCase):
    """Test EvaluationPlan data model, serialization, and registry."""

    def test_plan_creation_and_validation(self) -> None:
        plan = EvaluationPlan(
            evaluation_id="TEST_PLAN_01",
            research_question="RQ1",
            title="Test Plan Title",
            hypothesis="Test Hypothesis",
            dataset_source="TitanBench",
            scenario_set=["TB-A-001"],
            policies_or_baselines=["BASELINE-B1"],
            independent_variables={"var1": ["a", "b"]},
            controlled_variables={"workers": 2},
            dependent_metrics=["recovery_rate"],
            trial_count=3,
            seed_policy="fixed: 42",
            output_artifact_dir="research/test",
        )
        plan.validate()
        self.assertEqual(plan.evaluation_id, "TEST_PLAN_01")
        self.assertEqual(plan.research_question, "RQ1")
        self.assertEqual(plan.trial_count, 3)

    def test_plan_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            EvaluationPlan(
                evaluation_id="",
                research_question="RQ1",
                title="Title",
                hypothesis="Hypo",
                dataset_source="Src",
                scenario_set=["TB-A-001"],
                policies_or_baselines=[],
                independent_variables={},
                controlled_variables={},
                dependent_metrics=[],
                trial_count=1,
                seed_policy="",
                output_artifact_dir="",
            ).validate()

        with self.assertRaises(ValueError):
            EvaluationPlan(
                evaluation_id="VALID_ID",
                research_question="RQ1",
                title="Title",
                hypothesis="Hypo",
                dataset_source="Src",
                scenario_set=[],  # Empty scenarios
                policies_or_baselines=[],
                independent_variables={},
                controlled_variables={},
                dependent_metrics=[],
                trial_count=1,
                seed_policy="",
                output_artifact_dir="",
            ).validate()

        with self.assertRaises(ValueError):
            EvaluationPlan(
                evaluation_id="VALID_ID",
                research_question="RQ1",
                title="Title",
                hypothesis="Hypo",
                dataset_source="Src",
                scenario_set=["TB-A-001"],
                policies_or_baselines=[],
                independent_variables={},
                controlled_variables={},
                dependent_metrics=[],
                trial_count=0,  # Invalid trial count
                seed_policy="",
                output_artifact_dir="",
            ).validate()

    def test_plan_serialization_round_trip(self) -> None:
        plan = ResearchPlanRegistry.get("E1_REPLAY_FIDELITY")
        plan_dict = plan.to_dict()
        reconstructed = EvaluationPlan.from_dict(plan_dict)
        self.assertEqual(plan.evaluation_id, reconstructed.evaluation_id)
        self.assertEqual(plan.hypothesis, reconstructed.hypothesis)
        self.assertEqual(plan.trial_count, reconstructed.trial_count)

        json_str = plan.to_json()
        from_json_plan = EvaluationPlan.from_json(json_str)
        self.assertEqual(plan.evaluation_id, from_json_plan.evaluation_id)

    def test_plan_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "test_plan.json"
            plan = ResearchPlanRegistry.get("E2_FAILURE_DIAGNOSIS")
            plan.save(file_path)
            self.assertTrue(file_path.exists())

            loaded = EvaluationPlan.load(file_path)
            self.assertEqual(loaded.evaluation_id, "E2_FAILURE_DIAGNOSIS")
            self.assertEqual(loaded.research_question, "RQ2")

    def test_canonical_plans_registry_coverage(self) -> None:
        plans = ResearchPlanRegistry.list_all()
        plan_ids = {p.evaluation_id for p in plans}
        expected = {
            "E1_REPLAY_FIDELITY",
            "E2_FAILURE_DIAGNOSIS",
            "E3_RECOVERY_POLICIES",
            "E4_TRACING_OVERHEAD",
            "E5_REPLAY_COST",
            "E6_FAILURE_COMPLEXITY",
            "E7_SYSTEM_ABLATIONS",
        }
        self.assertTrue(expected.issubset(plan_ids))

        # Check all research questions RQ1-RQ6 are covered
        all_rqs = " ".join(p.research_question for p in plans)
        for rq in ["RQ1", "RQ2", "RQ3", "RQ4", "RQ5", "RQ6"]:
            self.assertIn(rq, all_rqs)


class TestBaselines(unittest.TestCase):
    """Test explicit Baseline definitions and registry."""

    def test_baselines_registered(self) -> None:
        baselines = BASELINE_REGISTRY.list_all()
        base_ids = {b.baseline_id for b in baselines}
        self.assertIn("BASELINE-B0", base_ids)
        self.assertIn("BASELINE-B1", base_ids)
        self.assertIn("BASELINE-B2", base_ids)
        self.assertIn("BASELINE-B3", base_ids)

    def test_baseline_retrieval_and_serialization(self) -> None:
        b0 = BASELINE_REGISTRY.get(BaselineId.B0_NORMAL_EXECUTION.value)
        self.assertFalse(b0.fault_injected)
        self.assertTrue(b0.tracing_enabled)

        b_dict = b0.to_dict()
        b_rec = BaselineDefinition.from_dict(b_dict)
        self.assertEqual(b0.baseline_id, b_rec.baseline_id)

    def test_unknown_baseline_error(self) -> None:
        with self.assertRaises(KeyError):
            BASELINE_REGISTRY.get("BASELINE-UNKNOWN")


class TestStatisticsAndNormalization(unittest.TestCase):
    """Test descriptive statistics and normalization calculations."""

    def test_safe_div(self) -> None:
        self.assertEqual(safe_div(10, 2), 5.0)
        self.assertEqual(safe_div(10, 0), 0.0)
        self.assertEqual(safe_div(10, 0.0, fallback=42.0), 42.0)

    def test_normalization_ratio(self) -> None:
        self.assertAlmostEqual(compute_normalized_ratio(120, 100), 1.2)
        self.assertEqual(compute_normalized_ratio(120, 0), 1.0)

    def test_relative_change_pct(self) -> None:
        self.assertAlmostEqual(compute_relative_change_pct(120, 100), 20.0)
        self.assertAlmostEqual(compute_relative_change_pct(80, 100), -20.0)
        self.assertEqual(compute_relative_change_pct(100, 0), 0.0)

    def test_descriptive_stats_empty(self) -> None:
        s = DescriptiveStats.compute([])
        self.assertEqual(s.n, 0)
        self.assertEqual(s.mean, 0.0)
        self.assertEqual(s.std_dev, 0.0)

    def test_descriptive_stats_single(self) -> None:
        s = DescriptiveStats.compute([42.0])
        self.assertEqual(s.n, 1)
        self.assertEqual(s.mean, 42.0)
        self.assertEqual(s.std_dev, 0.0)
        self.assertIn("undefined", s.sample_note)

    def test_descriptive_stats_multi(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        s = DescriptiveStats.compute(values)
        self.assertEqual(s.n, 5)
        self.assertAlmostEqual(s.mean, 30.0)
        self.assertAlmostEqual(s.median, 30.0)
        self.assertAlmostEqual(s.min, 10.0)
        self.assertAlmostEqual(s.max, 50.0)
        self.assertTrue(s.std_dev > 0)
        self.assertTrue(s.cv > 0)

        # Dictionary round-trip
        s_dict = s.to_dict()
        s_rec = DescriptiveStats.from_dict(s_dict)
        self.assertEqual(s.n, s_rec.n)
        self.assertAlmostEqual(s.mean, s_rec.mean)

    def test_directionality(self) -> None:
        self.assertTrue(is_lower_better("duration_sec"))
        self.assertTrue(is_lower_better("relative_overhead_pct"))
        self.assertTrue(is_higher_better("goodput_jobs_per_sec"))
        self.assertTrue(is_higher_better("recovery_rate"))
        self.assertIn("lower is better", get_direction_label("latency"))
        self.assertIn("higher is better", get_direction_label("throughput"))


class TestEnvironmentCapture(unittest.TestCase):
    """Test reproducibility environment metadata capture."""

    def test_environment_capture(self) -> None:
        env = EnvironmentMetadata.capture()
        self.assertTrue(len(env.titan_version) > 0)
        self.assertTrue(len(env.python_version) > 0)
        self.assertTrue(len(env.os_system) > 0)
        self.assertTrue(env.cpu_count >= 1)

        d = env.to_dict()
        rec = EnvironmentMetadata.from_dict(d)
        self.assertEqual(env.titan_version, rec.titan_version)

    def test_sanitize_path(self) -> None:
        raw_win = r"c:\Users\testuser\Projects\Titan\src\titan\runtime.py"
        sanitized = sanitize_path(raw_win)
        self.assertEqual(sanitized, "src/titan/runtime.py")

        other = r"c:\Users\secretuser\Documents\file.json"
        sanitized_other = sanitize_path(other)
        self.assertNotIn("secretuser", sanitized_other)


class TestCanonicalSuites(unittest.TestCase):
    """Test execution of canonical evaluation suites E1 and E2."""

    def test_e1_replay_fidelity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = E1ReplayFidelityEvaluator.run(
                repetitions=2,
                save_artifacts=True,
                output_dir=tmp_dir,
            )
            self.assertEqual(result.evaluation_id, "E1_REPLAY_FIDELITY")
            self.assertEqual(result.replay_validity_rate, 1.0)
            self.assertEqual(result.trace_equivalence_rate, 1.0)
            self.assertEqual(result.divergence_detection_rate, 1.0)
            self.assertTrue(len(result.trials) > 0)

            # Check trial preservation
            raw_file = Path(tmp_dir) / "raw" / "e1_replay_fidelity" / "e1_fidelity_trials.json"
            self.assertTrue(raw_file.exists())

    def test_e2_failure_diagnosis_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Run on subset of scenarios for fast unit testing
            result = E2FailureDiagnosisEvaluator.run(
                scenario_ids=("TB-A-001", "TB-B-001", "TB-E-001"),
                repetitions=1,
                save_artifacts=True,
                output_dir=tmp_dir,
            )
            self.assertEqual(result.evaluation_id, "E2_FAILURE_DIAGNOSIS")
            self.assertEqual(result.root_class_accuracy, 1.0)
            self.assertEqual(result.affected_entity_accuracy, 1.0)
            self.assertEqual(result.recovery_status_accuracy, 1.0)
            self.assertEqual(result.overall_diagnosis_accuracy, 1.0)

            # Check trial preservation
            raw_file = Path(tmp_dir) / "raw" / "e2_failure_diagnosis" / "e2_diagnosis_trials.json"
            self.assertTrue(raw_file.exists())


class TestAblationStudies(unittest.TestCase):
    """Test ablation data structures and runner."""

    def test_ablation_record_serialization(self) -> None:
        rec = AblationRecord(
            ablation_id="A1",
            mechanism_name="Worker Replacement",
            target_research_question="RQ3",
            scenario_id="TB-B-001",
            baseline_config_name="R0",
            ablated_config_name="R1",
            baseline_config={"replace_failed_workers": True},
            ablated_config={"replace_failed_workers": False},
            primary_metric="goodput",
            baseline_value=100.0,
            ablated_value=80.0,
            delta=-20.0,
            relative_change_pct=-20.0,
            impact_assessment="TRADE_OFF",
            mechanism_contribution="Preserves capacity",
        )
        d = rec.to_dict()
        rec2 = AblationRecord.from_dict(d)
        self.assertEqual(rec.ablation_id, rec2.ablation_id)
        self.assertEqual(rec.relative_change_pct, rec2.relative_change_pct)

    def test_ablation_study_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            study = AblationRunner.run_all(save_artifacts=True, output_dir=tmp_dir)
            self.assertEqual(study.evaluation_id, "E7_SYSTEM_ABLATIONS")
            self.assertEqual(len(study.ablations), 5)
            ablation_ids = [a.ablation_id for a in study.ablations]
            self.assertEqual(ablation_ids, ["A1", "A2", "A3", "A4", "A5"])

            # Verify saved JSON
            ab_file = Path(tmp_dir) / "raw" / "ablations" / "ablation_results.json"
            self.assertTrue(ab_file.exists())


class TestTableAndFigureGeneration(unittest.TestCase):
    """Test table and vector SVG figure generation."""

    def _create_mock_results(self) -> tuple[Any, ...]:
        fid_trials = [
            E1TrialRecord(
                case_name="exact_clean_trace",
                trial_index=1,
                event_count=46,
                trace_bytes=7000,
                replay_valid=True,
                equivalent=True,
                divergence_count=0,
                first_divergence_seq=None,
                first_divergence_cat=None,
                expected_outcome_matched=True,
                notes="",
            )
        ]
        fid_res = E1ReplayFidelityResult(
            evaluation_id="E1_REPLAY_FIDELITY",
            baseline_id="BASELINE-B1",
            total_trials=1,
            replay_validity_rate=1.0,
            trace_equivalence_rate=1.0,
            divergence_detection_rate=1.0,
            divergence_category_counts={},
            trials=fid_trials,
            notes="",
        )

        diag_trials = [
            E2DiagnosisTrialRecord(
                scenario_id="TB-B-001",
                scenario_class="CLASS_B_SINGLE_WORKER_FAILURE",
                trial_index=1,
                expected_root_class="WORKER_FAILURE",
                observed_root_class="WORKER_FAILURE",
                root_class_correct=True,
                expected_affected_entity="worker-0",
                observed_affected_entity="worker-0",
                affected_entity_correct=True,
                expected_recovery_status="RECOVERED",
                observed_recovery_status="RECOVERED",
                recovery_status_correct=True,
                overall_diagnosis_correct=True,
            )
        ]
        diag_res = E2FailureDiagnosisResult(
            evaluation_id="E2_FAILURE_DIAGNOSIS",
            baseline_id="BASELINE-B1",
            scenarios_evaluated=["TB-B-001"],
            total_trials=1,
            root_class_accuracy=1.0,
            affected_entity_accuracy=1.0,
            recovery_status_accuracy=1.0,
            overall_diagnosis_accuracy=1.0,
            trials=diag_trials,
            notes="",
        )

        comp = PolicyScenarioComparison(
            scenario_id="TB-B-001",
            scenario_class="CLASS_B_SINGLE_WORKER_FAILURE",
            baseline_policy="R0",
            candidate_policy="R1",
            baseline_recovery_rate=1.0,
            candidate_recovery_rate=1.0,
            recovery_rate_delta=0.0,
            baseline_goodput=120.0,
            candidate_goodput=110.0,
            goodput_ratio=0.916,
            baseline_retries=1,
            candidate_retries=1,
            retries_delta=0,
            baseline_lost_work=0,
            candidate_lost_work=0,
            lost_work_delta=0,
            baseline_duration_sec=0.15,
            candidate_duration_sec=0.16,
            duration_relative_change_pct=6.67,
        )
        pol_res = E3RecoveryPolicyResult(
            evaluation_id="E3_RECOVERY_POLICIES",
            baseline_id="BASELINE-B1",
            comparisons=[comp],
            raw_results={},
            notes="",
        )

        ovh_tr = TraceOverheadTrial(
            workload_name="overhead-small",
            trial_index=1,
            workers=2,
            jobs=10,
            work_units=500,
            pattern="uniform",
            seed=42,
            no_trace_duration_sec=0.1,
            with_trace_duration_sec=0.11,
            trace_event_count=46,
            trace_size_bytes=7000,
            trace_serialization_time_sec=0.001,
            absolute_overhead_sec=0.01,
            relative_overhead_pct=10.0,
            bytes_per_event=152.0,
            useful_completed_jobs=10,
            total_attempts=10,
            retries=0,
            worker_failures=0,
            worker_replacements=0,
        )
        ovh_res = [
            TraceOverheadResult(
                workload_name="overhead-small",
                workers=2,
                jobs=10,
                work_units=500,
                pattern="uniform",
                repetitions=1,
                trials=[ovh_tr],
                no_trace_duration_stats=MetricStats.compute([0.1]),
                with_trace_duration_stats=MetricStats.compute([0.11]),
                absolute_overhead_stats=MetricStats.compute([0.01]),
                relative_overhead_stats=MetricStats.compute([10.0]),
                event_count=46,
                trace_size_bytes=7000,
                trace_serialization_stats=MetricStats.compute([0.001]),
                bytes_per_event=152.0,
                useful_completed_jobs=10,
                total_attempts=10,
            )
        ]

        rep_tr = ReplayEvaluationTrial(
            trace_name="tb_a_baseline",
            trial_index=1,
            trace_event_count=46,
            trace_size_bytes=7000,
            replay_duration_sec=0.0001,
            replay_events_per_sec=460000.0,
            replay_valid=True,
            validation_error_count=0,
        )
        rep_res = [
            ReplayEvaluationResult(
                trace_name="tb_a_baseline",
                trace_source="TB-A-001",
                trace_event_count=46,
                trace_size_bytes=7000,
                repetitions=1,
                trials=[rep_tr],
                replay_duration_stats=MetricStats.compute([0.0001]),
                replay_throughput_stats=MetricStats.compute([460000.0]),
                replay_valid=True,
                validation_errors=[],
            )
        ]

        stress_cfg = StressWorkloadConfig(
            name="stress-scale-small",
            category="concurrency_scaling",
            workers=2,
            jobs=10,
            work_units=500,
        )
        stress_tr = StressTrial(
            config_name="stress-scale-small",
            category="concurrency_scaling",
            trial_index=1,
            workers=2,
            jobs=10,
            work_units=500,
            execution_status="COMPLETED",
            recovery_outcome="CLEAN",
            completed_jobs=10,
            failed_jobs=0,
            total_attempts=10,
            retries=0,
            worker_failures=0,
            worker_replacements=0,
            trace_event_count=46,
            trace_size_bytes=7000,
            replay_valid=True,
            replay_duration_sec=0.0001,
            wall_clock_duration_sec=0.2,
            goodput_jobs_per_sec=50.0,
        )
        stress_res = [
            StressEvaluationResult(
                config=stress_cfg,
                repetitions=1,
                trials=[stress_tr],
                execution_duration_stats=MetricStats.compute([0.2]),
                replay_duration_stats=MetricStats.compute([0.0001]),
                goodput_stats=MetricStats.compute([50.0]),
                successful_trials=1,
                recovery_rate=1.0,
            )
        ]

        ab_rec = AblationRecord(
            ablation_id="A1",
            mechanism_name="Worker Replacement",
            target_research_question="RQ3",
            scenario_id="TB-B-001",
            baseline_config_name="R0",
            ablated_config_name="R1",
            baseline_config={},
            ablated_config={},
            primary_metric="goodput",
            baseline_value=120.0,
            ablated_value=110.0,
            delta=-10.0,
            relative_change_pct=-8.33,
            impact_assessment="TRADE_OFF",
            mechanism_contribution="Maintains capacity",
        )
        ab_res = AblationStudyResult(
            evaluation_id="E7_SYSTEM_ABLATIONS",
            baseline_id="BASELINE-B1",
            ablations=[ab_rec],
            notes="",
        )

        return fid_res, diag_res, pol_res, ovh_res, rep_res, stress_res, ab_res

    def test_tables_generation(self) -> None:
        fid_res, diag_res, pol_res, ovh_res, rep_res, stress_res, ab_res = self._create_mock_results()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tables_map = TableGenerator.write_all_tables(
                output_dir=tmp_dir,
                fidelity_result=fid_res,
                diagnosis_result=diag_res,
                policy_result=pol_res,
                overhead_results=ovh_res,
                replay_results=rep_res,
                stress_results=stress_res,
                ablation_result=ab_res,
            )
            # 8 tables * 2 formats (md, csv) = 16 files
            self.assertEqual(len(tables_map), 16)
            for path_str in tables_map.values():
                p = Path(path_str)
                self.assertTrue(p.exists())
                self.assertTrue(p.stat().st_size > 0)

    def test_figures_generation(self) -> None:
        fid_res, diag_res, pol_res, ovh_res, rep_res, stress_res, ab_res = self._create_mock_results()

        with tempfile.TemporaryDirectory() as tmp_dir:
            fig_map = FigureGenerator.render_all_figures(
                output_dir=tmp_dir,
                policy_result=pol_res,
                overhead_results=ovh_res,
                replay_results=rep_res,
                stress_results=stress_res,
                ablation_result=ab_res,
            )
            self.assertEqual(len(fig_map), 5)
            for fig_key, path_str in fig_map.items():
                p = Path(path_str)
                self.assertTrue(p.exists())
                svg_content = p.read_text(encoding="utf-8")
                self.assertIn("<svg", svg_content)
                self.assertIn("</svg>", svg_content)
                # Verify raw companion data file exists
                json_p = p.parent / f"{p.stem}_data.json"
                self.assertTrue(json_p.exists())

    def test_report_generation(self) -> None:
        fid_res, diag_res, pol_res, ovh_res, rep_res, stress_res, ab_res = self._create_mock_results()
        env = EnvironmentMetadata.capture()

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_report.md"
            report_str = ReportGenerator.generate_report(
                env_meta=env,
                fidelity_res=fid_res,
                diagnosis_res=diag_res,
                policy_res=pol_res,
                overhead_res=ovh_res,
                replay_res=rep_res,
                stress_res=stress_res,
                ablation_res=ab_res,
                output_path=out_file,
            )
            self.assertTrue(out_file.exists())
            self.assertIn("# Titan Research Evaluation Report", report_str)
            self.assertIn("OBSERVATION", report_str)
            self.assertIn("INTERPRETATION", report_str)
            self.assertIn("LIMITATION", report_str)


class TestReproducibilityValidation(unittest.TestCase):
    """Test automated reproducibility verification routine."""

    def test_reproducibility_on_complete_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = ResearchOrchestrator(base_dir=tmp_dir)
            res = orchestrator.run_all(
                e1_trials=2,
                e2_trials=1,
                e3_trials=1,
                e4_trials=1,
                e5_trials=1,
            )
            repro = res.get("reproducibility", {})
            self.assertTrue(repro.get("verification_passed", False))

            # Directly call verify_reproducibility
            check_rep = verify_reproducibility(tmp_dir)
            self.assertTrue(check_rep.verification_passed)
            self.assertEqual(len(check_rep.plans_verified), 7)
            self.assertEqual(len(check_rep.tables_generated), 16)
            self.assertEqual(len(check_rep.figures_generated), 10)
            self.assertTrue(check_rep.report_generated)


if __name__ == "__main__":
    unittest.main()
