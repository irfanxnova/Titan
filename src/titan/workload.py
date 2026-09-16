"""Deterministic workload execution for Titan.

The computation itself is intentionally simple and reproducible; the primary
research focus is the system behavior and execution policies under load.
"""

from __future__ import annotations


def execute_workload(work_units: int) -> int:
    """Execute a strictly deterministic computation for the specified units.

    Uses a deterministic modular recurrence so that identical inputs always
    yield identical outputs without stochastic variation or external I/O.
    """
    accum = 0
    for i in range(1, work_units + 1):
        accum = (accum + (i * 31) ^ (i & 0xFF)) % 2147483647
    return accum
