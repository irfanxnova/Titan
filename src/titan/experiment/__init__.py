"""Titan Recovery-Policy Experimentation Framework and System Evaluation.

Provides a systematic, fair, and reproducible framework for evaluating and comparing
recovery policies, measuring tracing overhead, quantifying replay performance,
and evaluating system scaling and stress under controlled distributed failures.
"""

from titan.experiment.evaluation import (
    EvaluationMode,
    EvaluationRunner,
    ReplayEvaluationResult,
    ReplayEvaluationTrial,
    StressEvaluationResult,
    StressTrial,
    StressWorkloadConfig,
    SystemEvaluationSuite,
    TraceOverheadResult,
    TraceOverheadTrial,
    compute_relative_overhead,
    safe_div,
)
from titan.experiment.metrics import (
    METRIC_DEFINITIONS,
    UNAVAILABLE_METRICS,
    ExperimentMetrics,
    MetricDefinition,
    extract_experiment_metrics,
)
from titan.experiment.policy import (
    PolicyRegistry,
    RecoveryPolicy,
)
from titan.experiment.runner import ExperimentRunner
from titan.experiment.trial import (
    ExperimentResult,
    ExperimentTrial,
    MetricStats,
    PolicyComparison,
)

__all__ = [
    "RecoveryPolicy",
    "PolicyRegistry",
    "MetricDefinition",
    "METRIC_DEFINITIONS",
    "UNAVAILABLE_METRICS",
    "ExperimentMetrics",
    "extract_experiment_metrics",
    "ExperimentTrial",
    "MetricStats",
    "ExperimentResult",
    "PolicyComparison",
    "ExperimentRunner",
    "EvaluationMode",
    "EvaluationRunner",
    "TraceOverheadTrial",
    "TraceOverheadResult",
    "ReplayEvaluationTrial",
    "ReplayEvaluationResult",
    "StressWorkloadConfig",
    "StressTrial",
    "StressEvaluationResult",
    "SystemEvaluationSuite",
    "safe_div",
    "compute_relative_overhead",
]
