"""Configuration module for Titan.

Provides a minimal, immutable configuration structure with deterministic defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TitanConfig:
    """Immutable runtime configuration for Titan."""

    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> TitanConfig:
        """Load configuration from environment variables with safe fallbacks."""
        return cls(
            environment=os.getenv("TITAN_ENV", "development"),
            log_level=os.getenv("TITAN_LOG_LEVEL", "INFO"),
        )
