"""Reproducibility environment metadata capture for Titan research artifacts.

Captures system execution environment parameters while rigorously scrubbing
user personal paths, usernames, and sensitive host identifiers.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from titan import __version__


def sanitize_path(path_str: str | Path) -> str:
    """Sanitize absolute filesystem paths into repository-relative or anonymized representations."""
    if not path_str:
        return ""
    p = str(path_str).replace("\\", "/")
    # If path contains 'Titan/', strip up to Titan
    if "Titan/" in p:
        idx = p.find("Titan/")
        return p[idx + len("Titan/") :]
    # Remove user home references
    for token in ["c:/users/", "/users/", "/home/"]:
        if token in p.lower():
            parts = p.split("/")
            # Redact user directory
            try:
                user_idx = [i for i, part in enumerate(parts) if part.lower() in ("users", "home")][0]
                if user_idx + 1 < len(parts):
                    parts[user_idx + 1] = "<redacted>"
                return "/".join(parts)
            except IndexError:
                pass
    return p


@dataclass(frozen=True)
class EnvironmentMetadata:
    """Lightweight, anonymized environment metadata capturing experimental context."""

    titan_version: str
    python_version: str
    python_implementation: str
    os_system: str
    os_release: str
    os_architecture: str
    cpu_count: int
    processor: str
    timestamp_utc: str

    def to_dict(self) -> dict[str, Any]:
        """Convert environment metadata to dictionary."""
        return {
            "titan_version": self.titan_version,
            "python_version": self.python_version,
            "python_implementation": self.python_implementation,
            "os_system": self.os_system,
            "os_release": self.os_release,
            "os_architecture": self.os_architecture,
            "cpu_count": self.cpu_count,
            "processor": self.processor,
            "timestamp_utc": self.timestamp_utc,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize metadata to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EnvironmentMetadata:
        """Construct EnvironmentMetadata from dictionary."""
        return cls(
            titan_version=str(data["titan_version"]),
            python_version=str(data["python_version"]),
            python_implementation=str(data["python_implementation"]),
            os_system=str(data["os_system"]),
            os_release=str(data["os_release"]),
            os_architecture=str(data["os_architecture"]),
            cpu_count=int(data["cpu_count"]),
            processor=str(data.get("processor", "generic")),
            timestamp_utc=str(data.get("timestamp_utc", "")),
        )

    @classmethod
    def capture(cls) -> EnvironmentMetadata:
        """Capture local environment without leaking private user information."""
        return cls(
            titan_version=__version__,
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            os_system=platform.system(),
            os_release=platform.release(),
            os_architecture=platform.machine(),
            cpu_count=os.cpu_count() or 1,
            processor=platform.processor() or "x86_64",
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
