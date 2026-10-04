"""Structured event tracing and execution history for Titan.

Defines the canonical logical event model, event types, and execution trace collector
enabling complete reconstruction of job lifecycles, worker ownership, failures, retries,
and final outcomes without coupling to authoritative runtime state.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence


class EventType(str, Enum):
    """Canonical event types for structured logical execution tracing."""

    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    WORKER_STARTED = "WORKER_STARTED"
    WORKER_EXITED = "WORKER_EXITED"
    WORKER_FAILED = "WORKER_FAILED"
    WORKER_REPLACED = "WORKER_REPLACED"
    JOB_CREATED = "JOB_CREATED"
    JOB_ASSIGNED = "JOB_ASSIGNED"
    JOB_STARTED = "JOB_STARTED"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_FAILED = "JOB_FAILED"
    JOB_LOST = "JOB_LOST"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    JOB_REASSIGNED = "JOB_REASSIGNED"


@dataclass(frozen=True)
class TraceEvent:
    """Canonical structured representation of a logical execution event.

    Attributes:
        seq: Monotonically increasing sequence number defining canonical event ordering.
        event_type: Explicit lifecycle event category.
        timestamp: Time of event observation.
        job_id: Logical job identifier (if applicable).
        attempt_id: Concrete execution attempt identifier (if applicable).
        worker_id: Worker identifier responsible for event (if applicable).
        data: Structured details and telemetry payload.
    """

    seq: int
    event_type: EventType
    timestamp: float
    job_id: str | None = None
    attempt_id: int | None = None
    worker_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"#{self.seq} {self.event_type.value}"]
        if self.job_id:
            parts.append(f"job={self.job_id}")
        if self.attempt_id is not None:
            parts.append(f"att={self.attempt_id}")
        if self.worker_id:
            parts.append(f"worker={self.worker_id}")
        if self.data:
            items = ", ".join(f"{k}={v}" for k, v in self.data.items())
            parts.append(f"({items})")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to a JSON-compatible dictionary."""
        payload: dict[str, Any] = {
            "seq": self.seq,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "timestamp": round(self.timestamp, 6),
        }
        if self.job_id is not None:
            payload["job_id"] = self.job_id
        if self.attempt_id is not None:
            payload["attempt_id"] = self.attempt_id
        if self.worker_id is not None:
            payload["worker_id"] = self.worker_id
        if self.data:
            payload["data"] = self.data
        return payload

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceEvent:
        """Construct a TraceEvent from a dictionary."""
        raw_type = d["event_type"]
        event_type = EventType(raw_type) if raw_type in EventType._value2member_map_ else EventType[raw_type]
        return cls(
            seq=d["seq"],
            event_type=event_type,
            timestamp=d["timestamp"],
            job_id=d.get("job_id"),
            attempt_id=d.get("attempt_id"),
            worker_id=d.get("worker_id"),
            data=d.get("data", {}),
        )


class ExecutionTrace:
    """Canonical chronological collector of logical execution events."""

    def __init__(
        self,
        events: Sequence[TraceEvent] | None = None,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._events: list[TraceEvent] = list(events) if events else []
        self._seq_counter: int = len(self._events)

    @property
    def enabled(self) -> bool:
        """Indicate whether trace collection is active."""
        return self._enabled

    def emit(
        self,
        event_type: EventType,
        job_id: str | None = None,
        attempt_id: int | None = None,
        worker_id: str | None = None,
        data: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> TraceEvent:
        """Create, sequence, and record a canonical logical trace event."""
        if not self._enabled:
            return TraceEvent(
                seq=0,
                event_type=event_type,
                timestamp=0.0,
                job_id=job_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                data={},
            )
        self._seq_counter += 1
        ts = timestamp if timestamp is not None else time.perf_counter()
        event = TraceEvent(
            seq=self._seq_counter,
            event_type=event_type,
            timestamp=ts,
            job_id=job_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            data=dict(data) if data else {},
        )
        self._events.append(event)
        return event

    def clear(self) -> None:
        """Reset the trace collector."""
        self._events.clear()
        self._seq_counter = 0

    @property
    def events(self) -> list[TraceEvent]:
        """Return a shallow copy of all events in sequential order."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    def __getitem__(self, index: int) -> TraceEvent:
        return self._events[index]

    def filter_by_job(self, job_id: str) -> list[TraceEvent]:
        """Return events associated with a specific logical job."""
        return [e for e in self._events if e.job_id == job_id]

    def filter_by_worker(self, worker_id: str) -> list[TraceEvent]:
        """Return events associated with a specific worker."""
        return [e for e in self._events if e.worker_id == worker_id]

    def filter_by_type(self, event_type: EventType | str) -> list[TraceEvent]:
        """Return events of a specific event type."""
        target = event_type.value if isinstance(event_type, EventType) else str(event_type)
        return [
            e
            for e in self._events
            if (e.event_type.value if isinstance(e.event_type, EventType) else str(e.event_type)) == target
        ]

    def find_events(
        self,
        event_type: EventType | str | None = None,
        job_id: str | None = None,
        attempt_id: int | None = None,
        worker_id: str | None = None,
    ) -> list[TraceEvent]:
        """Find events matching all specified optional filter criteria."""
        results = self._events
        if event_type is not None:
            target = event_type.value if isinstance(event_type, EventType) else str(event_type)
            results = [
                e
                for e in results
                if (e.event_type.value if isinstance(e.event_type, EventType) else str(e.event_type)) == target
            ]
        if job_id is not None:
            results = [e for e in results if e.job_id == job_id]
        if attempt_id is not None:
            results = [e for e in results if e.attempt_id == attempt_id]
        if worker_id is not None:
            results = [e for e in results if e.worker_id == worker_id]
        return results

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize all events to a list of dicts."""
        return [e.to_dict() for e in self._events]

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize trace to formatted JSON string."""
        return json.dumps(self.to_list(), indent=indent)

    def save_to_file(self, path: str | Path) -> None:
        """Save trace as JSON to a file."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(self.to_json(indent=2), encoding="utf-8")

    @classmethod
    def from_list(cls, data: Sequence[dict[str, Any]]) -> ExecutionTrace:
        """Reconstruct trace from serialized list of dicts."""
        events = [TraceEvent.from_dict(item) for item in data]
        return cls(events=events)

    @classmethod
    def load_from_file(cls, path: str | Path) -> ExecutionTrace:
        """Load trace from JSON file."""
        content = Path(path).read_text(encoding="utf-8")
        data = json.loads(content)
        return cls.from_list(data)
