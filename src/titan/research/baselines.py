"""Explicit Baseline definitions and registry for Titan research evaluations.

Defines the authoritative set of experimental baselines required to validate
Titan research questions (RQ1-RQ6). Every comparative empirical measurement must
explicitly reference which baseline configuration is being used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class BaselineId(str, Enum):
    """Authoritative identifiers for experimental baselines."""

    B0_NORMAL_EXECUTION = "BASELINE-B0"
    B1_DEFAULT_RECOVERY = "BASELINE-B1"
    B2_NO_TRACING = "BASELINE-B2"
    B3_ALTERNATIVE_POLICIES = "BASELINE-B3"


@dataclass(frozen=True)
class BaselineDefinition:
    """Explicit metadata and configuration parameters defining an empirical baseline."""

    baseline_id: str
    name: str
    description: str
    target_research_questions: list[str]
    fault_injected: bool
    tracing_enabled: bool
    default_policy_id: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        """Convert baseline definition to dictionary."""
        return {
            "baseline_id": self.baseline_id,
            "name": self.name,
            "description": self.description,
            "target_research_questions": list(self.target_research_questions),
            "fault_injected": self.fault_injected,
            "tracing_enabled": self.tracing_enabled,
            "default_policy_id": self.default_policy_id,
            "rationale": self.rationale,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize baseline to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BaselineDefinition:
        """Construct BaselineDefinition from dictionary."""
        return cls(
            baseline_id=str(data["baseline_id"]),
            name=str(data["name"]),
            description=str(data["description"]),
            target_research_questions=list(data.get("target_research_questions", [])),
            fault_injected=bool(data["fault_injected"]),
            tracing_enabled=bool(data["tracing_enabled"]),
            default_policy_id=str(data["default_policy_id"]),
            rationale=str(data.get("rationale", "")),
        )


class BaselineRegistry:
    """Authoritative registry for experimental baselines."""

    _registry: dict[str, BaselineDefinition] = {}

    @classmethod
    def register(cls, baseline: BaselineDefinition) -> None:
        """Register a baseline definition."""
        cls._registry[baseline.baseline_id] = baseline

    @classmethod
    def get(cls, baseline_id: str) -> BaselineDefinition:
        """Retrieve baseline by ID."""
        if baseline_id not in cls._registry:
            avail = ", ".join(sorted(cls._registry.keys()))
            raise KeyError(f"Unknown baseline '{baseline_id}'. Available: {avail}")
        return cls._registry[baseline_id]

    @classmethod
    def list_all(cls) -> list[BaselineDefinition]:
        """List all registered baselines ordered by ID."""
        return [cls._registry[k] for k in sorted(cls._registry.keys())]

    @classmethod
    def clear(cls) -> None:
        """Clear registry."""
        cls._registry.clear()

    @classmethod
    def initialize_canonical_baselines(cls) -> None:
        """Register canonical Titan research baselines."""
        cls.clear()

        # BASELINE-B0: Normal Titan execution with no injected failure
        cls.register(
            BaselineDefinition(
                baseline_id=BaselineId.B0_NORMAL_EXECUTION.value,
                name="Normal Execution (No Failure)",
                description="Clean workload execution in the static multi-process runtime without any injected faults or worker terminations.",
                target_research_questions=["RQ3", "RQ4", "RQ5"],
                fault_injected=False,
                tracing_enabled=True,
                default_policy_id="R0",
                rationale="Establishes undisturbed performance and latency bounds against which recovery overhead and fault impacts are measured.",
            )
        )

        # BASELINE-B1: Existing Titan default recovery policy
        cls.register(
            BaselineDefinition(
                baseline_id=BaselineId.B1_DEFAULT_RECOVERY.value,
                name="Default Recovery Policy (R0: Restart & Retry)",
                description="Standard Titan recovery policy: automatic worker process replacement and default retry budget (max_retries=3).",
                target_research_questions=["RQ1", "RQ2", "RQ3", "RQ6"],
                fault_injected=True,
                tracing_enabled=True,
                default_policy_id="R0",
                rationale="Serves as the primary reference policy for comparative evaluations against degraded-capacity (R1) or limited-retry (R2/R3) policies.",
            )
        )

        # BASELINE-B2: Execution without structured trace collection
        cls.register(
            BaselineDefinition(
                baseline_id=BaselineId.B2_NO_TRACING.value,
                name="No-Trace Execution Baseline",
                description="Identical workload execution with structured event recording short-circuited (enable_tracing=False).",
                target_research_questions=["RQ4"],
                fault_injected=False,
                tracing_enabled=False,
                default_policy_id="R0",
                rationale="Provides pure computational execution times to isolate the runtime and memory overhead imposed by structured event tracing.",
            )
        )

        # BASELINE-B3: Alternative recovery policies from Prompt 9
        cls.register(
            BaselineDefinition(
                baseline_id=BaselineId.B3_ALTERNATIVE_POLICIES.value,
                name="Alternative Recovery Policies (R1, R2, R3)",
                description="Variant execution behaviors: no worker replacement (R1), limited retry budget (R2), and minimal fail-fast recovery (R3).",
                target_research_questions=["RQ3", "RQ6"],
                fault_injected=True,
                tracing_enabled=True,
                default_policy_id="R1",
                rationale="Exposes system trade-offs between worker recovery capacity, retry overhead, and lost work.",
            )
        )


# Global singleton registry instance and initialization
BASELINE_REGISTRY = BaselineRegistry
BaselineRegistry.initialize_canonical_baselines()
