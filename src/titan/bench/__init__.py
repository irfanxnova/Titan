"""TitanBench: Versioned, reproducible failure-corpus and scenario runner for Titan.

Provides a systematic, reproducible benchmark of distributed execution and failure
scenarios atop Titan's scenario, trace, replay, and analysis layers.
"""

from titan.bench.corpus import (
    BenchmarkScenario,
    CorpusRegistry,
    ExpectedBehavior,
    ScenarioClass,
)
from titan.bench.result import (
    BenchmarkArtifacts,
    BenchmarkResult,
    BenchmarkStatus,
    BenchmarkSummary,
)
from titan.bench.runner import TitanBenchRunner

__all__ = [
    "ScenarioClass",
    "ExpectedBehavior",
    "BenchmarkScenario",
    "CorpusRegistry",
    "BenchmarkStatus",
    "BenchmarkArtifacts",
    "BenchmarkResult",
    "BenchmarkSummary",
    "TitanBenchRunner",
]
