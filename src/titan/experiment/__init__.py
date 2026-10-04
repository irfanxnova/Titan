"""Titan Recovery-Policy Experimentation Framework.

Provides a systematic, fair, and reproducible framework for evaluating and comparing
recovery policies under controlled distributed failure scenarios.
"""

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
]
