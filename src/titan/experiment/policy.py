"""Recovery policy configuration and registry for Titan.

Defines explicit, immutable recovery policy specifications with stable identifiers,
enabling fair, controlled comparison across baseline, capacity-loss, and retry-limited
recovery behaviors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from titan.scenario import Scenario


@dataclass(frozen=True)
class RecoveryPolicy:
    """Explicit, immutable configuration specifying runtime failure-recovery behavior."""

    policy_id: str
    name: str
    description: str
    replace_failed_workers: bool = True
    max_retries: int = 3
    backoff_factor: float = 0.0

    def validate(self) -> None:
        """Validate recovery policy parameters."""
        if not self.policy_id or not self.policy_id.strip():
            raise ValueError("Recovery policy policy_id cannot be empty")
        if not self.name or not self.name.strip():
            raise ValueError("Recovery policy name cannot be empty")
        if self.max_retries < 1:
            raise ValueError(f"Recovery policy max_retries must be at least 1, got {self.max_retries}")
        if self.backoff_factor < 0.0:
            raise ValueError(f"Recovery policy backoff_factor cannot be negative, got {self.backoff_factor}")

    def apply_to_scenario(self, scenario: Scenario) -> Scenario:
        """Derive a new Scenario applying this policy's recovery parameters while preserving all non-policy variables."""
        self.validate()
        return Scenario(
            name=f"{scenario.name}_{self.policy_id.lower()}",
            num_workers=scenario.num_workers,
            num_jobs=scenario.num_jobs,
            work_units=scenario.work_units,
            pattern=scenario.pattern,
            seed=scenario.seed,
            max_retries=self.max_retries,
            replace_failed_workers=self.replace_failed_workers,
            fault_config=scenario.fault_config,
            fault_configs=scenario.fault_configs,
            duplicate_jobs=scenario.duplicate_jobs,
            timeout=scenario.timeout,
            enable_tracing=scenario.enable_tracing,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy configuration to dictionary."""
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "replace_failed_workers": self.replace_failed_workers,
            "max_retries": self.max_retries,
            "backoff_factor": self.backoff_factor,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize policy configuration to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecoveryPolicy:
        """Construct RecoveryPolicy from dictionary."""
        return cls(
            policy_id=data["policy_id"],
            name=data["name"],
            description=data.get("description", ""),
            replace_failed_workers=data.get("replace_failed_workers", True),
            max_retries=int(data.get("max_retries", 3)),
            backoff_factor=float(data.get("backoff_factor", 0.0)),
        )


class PolicyRegistry:
    """Authoritative registry for recovery policies with stable identifiers."""

    _registry: dict[str, RecoveryPolicy] = {}

    @classmethod
    def register(cls, policy: RecoveryPolicy) -> None:
        """Register a recovery policy ensuring stable ID uniqueness and validation."""
        policy.validate()
        if policy.policy_id in cls._registry:
            raise ValueError(f"Duplicate policy ID '{policy.policy_id}' already registered")
        cls._registry[policy.policy_id] = policy

    @classmethod
    def get(cls, policy_id: str) -> RecoveryPolicy:
        """Retrieve a registered policy by stable ID."""
        if policy_id not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise KeyError(f"Unknown recovery policy ID '{policy_id}'. Available: {available}")
        return cls._registry[policy_id]

    @classmethod
    def list_all(cls) -> list[RecoveryPolicy]:
        """Return all registered policies ordered by ID."""
        return [cls._registry[k] for k in sorted(cls._registry.keys())]

    @classmethod
    def clear(cls) -> None:
        """Clear registry (primarily for test isolation)."""
        cls._registry.clear()

    @classmethod
    def initialize_canonical_policies(cls) -> None:
        """Register the authoritative initial recovery policy variants."""
        cls.clear()

        # POLICY-R0 — Baseline / Existing Behavior
        cls.register(
            RecoveryPolicy(
                policy_id="R0",
                name="baseline-full-recovery",
                description="Standard Titan recovery: automatic worker replacement and default retry budget (max_retries=3).",
                replace_failed_workers=True,
                max_retries=3,
                backoff_factor=0.0,
            )
        )

        # POLICY-R1 — No Worker Replacement
        cls.register(
            RecoveryPolicy(
                policy_id="R1",
                name="no-worker-replacement",
                description="Failed workers are not replaced (replace_failed_workers=False); remaining workers process retried jobs under degraded capacity.",
                replace_failed_workers=False,
                max_retries=3,
                backoff_factor=0.0,
            )
        )

        # POLICY-R2 — Limited Retry
        cls.register(
            RecoveryPolicy(
                policy_id="R2",
                name="limited-retry",
                description="Worker replacement is enabled, but retry budget is strictly minimized (max_retries=1; zero retries allowed upon failure).",
                replace_failed_workers=True,
                max_retries=1,
                backoff_factor=0.0,
            )
        )

        # POLICY-R3 — Minimal Recovery
        cls.register(
            RecoveryPolicy(
                policy_id="R3",
                name="minimal-recovery-disabled",
                description="Minimal recovery: worker replacement is disabled and retry budget is strictly minimized (max_retries=1, replace_failed_workers=False).",
                replace_failed_workers=False,
                max_retries=1,
                backoff_factor=0.0,
            )
        )


# Initialize canonical policies at module import time
PolicyRegistry.initialize_canonical_policies()
