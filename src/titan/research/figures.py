"""Publication-Grade Vector SVG Figure Generation for Titan Research.

Generates five clean, accessible, publication-ready SVG figures directly from
machine-readable empirical measurements with zero external plotting dependencies:
- Figure 1: Recovery Rate by Policy across Failure Scenarios (RQ3, RQ6)
- Figure 2: Tracing Instrumentation Overhead vs. Workload Scale (RQ4)
- Figure 3: Replay Duration & Throughput vs. Trace Event Count (RQ4, RQ5)
- Figure 4: Goodput Performance Scaling under Concurrency (RQ5)
- Figure 5: Architecture Ablation Impact (RQ6)

Every generated figure preserves its underlying raw data in a companion JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from titan.experiment.evaluation import (
    ReplayEvaluationResult,
    StressEvaluationResult,
    TraceOverheadResult,
)
from titan.research.ablations import AblationStudyResult
from titan.research.suites import E3RecoveryPolicyResult


# Shared Publication-Style SVG Palette (ACM/IEEE compliant, colorblind-safe)
PALETTE = {
    "bg": "#ffffff",
    "border": "#e2e8f0",
    "text_dark": "#1e293b",
    "text_muted": "#64748b",
    "grid": "#f1f5f9",
    "axis": "#94a3b8",
    "primary": "#2563eb",     # Deep royal blue
    "secondary": "#0d9488",   # Teal
    "accent": "#e11d48",      # Crimson / Coral
    "warning": "#d97706",     # Amber
    "neutral": "#64748b",     # Slate
    "bar_base": "#3b82f6",
    "bar_alt": "#f97316",
}


class FigureGenerator:
    """Renders crisp, publication-quality vector SVG charts directly from empirical data."""

    # -------------------------------------------------------------------------
    # FIGURE 1: Recovery Rate by Policy across Failure Scenarios
    # -------------------------------------------------------------------------

    @classmethod
    def generate_figure_1_recovery_rate(
        cls,
        result: E3RecoveryPolicyResult,
        output_path: Path,
    ) -> None:
        """Render Figure 1: Recovery Rate by Policy across representative scenarios."""
        comparisons = result.comparisons
        raw_data = [c.to_dict() for c in comparisons]
        (output_path.parent / f"{output_path.stem}_data.json").write_text(
            json.dumps(raw_data, indent=2), encoding="utf-8"
        )

        width, height = 760, 420
        margin_left, margin_right = 70, 40
        margin_top, margin_bottom = 60, 80
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        scenarios = [c.scenario_id for c in comparisons]
        n_groups = len(scenarios)
        group_w = plot_w / max(1, n_groups)

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">')
        svg.append(f'<rect width="{width}" height="{height}" fill="{PALETTE["bg"]}" rx="6"/>')

        # Title & Subtitle
        svg.append(f'<text x="{width/2}" y="28" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="{PALETTE["text_dark"]}">FIGURE 1: Job Recovery Rate by Policy Across Failure Scenarios (RQ3, RQ6)</text>')
        svg.append(f'<text x="{width/2}" y="46" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_muted"]}">Comparison of Resilient Baseline (Policy R0) vs Degraded/Constrained Policies (R1/R2)</text>')

        # Y-Grid (0% to 100%)
        for pct in range(0, 101, 25):
            y = margin_top + plot_h - (pct / 100.0 * plot_h)
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="{PALETTE["grid"]}" stroke-width="1.5"/>')
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">{pct}%</text>')

        # Axis Lines
        svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')
        svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')

        # Grouped Bars
        bar_w = min(28.0, (group_w - 20) / 2.0)
        for i, c in enumerate(comparisons):
            gx = margin_left + i * group_w
            cx = gx + group_w / 2.0

            # Baseline Bar (R0)
            b_val = c.baseline_recovery_rate * 100.0
            b_h = (b_val / 100.0) * plot_h
            bx = cx - bar_w - 3
            by = margin_top + plot_h - b_h
            svg.append(f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{b_h}" fill="{PALETTE["primary"]}" rx="3"/>')
            svg.append(f'<text x="{bx + bar_w/2}" y="{by - 6}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="{PALETTE["text_dark"]}">{b_val:.0f}%</text>')

            # Candidate Bar
            c_val = c.candidate_recovery_rate * 100.0
            c_h = (c_val / 100.0) * plot_h
            cand_x = cx + 3
            cand_y = margin_top + plot_h - c_h
            cand_color = PALETTE["secondary"] if c.candidate_policy == "R1" else PALETTE["bar_alt"]
            svg.append(f'<rect x="{cand_x}" y="{cand_y}" width="{bar_w}" height="{c_h}" fill="{cand_color}" rx="3"/>')
            svg.append(f'<text x="{cand_x + bar_w/2}" y="{cand_y - 6}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="{cand_color}">{c_val:.0f}%</text>')

            # X-Label
            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 18}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="{PALETTE["text_dark"]}">{c.scenario_id}</text>')
            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 32}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" fill="{PALETTE["text_muted"]}">vs {c.candidate_policy}</text>')

        # Legend
        leg_y = height - 18
        svg.append(f'<rect x="{width/2 - 190}" y="{leg_y - 10}" width="12" height="12" fill="{PALETTE["primary"]}" rx="2"/>')
        svg.append(f'<text x="{width/2 - 172}" y="{leg_y}" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">Policy R0 (Full Recovery)</text>')
        svg.append(f'<rect x="{width/2 - 20}" y="{leg_y - 10}" width="12" height="12" fill="{PALETTE["secondary"]}" rx="2"/>')
        svg.append(f'<text x="{width/2 - 2}" y="{leg_y}" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">Policy R1 (No Replacement)</text>')
        svg.append(f'<rect x="{width/2 + 160}" y="{leg_y - 10}" width="12" height="12" fill="{PALETTE["bar_alt"]}" rx="2"/>')
        svg.append(f'<text x="{width/2 + 178}" y="{leg_y}" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">Policy R2 (Limited Retry)</text>')

        svg.append('</svg>')
        output_path.write_text("\n".join(svg), encoding="utf-8")

    # -------------------------------------------------------------------------
    # FIGURE 2: Tracing Overhead vs. Workload Scale
    # -------------------------------------------------------------------------

    @classmethod
    def generate_figure_2_tracing_overhead(
        cls,
        results: Sequence[TraceOverheadResult],
        output_path: Path,
    ) -> None:
        """Render Figure 2: Wall-Clock Duration & Tracing Overhead vs Workload Scale."""
        raw_data = [r.to_dict() for r in results]
        (output_path.parent / f"{output_path.stem}_data.json").write_text(
            json.dumps(raw_data, indent=2), encoding="utf-8"
        )

        width, height = 740, 420
        margin_left, margin_right = 80, 50
        margin_top, margin_bottom = 60, 80
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">')
        svg.append(f'<rect width="{width}" height="{height}" fill="{PALETTE["bg"]}" rx="6"/>')

        svg.append(f'<text x="{width/2}" y="28" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="{PALETTE["text_dark"]}">FIGURE 2: Tracing Instrumentation Overhead vs. Workload Scale (RQ4)</text>')
        svg.append(f'<text x="{width/2}" y="46" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_muted"]}">Execution Wall-Clock Time (s) with Tracing Disabled vs. Active</text>')

        # Determine max time
        max_dur = max(
            [r.with_trace_duration_stats.mean for r in results]
            + [r.no_trace_duration_stats.mean for r in results]
            + [1.5]
        ) * 1.2

        # Y-Grid
        ticks = 5
        for t in range(ticks + 1):
            val = (max_dur / ticks) * t
            y = margin_top + plot_h - (val / max_dur * plot_h)
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="{PALETTE["grid"]}" stroke-width="1.5"/>')
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">{val:.2f} s</text>')

        svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')
        svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')

        group_w = plot_w / max(1, len(results))
        bar_w = min(36.0, (group_w - 30) / 2.0)

        for i, r in enumerate(results):
            cx = margin_left + i * group_w + group_w / 2.0

            # No-Trace bar
            no_mean = r.no_trace_duration_stats.mean
            no_h = (no_mean / max_dur) * plot_h
            no_x = cx - bar_w - 4
            no_y = margin_top + plot_h - no_h
            svg.append(f'<rect x="{no_x}" y="{no_y}" width="{bar_w}" height="{no_h}" fill="{PALETTE["neutral"]}" rx="3"/>')
            svg.append(f'<text x="{no_x + bar_w/2}" y="{no_y - 6}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="{PALETTE["text_muted"]}">{no_mean:.2f}s</text>')

            # With-Trace bar
            with_mean = r.with_trace_duration_stats.mean
            with_h = (with_mean / max_dur) * plot_h
            with_x = cx + 4
            with_y = margin_top + plot_h - with_h
            svg.append(f'<rect x="{with_x}" y="{with_y}" width="{bar_w}" height="{with_h}" fill="{PALETTE["primary"]}" rx="3"/>')
            svg.append(f'<text x="{with_x + bar_w/2}" y="{with_y - 6}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="{PALETTE["primary"]}">{with_mean:.2f}s</text>')

            # Overhead badge
            rel_ovh = r.relative_overhead_stats.mean
            badge_text = f"+{rel_ovh:.1f}%" if rel_ovh >= 0 else f"{rel_ovh:.1f}%"
            svg.append(f'<text x="{cx}" y="{min(no_y, with_y) - 20}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="700" fill="{PALETTE["accent"]}">{badge_text}</text>')

            # X-Label
            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 18}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="{PALETTE["text_dark"]}">{r.workload_name}</text>')
            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 32}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" fill="{PALETTE["text_muted"]}">{r.jobs} jobs ({r.workers}w)</text>')

        # Legend
        leg_y = height - 18
        svg.append(f'<rect x="{width/2 - 120}" y="{leg_y - 10}" width="12" height="12" fill="{PALETTE["neutral"]}" rx="2"/>')
        svg.append(f'<text x="{width/2 - 102}" y="{leg_y}" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">No-Trace Baseline (Mode A)</text>')
        svg.append(f'<rect x="{width/2 + 50}" y="{leg_y - 10}" width="12" height="12" fill="{PALETTE["primary"]}" rx="2"/>')
        svg.append(f'<text x="{width/2 + 68}" y="{leg_y}" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">With-Trace Active (Mode B)</text>')

        svg.append('</svg>')
        output_path.write_text("\n".join(svg), encoding="utf-8")

    # -------------------------------------------------------------------------
    # FIGURE 3: Replay Duration vs Trace Event Count
    # -------------------------------------------------------------------------

    @classmethod
    def generate_figure_3_replay_cost(
        cls,
        results: Sequence[ReplayEvaluationResult],
        output_path: Path,
    ) -> None:
        """Render Figure 3: Deterministic Replay Duration vs. Event Count."""
        raw_data = [r.to_dict() for r in results]
        (output_path.parent / f"{output_path.stem}_data.json").write_text(
            json.dumps(raw_data, indent=2), encoding="utf-8"
        )

        width, height = 740, 420
        margin_left, margin_right = 80, 50
        margin_top, margin_bottom = 60, 70
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">')
        svg.append(f'<rect width="{width}" height="{height}" fill="{PALETTE["bg"]}" rx="6"/>')

        svg.append(f'<text x="{width/2}" y="28" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="{PALETTE["text_dark"]}">FIGURE 3: Deterministic Replay Duration vs. Event Scale (RQ4, RQ5)</text>')
        svg.append(f'<text x="{width/2}" y="46" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_muted"]}">Sub-millisecond Replay Reconstruction Across Canonical Traces</text>')

        # Max values
        max_events = max([r.trace_event_count for r in results] + [100]) * 1.2
        # Use milliseconds for readability
        max_dur_ms = max([r.replay_duration_stats.mean * 1000.0 for r in results] + [0.5]) * 1.3

        # Y-Grid (ms)
        ticks = 5
        for t in range(ticks + 1):
            val = (max_dur_ms / ticks) * t
            y = margin_top + plot_h - (val / max_dur_ms * plot_h)
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="{PALETTE["grid"]}" stroke-width="1.5"/>')
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">{val:.2f} ms</text>')

        # X-Axis Ticks
        for ev in range(0, int(max_events) + 1, 20):
            x = margin_left + (ev / max_events * plot_w)
            svg.append(f'<line x1="{x}" y1="{margin_top + plot_h}" x2="{x}" y2="{margin_top + plot_h + 5}" stroke="{PALETTE["axis"]}" stroke-width="1"/>')
            svg.append(f'<text x="{x}" y="{margin_top + plot_h + 18}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">{ev}</text>')

        svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')
        svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')

        # Connect points with line
        pts = []
        for r in sorted(results, key=lambda x: x.trace_event_count):
            px = margin_left + (r.trace_event_count / max_events * plot_w)
            py = margin_top + plot_h - ((r.replay_duration_stats.mean * 1000.0) / max_dur_ms * plot_h)
            pts.append((px, py, r))

        if len(pts) > 1:
            line_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y, _ in pts)
            svg.append(f'<path d="{line_d}" fill="none" stroke="{PALETTE["primary"]}" stroke-width="2.5" stroke-dasharray="4,4"/>')

        for px, py, r in pts:
            thru = r.replay_throughput_stats.mean
            dur_ms = r.replay_duration_stats.mean * 1000.0
            svg.append(f'<circle cx="{px}" cy="{py}" r="6" fill="{PALETTE["secondary"]}" stroke="{PALETTE["bg"]}" stroke-width="2"/>')
            svg.append(f'<text x="{px}" y="{py - 12}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="{PALETTE["text_dark"]}">{dur_ms:.3f} ms</text>')
            svg.append(f'<text x="{px}" y="{py + 22}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" fill="{PALETTE["text_muted"]}">{r.trace_name} ({thru:,.0f} ev/s)</text>')

        svg.append(f'<text x="{width/2}" y="{height - 15}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_dark"]}">Trace Event Count (Chronological Events)</text>')
        svg.append('</svg>')
        output_path.write_text("\n".join(svg), encoding="utf-8")

    # -------------------------------------------------------------------------
    # FIGURE 4: Goodput Performance Scaling under Concurrency
    # -------------------------------------------------------------------------

    @classmethod
    def generate_figure_4_goodput_scaling(
        cls,
        results: Sequence[StressEvaluationResult],
        output_path: Path,
    ) -> None:
        """Render Figure 4: Goodput (completed jobs / sec) vs. Workload Concurrency Scaling."""
        # Filter concurrency scaling results
        scaling_res = [r for r in results if r.config.category == "concurrency_scaling"]
        if not scaling_res:
            scaling_res = list(results[:3])

        raw_data = [r.to_dict() for r in scaling_res]
        (output_path.parent / f"{output_path.stem}_data.json").write_text(
            json.dumps(raw_data, indent=2), encoding="utf-8"
        )

        width, height = 740, 420
        margin_left, margin_right = 80, 50
        margin_top, margin_bottom = 60, 70
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">')
        svg.append(f'<rect width="{width}" height="{height}" fill="{PALETTE["bg"]}" rx="6"/>')

        svg.append(f'<text x="{width/2}" y="28" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="{PALETTE["text_dark"]}">FIGURE 4: System Goodput Scaling Across Concurrency & Workloads (RQ5)</text>')
        svg.append(f'<text x="{width/2}" y="46" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_muted"]}">Primary Throughput (Completed Unique Jobs / Second) Under Static Runtime</text>')

        max_goodput = max([r.goodput_stats.mean for r in scaling_res] + [100.0]) * 1.25

        ticks = 5
        for t in range(ticks + 1):
            val = (max_goodput / ticks) * t
            y = margin_top + plot_h - (val / max_goodput * plot_h)
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="{PALETTE["grid"]}" stroke-width="1.5"/>')
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">{val:.0f} j/s</text>')

        svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')
        svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')

        group_w = plot_w / max(1, len(scaling_res))
        bar_w = min(45.0, group_w * 0.4)

        for i, r in enumerate(scaling_res):
            cx = margin_left + i * group_w + group_w / 2.0
            g_val = r.goodput_stats.mean
            bar_h = (g_val / max_goodput) * plot_h
            bx = cx - bar_w / 2.0
            by = margin_top + plot_h - bar_h

            color = PALETTE["secondary"] if i % 2 == 1 else PALETTE["primary"]
            svg.append(f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="4"/>')
            svg.append(f'<text x="{cx}" y="{by - 8}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="700" fill="{color}">{g_val:.1f} j/s</text>')

            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 18}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="{PALETTE["text_dark"]}">{r.config.name}</text>')
            svg.append(f'<text x="{cx}" y="{margin_top + plot_h + 32}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="10" fill="{PALETTE["text_muted"]}">{r.config.jobs} jobs ({r.config.workers} workers)</text>')

        svg.append(f'<text x="{width/2}" y="{height - 15}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_dark"]}">Workload Scale & Worker Concurrency Configurations</text>')
        svg.append('</svg>')
        output_path.write_text("\n".join(svg), encoding="utf-8")

    # -------------------------------------------------------------------------
    # FIGURE 5: Ablation Study Comparison
    # -------------------------------------------------------------------------

    @classmethod
    def generate_figure_5_ablations(
        cls,
        result: AblationStudyResult,
        output_path: Path,
    ) -> None:
        """Render Figure 5: Architecture Ablation Comparison."""
        ablations = result.ablations
        raw_data = [a.to_dict() for a in ablations]
        (output_path.parent / f"{output_path.stem}_data.json").write_text(
            json.dumps(raw_data, indent=2), encoding="utf-8"
        )

        width, height = 760, 420
        margin_left, margin_right = 230, 90
        margin_top, margin_bottom = 60, 50
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">')
        svg.append(f'<rect width="{width}" height="{height}" fill="{PALETTE["bg"]}" rx="6"/>')

        svg.append(f'<text x="{width/2}" y="28" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="{PALETTE["text_dark"]}">FIGURE 5: Mechanism Ablation Impact on Primary Metrics (RQ6)</text>')
        svg.append(f'<text x="{width/2}" y="46" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="{PALETTE["text_muted"]}">Relative Change (%) in Primary Metric Observed When Ablating Mechanism</text>')

        # Center line at 0%
        zero_x = margin_left + plot_w / 2.0
        svg.append(f'<line x1="{zero_x}" y1="{margin_top}" x2="{zero_x}" y2="{margin_top + plot_h}" stroke="{PALETTE["axis"]}" stroke-width="1.5"/>')

        row_h = plot_h / max(1, len(ablations))
        bar_h = min(24.0, row_h * 0.6)

        # Scale: -100% to +100%
        scale_range = 100.0

        for i, a in enumerate(ablations):
            cy = margin_top + i * row_h + row_h / 2.0
            by = cy - bar_h / 2.0

            # Clip pct for visualization to [-100, 100]
            pct = max(-100.0, min(100.0, a.relative_change_pct))
            bw = abs(pct / scale_range) * (plot_w / 2.0)

            if pct < 0:
                bx = zero_x - bw
                color = PALETTE["accent"]
            else:
                bx = zero_x
                color = PALETTE["secondary"]

            svg.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bar_h}" fill="{color}" rx="3"/>')

            # Label on left
            lbl = f"{a.ablation_id}: {a.mechanism_name}"
            svg.append(f'<text x="{margin_left - 12}" y="{cy + 4}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" font-weight="600" fill="{PALETTE["text_dark"]}">{lbl}</text>')

            # Value label
            val_x = (zero_x - bw - 8) if pct < 0 else (zero_x + bw + 8)
            anchor = "end" if pct < 0 else "start"
            val_text = f"{a.relative_change_pct:+.1f}% ({a.impact_assessment})"
            svg.append(f'<text x="{val_x}" y="{cy + 4}" text-anchor="{anchor}" font-family="system-ui, sans-serif" font-size="10" font-weight="600" fill="{color}">{val_text}</text>')

        # Bottom Scale Markers
        svg.append(f'<text x="{zero_x}" y="{margin_top + plot_h + 20}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_dark"]}">0% (Baseline Reference)</text>')
        svg.append(f'<text x="{margin_left}" y="{margin_top + plot_h + 20}" text-anchor="start" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">-100% (Degraded)</text>')
        svg.append(f'<text x="{margin_left + plot_w}" y="{margin_top + plot_h + 20}" text-anchor="end" font-family="system-ui, sans-serif" font-size="11" fill="{PALETTE["text_muted"]}">+100% (Overhead/Speedup)</text>')

        svg.append('</svg>')
        output_path.write_text("\n".join(svg), encoding="utf-8")

    # -------------------------------------------------------------------------
    # Render All Figures
    # -------------------------------------------------------------------------

    @classmethod
    def render_all_figures(
        cls,
        output_dir: str | Path,
        policy_result: E3RecoveryPolicyResult,
        overhead_results: Sequence[TraceOverheadResult],
        replay_results: Sequence[ReplayEvaluationResult],
        stress_results: Sequence[StressEvaluationResult],
        ablation_result: AblationStudyResult,
    ) -> dict[str, str]:
        """Generate and write all 5 research figures to output directory."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        fig_paths: dict[str, str] = {}

        p1 = target_dir / "figure_1_recovery_rate_by_policy.svg"
        cls.generate_figure_1_recovery_rate(policy_result, p1)
        fig_paths["figure_1"] = str(p1)

        p2 = target_dir / "figure_2_tracing_overhead_vs_scale.svg"
        cls.generate_figure_2_tracing_overhead(overhead_results, p2)
        fig_paths["figure_2"] = str(p2)

        p3 = target_dir / "figure_3_replay_duration_vs_events.svg"
        cls.generate_figure_3_replay_cost(replay_results, p3)
        fig_paths["figure_3"] = str(p3)

        p4 = target_dir / "figure_4_goodput_vs_workload_scale.svg"
        cls.generate_figure_4_goodput_scaling(stress_results, p4)
        fig_paths["figure_4"] = str(p4)

        p5 = target_dir / "figure_5_ablation_comparison.svg"
        cls.generate_figure_5_ablations(ablation_result, p5)
        fig_paths["figure_5"] = str(p5)

        return fig_paths
