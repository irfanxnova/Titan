"""Automated Table Generation for Titan Research Evaluations.

Generates human-readable Markdown and machine-readable CSV tables from recorded empirical data:
- Table 1: TitanBench Corpus Coverage
- Table 2: Replay Fidelity & Divergence Detection (RQ1)
- Table 3: Failure Classification Accuracy against Injected Ground Truth (RQ2)
- Table 4: Recovery Policy Comparison (RQ3, RQ6)
- Table 5: Tracing Instrumentation Overhead (RQ4)
- Table 6: Deterministic Replay Cost & Throughput (RQ4, RQ5)
- Table 7: Stress & Scaling Behavior (RQ5)
- Table 8: Mechanism Ablation Results (RQ6)
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Sequence

from titan.bench.corpus import CorpusRegistry
from titan.experiment.evaluation import (
    ReplayEvaluationResult,
    StressEvaluationResult,
    TraceOverheadResult,
)
from titan.research.ablations import AblationStudyResult
from titan.research.suites import (
    E1ReplayFidelityResult,
    E2FailureDiagnosisResult,
    E3RecoveryPolicyResult,
)


class TableGenerator:
    """Generates standardized Markdown and CSV tables directly from experimental results."""

    @staticmethod
    def _csv_from_rows(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        """Helper to render CSV text."""
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    @staticmethod
    def _md_from_rows(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        """Helper to render Markdown table text."""
        col_count = len(headers)
        lines = []
        lines.append("| " + " | ".join(str(h) for h in headers) + " |")
        lines.append("| " + " | ".join([":---"] + [":---:" for _ in range(col_count - 1)]) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        return "\n".join(lines) + "\n"

    # -------------------------------------------------------------------------
    # TABLE 1: TitanBench Corpus Coverage
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_1_corpus(cls) -> tuple[str, str]:
        """Generate Table 1: TitanBench Corpus Coverage (Markdown, CSV)."""
        headers = [
            "Scenario ID",
            "Scenario Name",
            "Class",
            "Workers",
            "Jobs",
            "Fault Injection",
            "Max Retries",
            "Expected Outcome",
            "Expected Root Class",
        ]
        scenarios = CorpusRegistry.list_all()
        rows = []
        for s in scenarios:
            has_fault = "Active" if (s.scenario.fault_config or s.scenario.fault_configs) else "None"
            exp_rec = s.expected_behavior.expected_overall_status or "CLEAN"
            exp_root = s.expected_behavior.expected_root_class or "None"
            sc_name = s.scenario_class.value if hasattr(s.scenario_class, "value") else str(s.scenario_class)
            rows.append(
                [
                    s.scenario_id,
                    s.name,
                    sc_name,
                    s.scenario.num_workers,
                    s.scenario.num_jobs,
                    has_fault,
                    s.scenario.max_retries,
                    exp_rec,
                    exp_root,
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 2: Replay Fidelity (RQ1)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_2_fidelity(cls, result: E1ReplayFidelityResult) -> tuple[str, str]:
        """Generate Table 2: Replay Fidelity & Divergence Detection (Markdown, CSV)."""
        headers = [
            "Evaluation Case",
            "Trials (N)",
            "Events",
            "Trace (KB)",
            "Replay Valid (%)",
            "Equivalence (%)",
            "Divergences",
            "First Divergence Category",
            "Result Assessment",
        ]
        # Group trials by case_name
        grouped: dict[str, list[Any]] = {}
        for t in result.trials:
            grouped.setdefault(t.case_name, []).append(t)

        rows = []
        for case, trials in grouped.items():
            n = len(trials)
            evs = trials[0].event_count
            kb = round(trials[0].trace_bytes / 1024.0, 2)
            valid_pct = round(sum(1 for t in trials if t.replay_valid) / n * 100.0, 1)
            equiv_pct = round(sum(1 for t in trials if t.equivalent) / n * 100.0, 1)
            div_count = sum(t.divergence_count for t in trials)
            first_cat = trials[0].first_divergence_cat or "None (Identical)"
            matched_pct = round(sum(1 for t in trials if t.expected_outcome_matched) / n * 100.0, 1)
            status = "VERIFIED (100%)" if matched_pct == 100.0 else f"PARTIAL ({matched_pct}%)"
            rows.append([case, n, evs, f"{kb:.2f} KB", f"{valid_pct:.1f}%", f"{equiv_pct:.1f}%", div_count, first_cat, status])

        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 3: Failure Diagnosis Accuracy (RQ2)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_3_diagnosis(cls, result: E2FailureDiagnosisResult) -> tuple[str, str]:
        """Generate Table 3: Failure Classification Accuracy against Injected Ground Truth (Markdown, CSV)."""
        headers = [
            "Scenario ID",
            "Scenario Class",
            "Injected Fault (Ground Truth)",
            "Expected Root Class",
            "Observed Root Class",
            "Root Class Match",
            "Entity Match",
            "Recovery Assessment Match",
            "Overall Diagnostic Match",
        ]
        # Group by scenario_id
        grouped: dict[str, list[Any]] = {}
        for t in result.trials:
            grouped.setdefault(t.scenario_id, []).append(t)

        rows = []
        for sid, trials in grouped.items():
            t0 = trials[0]
            root_ok = all(t.root_class_correct for t in trials)
            ent_ok = all(t.affected_entity_correct for t in trials)
            rec_ok = all(t.recovery_status_correct for t in trials)
            overall_ok = all(t.overall_diagnosis_correct for t in trials)

            gt_desc = t0.expected_affected_entity or "Clean / None"
            rows.append(
                [
                    sid,
                    t0.scenario_class,
                    gt_desc,
                    t0.expected_root_class or "None (Clean)",
                    t0.observed_root_class or "None (Clean)",
                    "100% (PASS)" if root_ok else "FAIL",
                    "100% (PASS)" if ent_ok else "FAIL",
                    "100% (PASS)" if rec_ok else "FAIL",
                    "100% (PASS)" if overall_ok else "FAIL",
                ]
            )

        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 4: Recovery Policy Comparison (RQ3, RQ6)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_4_recovery_policies(cls, result: E3RecoveryPolicyResult) -> tuple[str, str]:
        """Generate Table 4: Recovery Policy Comparison (Markdown, CSV)."""
        headers = [
            "Scenario ID",
            "Class",
            "Baseline (B1: R0)",
            "Candidate Policy",
            "Base Recovery (%)",
            "Cand Recovery (%)",
            "Recovery Delta",
            "Base Goodput (j/s)",
            "Cand Goodput (j/s)",
            "Retries Delta",
            "Lost Work Delta",
            "Duration Change (%)",
        ]
        rows = []
        for c in result.comparisons:
            dur_pct_str = f"{c.duration_relative_change_pct:+.1f}%"
            rows.append(
                [
                    c.scenario_id,
                    c.scenario_class,
                    c.baseline_policy,
                    c.candidate_policy,
                    f"{c.baseline_recovery_rate * 100:.0f}%",
                    f"{c.candidate_recovery_rate * 100:.0f}%",
                    f"{c.recovery_rate_delta * 100:+.0f}%",
                    f"{c.baseline_goodput:.1f}",
                    f"{c.candidate_goodput:.1f}",
                    f"{c.retries_delta:+d}",
                    f"{c.lost_work_delta:+d}",
                    dur_pct_str,
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 5: Tracing Overhead (RQ4)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_5_tracing_overhead(cls, results: Sequence[TraceOverheadResult]) -> tuple[str, str]:
        """Generate Table 5: Tracing Overhead (Markdown, CSV)."""
        headers = [
            "Workload",
            "Workers",
            "Jobs",
            "Event Count",
            "Trace Size (KB)",
            "Bytes/Event",
            "No-Trace Mean (s)",
            "With-Trace Mean (s)",
            "Absolute Overhead (s)",
            "Relative Overhead (%)",
        ]
        rows = []
        for r in results:
            kb = round(r.trace_size_bytes / 1024.0, 2)
            no_mean = r.no_trace_duration_stats.mean
            with_mean = r.with_trace_duration_stats.mean
            abs_ovh = r.absolute_overhead_stats.mean
            rel_ovh = r.relative_overhead_stats.mean
            rows.append(
                [
                    r.workload_name,
                    r.workers,
                    r.jobs,
                    r.event_count,
                    f"{kb:.2f} KB",
                    f"{r.bytes_per_event:.1f}",
                    f"{no_mean:.4f} s",
                    f"{with_mean:.4f} s",
                    f"{abs_ovh:+.4f} s",
                    f"{rel_ovh:+.2f}%",
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 6: Replay Cost & Scalability (RQ4, RQ5)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_6_replay_cost(cls, results: Sequence[ReplayEvaluationResult]) -> tuple[str, str]:
        """Generate Table 6: Replay Cost & Event Throughput (Markdown, CSV)."""
        headers = [
            "Trace Name",
            "Source Scenario",
            "Event Count",
            "Trace Size (KB)",
            "Replay Duration Mean (s)",
            "Replay Throughput (ev/s)",
            "Replay Valid",
        ]
        rows = []
        for r in results:
            kb = round(r.trace_size_bytes / 1024.0, 2)
            dur_mean = r.replay_duration_stats.mean
            thru_mean = r.replay_throughput_stats.mean
            rows.append(
                [
                    r.trace_name,
                    r.trace_source,
                    r.trace_event_count,
                    f"{kb:.2f} KB",
                    f"{dur_mean:.6f} s",
                    f"{thru_mean:,.0f} ev/s",
                    "YES (VALID)" if r.replay_valid else "NO (INVALID)",
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 7: Stress & Scaling Behavior (RQ5)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_7_stress_scaling(cls, results: Sequence[StressEvaluationResult]) -> tuple[str, str]:
        """Generate Table 7: Stress & Scaling Matrix (Markdown, CSV)."""
        headers = [
            "Configuration",
            "Category",
            "Workers",
            "Jobs",
            "Execution Status",
            "Recovery Outcome",
            "Duration Mean (s)",
            "Goodput Mean (j/s)",
            "Recovery Rate (%)",
        ]
        rows = []
        for r in results:
            dur_mean = r.execution_duration_stats.mean
            goodput_mean = r.goodput_stats.mean
            rec_rate = r.recovery_rate * 100.0
            rows.append(
                [
                    r.config.name,
                    r.config.category,
                    r.config.workers,
                    r.config.jobs,
                    r.trials[0].execution_status if r.trials else "COMPLETED",
                    r.trials[0].recovery_outcome if r.trials else "CLEAN",
                    f"{dur_mean:.4f} s",
                    f"{goodput_mean:.1f}",
                    f"{rec_rate:.0f}%",
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # TABLE 8: Ablation Results (RQ6)
    # -------------------------------------------------------------------------

    @classmethod
    def generate_table_8_ablations(cls, result: AblationStudyResult) -> tuple[str, str]:
        """Generate Table 8: Architecture Mechanism Ablations (Markdown, CSV)."""
        headers = [
            "Ablation ID",
            "Mechanism Name",
            "Scenario",
            "Baseline Config",
            "Ablated Config",
            "Primary Metric",
            "Baseline",
            "Ablated",
            "Delta",
            "Change (%)",
            "Impact Assessment",
        ]
        rows = []
        for a in result.ablations:
            rows.append(
                [
                    a.ablation_id,
                    a.mechanism_name,
                    a.scenario_id,
                    a.baseline_config_name,
                    a.ablated_config_name,
                    a.primary_metric,
                    f"{a.baseline_value:.4f}",
                    f"{a.ablated_value:.4f}",
                    f"{a.delta:+.4f}",
                    f"{a.relative_change_pct:+.2f}%",
                    a.impact_assessment,
                ]
            )
        return cls._md_from_rows(headers, rows), cls._csv_from_rows(headers, rows)

    # -------------------------------------------------------------------------
    # Orchestrator Table Writer
    # -------------------------------------------------------------------------

    @classmethod
    def write_all_tables(
        cls,
        output_dir: str | Path,
        fidelity_result: E1ReplayFidelityResult,
        diagnosis_result: E2FailureDiagnosisResult,
        policy_result: E3RecoveryPolicyResult,
        overhead_results: Sequence[TraceOverheadResult],
        replay_results: Sequence[ReplayEvaluationResult],
        stress_results: Sequence[StressEvaluationResult],
        ablation_result: AblationStudyResult,
    ) -> dict[str, str]:
        """Generate and write all 8 tables to output directory in both Markdown and CSV formats."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        table_files: dict[str, str] = {}

        tables_data = [
            ("table_1_corpus_coverage", cls.generate_table_1_corpus()),
            ("table_2_replay_fidelity", cls.generate_table_2_fidelity(fidelity_result)),
            ("table_3_diagnosis_accuracy", cls.generate_table_3_diagnosis(diagnosis_result)),
            ("table_4_policy_comparison", cls.generate_table_4_recovery_policies(policy_result)),
            ("table_5_tracing_overhead", cls.generate_table_5_tracing_overhead(overhead_results)),
            ("table_6_replay_cost", cls.generate_table_6_replay_cost(replay_results)),
            ("table_7_stress_scaling", cls.generate_table_7_stress_scaling(stress_results)),
            ("table_8_ablation_results", cls.generate_table_8_ablations(ablation_result)),
        ]

        for base_name, (md_content, csv_content) in tables_data:
            md_path = target_dir / f"{base_name}.md"
            csv_path = target_dir / f"{base_name}.csv"
            md_path.write_text(md_content, encoding="utf-8")
            csv_path.write_text(csv_content, encoding="utf-8")
            table_files[f"{base_name}_md"] = str(md_path)
            table_files[f"{base_name}_csv"] = str(csv_path)

        return table_files
