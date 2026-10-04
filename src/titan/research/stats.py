"""Lightweight, defensible descriptive statistics and normalization utilities for Titan.

Strict adherence to empirical rigor:
- Transparent descriptive statistics (N, mean, median, min, max, std dev, cv).
- Strict avoidance of fabricated inferential statistics or hypothesis testing.
- Safe division and zero-denominator protections for normalized metrics.
- Explicit documentation of metric interpretation directionality (lower vs higher is better).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def safe_div(numerator: float | int, denominator: float | int, fallback: float = 0.0) -> float:
    """Safely divide two numbers with non-zero denominator protection."""
    if denominator == 0.0 or denominator == 0:
        return fallback
    return float(numerator) / float(denominator)


def compute_normalized_ratio(
    value: float | int,
    baseline_value: float | int,
    fallback: float = 1.0,
) -> float:
    """Compute normalized ratio: value / baseline_value.

    A ratio of 1.0 indicates identity with the baseline.
    """
    if baseline_value <= 0.0:
        return fallback
    return float(value) / float(baseline_value)


def compute_relative_change_pct(
    value: float | int,
    baseline_value: float | int,
    fallback: float = 0.0,
) -> float:
    """Compute percentage change relative to baseline: ((value - baseline) / baseline) * 100."""
    if baseline_value <= 0.0:
        return fallback
    return ((float(value) - float(baseline_value)) / float(baseline_value)) * 100.0


# Authoritative directionality lookup
_LOWER_IS_BETTER_KEYWORDS = {
    "duration",
    "latency",
    "overhead",
    "time",
    "lost_work",
    "failed",
    "retries",
    "errors",
    "unrecovered",
    "divergence",
    "divergences",
}

_HIGHER_IS_BETTER_KEYWORDS = {
    "goodput",
    "throughput",
    "completed",
    "recovery_rate",
    "equivalence_rate",
    "validity",
    "accuracy",
    "success",
}


def is_lower_better(metric_name: str) -> bool:
    """Determine whether smaller values are preferable for the given metric name."""
    name_lower = metric_name.lower()
    for kw in _LOWER_IS_BETTER_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def is_higher_better(metric_name: str) -> bool:
    """Determine whether larger values are preferable for the given metric name."""
    name_lower = metric_name.lower()
    for kw in _HIGHER_IS_BETTER_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def get_direction_label(metric_name: str) -> str:
    """Return human-readable directionality annotation for tables and figures."""
    if is_lower_better(metric_name):
        return "lower is better (↓)"
    if is_higher_better(metric_name):
        return "higher is better (↑)"
    return "neutral / context-dependent"


@dataclass(frozen=True)
class DescriptiveStats:
    """Lightweight, transparent descriptive summary of repeated numerical measurements."""

    n: int
    mean: float
    median: float
    min: float
    max: float
    std_dev: float
    cv: float
    sample_note: str

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            "n": self.n,
            "mean": round(self.mean, 6),
            "median": round(self.median, 6),
            "min": round(self.min, 6),
            "max": round(self.max, 6),
            "std_dev": round(self.std_dev, 6),
            "cv": round(self.cv, 4),
            "sample_note": self.sample_note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DescriptiveStats:
        """Construct DescriptiveStats from dictionary."""
        return cls(
            n=int(data["n"]),
            mean=float(data["mean"]),
            median=float(data["median"]),
            min=float(data["min"]),
            max=float(data["max"]),
            std_dev=float(data["std_dev"]),
            cv=float(data.get("cv", 0.0)),
            sample_note=str(data.get("sample_note", "")),
        )

    @classmethod
    def compute(cls, values: Sequence[float | int]) -> DescriptiveStats:
        """Compute transparent descriptive statistics with strict handling of small sample sizes."""
        clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
        n = len(clean)

        if n == 0:
            return cls(
                n=0,
                mean=0.0,
                median=0.0,
                min=0.0,
                max=0.0,
                std_dev=0.0,
                cv=0.0,
                sample_note="No valid measurements (N=0)",
            )

        sorted_vals = sorted(clean)
        min_v = sorted_vals[0]
        max_v = sorted_vals[-1]
        mean_v = sum(sorted_vals) / n

        # Median calculation
        if n % 2 == 1:
            median_v = sorted_vals[n // 2]
        else:
            median_v = (sorted_vals[(n // 2) - 1] + sorted_vals[n // 2]) / 2.0

        # Sample standard deviation (Bessel's correction n - 1)
        if n > 1:
            variance = sum((x - mean_v) ** 2 for x in sorted_vals) / (n - 1)
            std_dev_v = math.sqrt(max(0.0, variance))
            cv_v = safe_div(std_dev_v, abs(mean_v)) if mean_v != 0 else 0.0
            if n < 5:
                note = f"Small sample (N={n}): descriptive only, variance sensitive to outliers"
            else:
                note = f"Sample N={n}"
        else:
            std_dev_v = 0.0
            cv_v = 0.0
            note = "Single trial (N=1): sample variance undefined"

        return cls(
            n=n,
            mean=mean_v,
            median=median_v,
            min=min_v,
            max=max_v,
            std_dev=std_dev_v,
            cv=cv_v,
            sample_note=note,
        )
