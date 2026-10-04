"""Titan Research-Grade Evaluation, Baselines, Ablations & Reproducibility System.

Provides the comprehensive empirical evaluation layer for answering Titan's core
research questions (RQ1-RQ6) with controlled baselines, structured ablations,
deterministic replay fidelity, ground-truth failure diagnosis, and automated
publication-style tables, figures, and reports.
"""

from __future__ import annotations

from titan.research.baselines import (
    BASELINE_REGISTRY,
    BaselineDefinition,
    BaselineId,
)
from titan.research.environment import EnvironmentMetadata
from titan.research.orchestrator import ResearchOrchestrator
from titan.research.plan import EvaluationPlan, ResearchPlanRegistry
from titan.research.reproducibility import (
    ReproducibilityReport,
    verify_reproducibility,
)
from titan.research.stats import DescriptiveStats, compute_relative_change_pct

__all__ = [
    "EvaluationPlan",
    "ResearchPlanRegistry",
    "BaselineId",
    "BaselineDefinition",
    "BASELINE_REGISTRY",
    "DescriptiveStats",
    "compute_relative_change_pct",
    "EnvironmentMetadata",
    "ResearchOrchestrator",
    "verify_reproducibility",
    "ReproducibilityReport",
]
