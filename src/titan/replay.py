"""Deterministic trace replay engine and execution history validator for Titan.

Reconstructs and verifies the logical execution state of a completed run solely
from a canonical structured execution trace without executing workload computation,
spawning worker processes, invoking fault injection, or depending on wall-clock timing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from titan.trace import EventType, ExecutionTrace, TraceEvent

__all__ = [
    "ReplayRunStatus",
    "ReplayWorkerStatus",
    "ReplayJobStatus",
    "ReplayAttemptStatus",
    "ReplayWorkerState",
    "ReplayAttemptState",
    "ReplayJobState",
    "ReplayState",
    "ReplayResult",
    "ReplayEngine",
    "DivergenceCategory",
    "DivergenceRecord",
    "FidelityResult",
    "ReplayFidelityEngine",
]


class ReplayRunStatus(str, Enum):
    """Lifecycle status of the replayed workload execution."""

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ReplayWorkerStatus(str, Enum):
    """Reconstructed lifecycle status of a worker entity."""

    IDLE = "IDLE"
    BUSY = "BUSY"
    FAILED = "FAILED"
    EXITED = "EXITED"


class ReplayJobStatus(str, Enum):
    """Reconstructed lifecycle status of a logical job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReplayAttemptStatus(str, Enum):
    """Reconstructed lifecycle status of a concrete execution attempt."""

    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    LOST = "LOST"


class DivergenceCategory(str, Enum):
    """Classification of divergence detected between expected and observed execution."""

    EVENT = "EVENT"
    STATE = "STATE"
    OWNERSHIP = "OWNERSHIP"
    RETRY = "RETRY"
    WORKER = "WORKER"
    OUTCOME = "OUTCOME"



@dataclass
class ReplayWorkerState:
    """Reconstructed state of an individual worker process."""

    worker_id: str
    status: ReplayWorkerStatus = ReplayWorkerStatus.IDLE
    is_replacement: bool = False
    replaced_worker_id: str | None = None
    current_job_id: str | None = None
    current_attempt_id: int | None = None
    completed_count: int = 0


@dataclass
class ReplayAttemptState:
    """Reconstructed state of an individual execution attempt."""

    job_id: str
    attempt_id: int
    worker_id: str | None = None
    status: ReplayAttemptStatus = ReplayAttemptStatus.CREATED
    started_at: float | None = None
    completed_at: float | None = None
    result: int | None = None
    error: str | None = None


@dataclass
class ReplayJobState:
    """Reconstructed state of a logical job."""

    job_id: str
    work_units: int = 0
    max_retries: int = 3
    status: ReplayJobStatus = ReplayJobStatus.PENDING
    active_attempt_id: int | None = None
    attempts: list[int] = field(default_factory=list)
    retry_count: int = 0
    terminal_outcome: str | None = None


@dataclass
class ReplayState:
    """Complete reconstructed logical state of a Titan workload execution."""

    run_status: ReplayRunStatus = ReplayRunStatus.NOT_STARTED
    workers: dict[str, ReplayWorkerState] = field(default_factory=dict)
    jobs: dict[str, ReplayJobState] = field(default_factory=dict)
    attempts: dict[tuple[str, int], ReplayAttemptState] = field(default_factory=dict)
    active_ownership: dict[str, tuple[str, int]] = field(default_factory=dict)
    total_retries: int = 0
    worker_failures: int = 0
    worker_replacements: int = 0


@dataclass(frozen=True)
class ReplayResult:
    """Outcome and diagnostics of deterministic trace replay and validation."""

    valid: bool
    total_events: int
    final_run_state: str
    reconstructed_job_states: dict[str, str]
    reconstructed_worker_states: dict[str, str]
    attempts: int
    retries: int
    worker_failures: int
    worker_replacements: int
    validation_errors: list[str]
    summary_metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize replay results to a dictionary suitable for JSON export."""
        return {
            "valid": self.valid,
            "total_events": self.total_events,
            "final_run_state": self.final_run_state,
            "reconstructed_job_states": self.reconstructed_job_states,
            "reconstructed_worker_states": self.reconstructed_worker_states,
            "attempts": self.attempts,
            "retries": self.retries,
            "worker_failures": self.worker_failures,
            "worker_replacements": self.worker_replacements,
            "validation_errors": self.validation_errors,
            "summary_metrics": self.summary_metrics,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize replay results to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayResult:
        """Construct a ReplayResult from serialized dictionary representation."""
        return cls(
            valid=data["valid"],
            total_events=data["total_events"],
            final_run_state=data["final_run_state"],
            reconstructed_job_states=dict(data.get("reconstructed_job_states", {})),
            reconstructed_worker_states=dict(data.get("reconstructed_worker_states", {})),
            attempts=data.get("attempts", 0),
            retries=data.get("retries", 0),
            worker_failures=data.get("worker_failures", 0),
            worker_replacements=data.get("worker_replacements", 0),
            validation_errors=list(data.get("validation_errors", [])),
            summary_metrics=dict(data.get("summary_metrics", {})),
        )


@dataclass(frozen=True)
class DivergenceRecord:
    """Explicit, structured record of a divergence between expected and observed execution."""

    category: DivergenceCategory
    message: str
    seq: int | None = None
    expected: Any = None
    observed: Any = None
    job_id: str | None = None
    attempt_id: int | None = None
    worker_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize divergence record to a JSON-compatible dictionary."""
        return {
            "category": self.category.value if isinstance(self.category, DivergenceCategory) else str(self.category),
            "message": self.message,
            "seq": self.seq,
            "expected": self.expected,
            "observed": self.observed,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "worker_id": self.worker_id,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DivergenceRecord:
        """Construct a DivergenceRecord from a dictionary."""
        return cls(
            category=DivergenceCategory(data["category"]),
            message=data["message"],
            seq=data.get("seq"),
            expected=data.get("expected"),
            observed=data.get("observed"),
            job_id=data.get("job_id"),
            attempt_id=data.get("attempt_id"),
            worker_id=data.get("worker_id"),
            details=dict(data.get("details", {})),
        )


@dataclass(frozen=True)
class FidelityResult:
    """Result of deterministic execution replay fidelity comparison."""

    equivalent: bool
    total_comparisons: int
    divergence_count: int
    divergences: list[DivergenceRecord]
    first_divergence: DivergenceRecord | None
    summary_by_category: dict[str, int]
    expected_events_count: int
    observed_events_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize fidelity result to a dictionary suitable for JSON export."""
        return {
            "equivalent": self.equivalent,
            "total_comparisons": self.total_comparisons,
            "divergence_count": self.divergence_count,
            "first_divergence": self.first_divergence.to_dict() if self.first_divergence else None,
            "summary_by_category": self.summary_by_category,
            "expected_events_count": self.expected_events_count,
            "observed_events_count": self.observed_events_count,
            "divergences": [d.to_dict() for d in self.divergences],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize fidelity result to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FidelityResult:
        """Construct a FidelityResult from a dictionary representation."""
        first = DivergenceRecord.from_dict(data["first_divergence"]) if data.get("first_divergence") else None
        divs = [DivergenceRecord.from_dict(d) for d in data.get("divergences", [])]
        return cls(
            equivalent=data["equivalent"],
            total_comparisons=data["total_comparisons"],
            divergence_count=data["divergence_count"],
            divergences=divs,
            first_divergence=first,
            summary_by_category=dict(data.get("summary_by_category", {})),
            expected_events_count=data.get("expected_events_count", 0),
            observed_events_count=data.get("observed_events_count", 0),
        )


class ReplayEngine:
    """Observational deterministic replay engine for Titan structured execution traces."""

    @classmethod
    def replay(
        cls,
        trace_input: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path,
    ) -> ReplayResult:
        """Reconstruct and validate logical execution history from a structured trace."""
        events = cls._normalize_trace(trace_input)
        state = ReplayState()
        errors: list[str] = []
        expected_seq = 1

        for event in events:
            # 1. Monotonic sequence verification
            if event.seq != expected_seq:
                errors.append(f"Event sequence discontinuity: expected seq {expected_seq}, got {event.seq}")
                expected_seq = event.seq + 1
            else:
                expected_seq += 1

            # 2. Run state boundaries
            if state.run_status == ReplayRunStatus.NOT_STARTED:
                if event.event_type != EventType.RUN_STARTED:
                    errors.append(
                        f"Event {event.event_type.value} occurred before RUN_STARTED at seq {event.seq}"
                    )
            elif state.run_status == ReplayRunStatus.COMPLETED:
                # Only clean shutdown WORKER_EXITED events are permitted after RUN_COMPLETED
                if event.event_type != EventType.WORKER_EXITED:
                    errors.append(
                        f"Illegal event {event.event_type.value} occurred after RUN_COMPLETED at seq {event.seq}"
                    )

            # 3. Transition validation & state progression
            cls._process_event(event, state, errors)

        # 4. Post-trace completion verification
        if events and state.run_status != ReplayRunStatus.COMPLETED:
            errors.append("Trace terminated without RUN_COMPLETED event")

        summary_metrics = {
            "total_jobs": len(state.jobs),
            "completed_jobs": len(
                [j for j in state.jobs.values() if j.status == ReplayJobStatus.COMPLETED]
            ),
            "failed_jobs": len(
                [j for j in state.jobs.values() if j.status == ReplayJobStatus.FAILED]
            ),
            "total_attempts": len(state.attempts),
            "total_retries": state.total_retries,
            "worker_failures": state.worker_failures,
            "worker_replacements": state.worker_replacements,
            "total_workers": len(state.workers),
        }

        return ReplayResult(
            valid=len(errors) == 0,
            total_events=len(events),
            final_run_state=state.run_status.value,
            reconstructed_job_states={jid: j.status.value for jid, j in state.jobs.items()},
            reconstructed_worker_states={wid: w.status.value for wid, w in state.workers.items()},
            attempts=len(state.attempts),
            retries=state.total_retries,
            worker_failures=state.worker_failures,
            worker_replacements=state.worker_replacements,
            validation_errors=errors,
            summary_metrics=summary_metrics,
        )

    @classmethod
    def replay_file(cls, path: str | Path) -> ReplayResult:
        """Load and replay a structured trace from a JSON file."""
        return cls.replay(path)

    @classmethod
    def compare(
        cls,
        expected: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path | ReplayResult,
        observed: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path | ReplayResult,
    ) -> FidelityResult:
        """Compare expected and observed execution traces for deterministic fidelity."""
        return ReplayFidelityEngine.compare(expected=expected, observed=observed)


    @classmethod
    def _normalize_trace(
        cls,
        trace_input: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path,
    ) -> list[TraceEvent]:
        """Convert various trace input formats to a sequence of TraceEvent instances."""
        if isinstance(trace_input, ExecutionTrace):
            return trace_input.events

        if isinstance(trace_input, (str, Path)):
            p = Path(trace_input)
            if p.is_file():
                return ExecutionTrace.load_from_file(p).events
            data = json.loads(str(trace_input))
            return ExecutionTrace.from_list(data).events

        if isinstance(trace_input, Sequence):
            if not trace_input:
                return []
            first = trace_input[0]
            if isinstance(first, TraceEvent):
                return list(trace_input)  # type: ignore
            if isinstance(first, dict):
                return [TraceEvent.from_dict(d) for d in trace_input]  # type: ignore

        raise ValueError(f"Unsupported trace input type: {type(trace_input)}")

    @classmethod
    def _process_event(cls, event: TraceEvent, state: ReplayState, errors: list[str]) -> None:
        """Apply deterministic transition rules for a single trace event."""
        etype = event.event_type

        if etype == EventType.RUN_STARTED:
            if state.run_status != ReplayRunStatus.NOT_STARTED:
                errors.append(f"Duplicate or unexpected RUN_STARTED at seq {event.seq}")
            state.run_status = ReplayRunStatus.RUNNING

        elif etype == EventType.WORKER_STARTED:
            if not event.worker_id:
                errors.append(f"WORKER_STARTED missing worker_id at seq {event.seq}")
                return
            w = state.workers.get(event.worker_id)
            if w is not None and w.status in (ReplayWorkerStatus.IDLE, ReplayWorkerStatus.BUSY):
                errors.append(f"Worker {event.worker_id} started while already active at seq {event.seq}")
            is_rep = event.data.get("is_replacement", False)
            rep_id = event.data.get("replaced_worker_id")
            state.workers[event.worker_id] = ReplayWorkerState(
                worker_id=event.worker_id,
                status=ReplayWorkerStatus.IDLE,
                is_replacement=is_rep,
                replaced_worker_id=rep_id,
            )

        elif etype == EventType.JOB_CREATED:
            if not event.job_id:
                errors.append(f"JOB_CREATED missing job_id at seq {event.seq}")
                return
            if event.job_id in state.jobs:
                errors.append(f"Duplicate JOB_CREATED for job {event.job_id} at seq {event.seq}")
                return
            state.jobs[event.job_id] = ReplayJobState(
                job_id=event.job_id,
                work_units=event.data.get("work_units", 0),
                max_retries=event.data.get("max_retries", 3),
                status=ReplayJobStatus.PENDING,
            )

        elif etype == EventType.JOB_ASSIGNED:
            if not event.job_id or event.attempt_id is None or not event.worker_id:
                errors.append(f"JOB_ASSIGNED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_ASSIGNED for unknown job {event.job_id} at seq {event.seq}")
                return
            worker = state.workers.get(event.worker_id)
            if worker is None:
                errors.append(f"JOB_ASSIGNED to unknown worker {event.worker_id} at seq {event.seq}")
                return
            if worker.status in (ReplayWorkerStatus.FAILED, ReplayWorkerStatus.EXITED):
                errors.append(
                    f"JOB_ASSIGNED to inactive/failed worker {event.worker_id} at seq {event.seq}"
                )
            if event.attempt_id != 1:
                errors.append(
                    f"Initial JOB_ASSIGNED must have attempt_id=1, got {event.attempt_id} at seq {event.seq}"
                )
            if job.status != ReplayJobStatus.PENDING:
                errors.append(
                    f"JOB_ASSIGNED for job {event.job_id} in invalid state {job.status.value} at seq {event.seq}"
                )

            att_key = (event.job_id, event.attempt_id)
            if att_key in state.attempts:
                errors.append(f"Attempt {att_key} already exists at seq {event.seq}")
            state.attempts[att_key] = ReplayAttemptState(
                job_id=event.job_id,
                attempt_id=event.attempt_id,
                worker_id=event.worker_id,
                status=ReplayAttemptStatus.ASSIGNED,
            )
            job.status = ReplayJobStatus.RUNNING
            job.active_attempt_id = event.attempt_id
            if event.attempt_id not in job.attempts:
                job.attempts.append(event.attempt_id)

            worker.status = ReplayWorkerStatus.BUSY
            worker.current_job_id = event.job_id
            worker.current_attempt_id = event.attempt_id
            state.active_ownership[event.worker_id] = att_key

        elif etype == EventType.JOB_STARTED:
            if not event.job_id or event.attempt_id is None:
                errors.append(f"JOB_STARTED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_STARTED for unknown job {event.job_id} at seq {event.seq}")
                return
            att_key = (event.job_id, event.attempt_id)
            attempt = state.attempts.get(att_key)
            if attempt is None:
                errors.append(f"JOB_STARTED for unassigned attempt {att_key} at seq {event.seq}")
                return
            if attempt.status not in (ReplayAttemptStatus.ASSIGNED, ReplayAttemptStatus.RUNNING):
                errors.append(
                    f"JOB_STARTED for attempt {att_key} in invalid state {attempt.status.value} at seq {event.seq}"
                )
            if event.worker_id and attempt.worker_id and event.worker_id != attempt.worker_id:
                errors.append(
                    f"JOB_STARTED worker {event.worker_id} mismatch assigned worker {attempt.worker_id} at seq {event.seq}"
                )
            attempt.status = ReplayAttemptStatus.RUNNING
            attempt.started_at = event.timestamp

        elif etype == EventType.JOB_COMPLETED:
            if not event.job_id or event.attempt_id is None:
                errors.append(f"JOB_COMPLETED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_COMPLETED for unknown job {event.job_id} at seq {event.seq}")
                return
            att_key = (event.job_id, event.attempt_id)
            attempt = state.attempts.get(att_key)
            if attempt is None:
                errors.append(f"JOB_COMPLETED for unassigned attempt {att_key} at seq {event.seq}")
                return
            if attempt.status == ReplayAttemptStatus.COMPLETED:
                errors.append(
                    f"Duplicate terminal completion for attempt {att_key} at seq {event.seq}"
                )
            elif attempt.status not in (ReplayAttemptStatus.ASSIGNED, ReplayAttemptStatus.RUNNING):
                errors.append(
                    f"JOB_COMPLETED for attempt {att_key} in invalid state {attempt.status.value} at seq {event.seq}"
                )

            attempt.status = ReplayAttemptStatus.COMPLETED
            attempt.completed_at = event.timestamp
            attempt.result = event.data.get("result")
            job.status = ReplayJobStatus.COMPLETED
            job.terminal_outcome = "COMPLETED"

            if event.worker_id:
                w = state.workers.get(event.worker_id)
                if w:
                    w.status = ReplayWorkerStatus.IDLE
                    w.current_job_id = None
                    w.current_attempt_id = None
                    w.completed_count += 1
                state.active_ownership.pop(event.worker_id, None)

        elif etype == EventType.JOB_FAILED:
            if not event.job_id or event.attempt_id is None:
                errors.append(f"JOB_FAILED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_FAILED for unknown job {event.job_id} at seq {event.seq}")
                return
            att_key = (event.job_id, event.attempt_id)
            attempt = state.attempts.get(att_key)
            if attempt is not None:
                attempt.status = ReplayAttemptStatus.FAILED
                attempt.completed_at = event.timestamp
                attempt.error = event.data.get("error")
            job.status = ReplayJobStatus.FAILED
            job.terminal_outcome = "FAILED"
            if event.worker_id:
                w = state.workers.get(event.worker_id)
                if w:
                    w.status = ReplayWorkerStatus.IDLE
                    w.current_job_id = None
                    w.current_attempt_id = None
                state.active_ownership.pop(event.worker_id, None)

        elif etype == EventType.WORKER_FAILED:
            if not event.worker_id:
                errors.append(f"WORKER_FAILED missing worker_id at seq {event.seq}")
                return
            worker = state.workers.get(event.worker_id)
            if worker is None:
                errors.append(f"WORKER_FAILED for unknown worker {event.worker_id} at seq {event.seq}")
                return
            if worker.status == ReplayWorkerStatus.FAILED:
                errors.append(
                    f"Duplicate WORKER_FAILED for worker {event.worker_id} at seq {event.seq}"
                )
            worker.status = ReplayWorkerStatus.FAILED
            state.worker_failures += 1

        elif etype == EventType.JOB_LOST:
            if not event.job_id or event.attempt_id is None:
                errors.append(f"JOB_LOST missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_LOST for unknown job {event.job_id} at seq {event.seq}")
                return
            att_key = (event.job_id, event.attempt_id)
            attempt = state.attempts.get(att_key)
            if attempt is None:
                errors.append(f"JOB_LOST for unknown attempt {att_key} at seq {event.seq}")
                return
            if attempt.status in (ReplayAttemptStatus.COMPLETED, ReplayAttemptStatus.FAILED):
                errors.append(
                    f"JOB_LOST for already-terminal attempt {att_key} at seq {event.seq}"
                )
            attempt.status = ReplayAttemptStatus.LOST
            if event.worker_id:
                state.active_ownership.pop(event.worker_id, None)

        elif etype == EventType.RETRY_SCHEDULED:
            if not event.job_id or event.attempt_id is None:
                errors.append(f"RETRY_SCHEDULED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"RETRY_SCHEDULED for unknown job {event.job_id} at seq {event.seq}")
                return
            if job.status == ReplayJobStatus.COMPLETED:
                errors.append(
                    f"RETRY_SCHEDULED for already completed job {event.job_id} at seq {event.seq}"
                )
            if event.attempt_id <= 1:
                errors.append(
                    f"RETRY_SCHEDULED attempt_id must be > 1, got {event.attempt_id} at seq {event.seq}"
                )
            if event.attempt_id > job.max_retries:
                errors.append(
                    f"RETRY_SCHEDULED attempt_id {event.attempt_id} exceeds max_retries {job.max_retries} for job {event.job_id} at seq {event.seq}"
                )

            # Ensure previous attempt was actually lost or failed
            prev_attempt_key = (event.job_id, event.attempt_id - 1)
            prev_attempt = state.attempts.get(prev_attempt_key)
            if prev_attempt is not None and prev_attempt.status not in (
                ReplayAttemptStatus.LOST,
                ReplayAttemptStatus.FAILED,
                ReplayAttemptStatus.ASSIGNED,
                ReplayAttemptStatus.RUNNING,
            ):
                errors.append(
                    f"RETRY_SCHEDULED for job {event.job_id} without prior failed/lost execution at seq {event.seq}"
                )

            job.status = ReplayJobStatus.RETRY_PENDING
            job.retry_count += 1
            state.total_retries += 1

        elif etype == EventType.WORKER_REPLACED:
            if not event.worker_id:
                errors.append(f"WORKER_REPLACED missing worker_id at seq {event.seq}")
                return
            replaced_id = event.data.get("replaced_worker_id")
            if not replaced_id:
                errors.append(f"WORKER_REPLACED missing replaced_worker_id at seq {event.seq}")
            elif replaced_id not in state.workers:
                errors.append(
                    f"WORKER_REPLACED refers to unknown worker {replaced_id} at seq {event.seq}"
                )
            elif state.workers[replaced_id].status not in (
                ReplayWorkerStatus.FAILED,
                ReplayWorkerStatus.EXITED,
            ):
                errors.append(
                    f"WORKER_REPLACED refers to non-failed worker {replaced_id} at seq {event.seq}"
                )
            state.worker_replacements += 1

        elif etype == EventType.JOB_REASSIGNED:
            if not event.job_id or event.attempt_id is None or not event.worker_id:
                errors.append(f"JOB_REASSIGNED missing identifiers at seq {event.seq}")
                return
            job = state.jobs.get(event.job_id)
            if job is None:
                errors.append(f"JOB_REASSIGNED for unknown job {event.job_id} at seq {event.seq}")
                return
            worker = state.workers.get(event.worker_id)
            if worker is None:
                errors.append(
                    f"JOB_REASSIGNED to unknown worker {event.worker_id} at seq {event.seq}"
                )
                return
            if worker.status in (ReplayWorkerStatus.FAILED, ReplayWorkerStatus.EXITED):
                errors.append(
                    f"JOB_REASSIGNED to failed or inactive worker {event.worker_id} at seq {event.seq}"
                )
            if event.attempt_id <= 1:
                errors.append(
                    f"JOB_REASSIGNED attempt_id must be > 1, got {event.attempt_id} at seq {event.seq}"
                )
            if job.status != ReplayJobStatus.RETRY_PENDING:
                errors.append(
                    f"JOB_REASSIGNED for job {event.job_id} not in RETRY_PENDING (currently {job.status.value}) at seq {event.seq}"
                )

            att_key = (event.job_id, event.attempt_id)
            if att_key in state.attempts:
                errors.append(f"Attempt {att_key} already exists at seq {event.seq}")
            state.attempts[att_key] = ReplayAttemptState(
                job_id=event.job_id,
                attempt_id=event.attempt_id,
                worker_id=event.worker_id,
                status=ReplayAttemptStatus.ASSIGNED,
            )
            job.status = ReplayJobStatus.RUNNING
            job.active_attempt_id = event.attempt_id
            if event.attempt_id not in job.attempts:
                job.attempts.append(event.attempt_id)

            worker.status = ReplayWorkerStatus.BUSY
            worker.current_job_id = event.job_id
            worker.current_attempt_id = event.attempt_id
            state.active_ownership[event.worker_id] = att_key

        elif etype == EventType.WORKER_EXITED:
            if not event.worker_id:
                errors.append(f"WORKER_EXITED missing worker_id at seq {event.seq}")
                return
            w = state.workers.get(event.worker_id)
            if w is None:
                errors.append(f"WORKER_EXITED for unknown worker {event.worker_id} at seq {event.seq}")
                return
            w.status = ReplayWorkerStatus.EXITED
            state.active_ownership.pop(event.worker_id, None)

        elif etype == EventType.RUN_COMPLETED:
            if state.run_status != ReplayRunStatus.RUNNING:
                errors.append(
                    f"RUN_COMPLETED when run is not RUNNING (currently {state.run_status.value}) at seq {event.seq}"
                )
            state.run_status = ReplayRunStatus.COMPLETED

            # Verify all submitted jobs reached terminal states
            for jid, j in state.jobs.items():
                if j.status not in (ReplayJobStatus.COMPLETED, ReplayJobStatus.FAILED):
                    errors.append(
                        f"Job {jid} left in non-terminal state {j.status.value} at RUN_COMPLETED"
                    )


class ReplayFidelityEngine:
    """Deterministic fidelity comparison and divergence detection engine.

    Evaluates execution equivalence between expected and observed traces or replay
    results, identifying the exact sequence position, category, and context of divergence.
    """

    @classmethod
    def compare(
        cls,
        expected: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path | ReplayResult,
        observed: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path | ReplayResult,
    ) -> FidelityResult:
        """Compare expected and observed execution traces for deterministic fidelity."""
        if isinstance(expected, ReplayResult) and isinstance(observed, ReplayResult):
            return cls.compare_replay_results(expected, observed)

        expected_events = ReplayEngine._normalize_trace(expected)
        observed_events = ReplayEngine._normalize_trace(observed)

        # Run replay on both to reconstruct logical execution states
        expected_replay = ReplayEngine.replay(expected_events)
        observed_replay = ReplayEngine.replay(observed_events)

        divergences: list[DivergenceRecord] = []
        total_comparisons = 0

        # Step 1: Event-by-event comparison in canonical sequence order
        max_events = max(len(expected_events), len(observed_events))
        for i in range(max_events):
            if i < len(expected_events) and i < len(observed_events):
                exp_ev = expected_events[i]
                obs_ev = observed_events[i]

                # 1. Monotonic Sequence continuity check
                total_comparisons += 1
                if exp_ev.seq != obs_ev.seq:
                    divergences.append(
                        DivergenceRecord(
                            category=DivergenceCategory.EVENT,
                            message=f"Sequence number mismatch: expected seq {exp_ev.seq}, observed seq {obs_ev.seq}",
                            seq=obs_ev.seq,
                            expected=exp_ev.seq,
                            observed=obs_ev.seq,
                            job_id=obs_ev.job_id or exp_ev.job_id,
                            attempt_id=obs_ev.attempt_id or exp_ev.attempt_id,
                            worker_id=obs_ev.worker_id or exp_ev.worker_id,
                        )
                    )

                # 2. Event Type check
                total_comparisons += 1
                if exp_ev.event_type != obs_ev.event_type:
                    divergences.append(
                        DivergenceRecord(
                            category=DivergenceCategory.EVENT,
                            message=f"Event type mismatch at seq {exp_ev.seq}: expected '{exp_ev.event_type.value}', observed '{obs_ev.event_type.value}'",
                            seq=exp_ev.seq,
                            expected=exp_ev.event_type.value,
                            observed=obs_ev.event_type.value,
                            job_id=obs_ev.job_id or exp_ev.job_id,
                            attempt_id=obs_ev.attempt_id or exp_ev.attempt_id,
                            worker_id=obs_ev.worker_id or exp_ev.worker_id,
                        )
                    )

                # 3. Job Identity check
                total_comparisons += 1
                if exp_ev.job_id != obs_ev.job_id:
                    divergences.append(
                        DivergenceRecord(
                            category=DivergenceCategory.EVENT,
                            message=f"Job identity mismatch at seq {exp_ev.seq}: expected '{exp_ev.job_id}', observed '{obs_ev.job_id}'",
                            seq=exp_ev.seq,
                            expected=exp_ev.job_id,
                            observed=obs_ev.job_id,
                            job_id=obs_ev.job_id,
                            attempt_id=obs_ev.attempt_id or exp_ev.attempt_id,
                            worker_id=obs_ev.worker_id or exp_ev.worker_id,
                        )
                    )

                # 4. Attempt Identity & Retry check
                total_comparisons += 1
                if exp_ev.attempt_id != obs_ev.attempt_id:
                    divergences.append(
                        DivergenceRecord(
                            category=DivergenceCategory.RETRY,
                            message=f"Attempt ID mismatch at seq {exp_ev.seq} for job {exp_ev.job_id}: expected attempt {exp_ev.attempt_id}, observed {obs_ev.attempt_id}",
                            seq=exp_ev.seq,
                            expected=exp_ev.attempt_id,
                            observed=obs_ev.attempt_id,
                            job_id=exp_ev.job_id,
                            attempt_id=obs_ev.attempt_id,
                            worker_id=obs_ev.worker_id or exp_ev.worker_id,
                        )
                    )

                # 5. Worker Identity & Ownership check
                total_comparisons += 1
                if exp_ev.worker_id != obs_ev.worker_id:
                    if exp_ev.event_type in (
                        EventType.JOB_ASSIGNED,
                        EventType.JOB_STARTED,
                        EventType.JOB_COMPLETED,
                        EventType.JOB_FAILED,
                        EventType.JOB_LOST,
                        EventType.JOB_REASSIGNED,
                    ):
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.OWNERSHIP,
                                message=f"Worker ownership mismatch at seq {exp_ev.seq} for job {exp_ev.job_id} attempt {exp_ev.attempt_id}: expected worker '{exp_ev.worker_id}', observed '{obs_ev.worker_id}'",
                                seq=exp_ev.seq,
                                expected=exp_ev.worker_id,
                                observed=obs_ev.worker_id,
                                job_id=exp_ev.job_id,
                                attempt_id=exp_ev.attempt_id,
                                worker_id=obs_ev.worker_id,
                            )
                        )
                    else:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.WORKER,
                                message=f"Worker lifecycle entity mismatch at seq {exp_ev.seq} ({exp_ev.event_type.value}): expected worker '{exp_ev.worker_id}', observed '{obs_ev.worker_id}'",
                                seq=exp_ev.seq,
                                expected=exp_ev.worker_id,
                                observed=obs_ev.worker_id,
                                worker_id=obs_ev.worker_id,
                            )
                        )

                # 6. Deterministic payload data checks
                if exp_ev.event_type == EventType.WORKER_REPLACED:
                    total_comparisons += 1
                    exp_rep = exp_ev.data.get("replaced_worker_id")
                    obs_rep = obs_ev.data.get("replaced_worker_id")
                    if exp_rep != obs_rep:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.WORKER,
                                message=f"Replaced worker mismatch at seq {exp_ev.seq}: expected '{exp_rep}', observed '{obs_rep}'",
                                seq=exp_ev.seq,
                                expected=exp_rep,
                                observed=obs_rep,
                                worker_id=exp_ev.worker_id,
                            )
                        )

                elif exp_ev.event_type == EventType.JOB_COMPLETED:
                    total_comparisons += 1
                    exp_res = exp_ev.data.get("result")
                    obs_res = obs_ev.data.get("result")
                    if exp_res != obs_res:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.OUTCOME,
                                message=f"Job result mismatch at seq {exp_ev.seq} for job {exp_ev.job_id}: expected {exp_res}, observed {obs_res}",
                                seq=exp_ev.seq,
                                expected=exp_res,
                                observed=obs_res,
                                job_id=exp_ev.job_id,
                                attempt_id=exp_ev.attempt_id,
                                worker_id=exp_ev.worker_id,
                            )
                        )

                elif exp_ev.event_type == EventType.JOB_FAILED:
                    total_comparisons += 1
                    exp_err = exp_ev.data.get("error")
                    obs_err = obs_ev.data.get("error")
                    if exp_err != obs_err:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.OUTCOME,
                                message=f"Job failure error mismatch at seq {exp_ev.seq} for job {exp_ev.job_id}: expected '{exp_err}', observed '{obs_err}'",
                                seq=exp_ev.seq,
                                expected=exp_err,
                                observed=obs_err,
                                job_id=exp_ev.job_id,
                                attempt_id=exp_ev.attempt_id,
                                worker_id=exp_ev.worker_id,
                            )
                        )

                elif exp_ev.event_type == EventType.RUN_COMPLETED:
                    total_comparisons += 2
                    exp_comp = exp_ev.data.get("completed")
                    obs_comp = obs_ev.data.get("completed")
                    if exp_comp != obs_comp:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.OUTCOME,
                                message=f"Run completed jobs count mismatch at seq {exp_ev.seq}: expected {exp_comp}, observed {obs_comp}",
                                seq=exp_ev.seq,
                                expected=exp_comp,
                                observed=obs_comp,
                            )
                        )
                    exp_fail = exp_ev.data.get("failed")
                    obs_fail = obs_ev.data.get("failed")
                    if exp_fail != obs_fail:
                        divergences.append(
                            DivergenceRecord(
                                category=DivergenceCategory.OUTCOME,
                                message=f"Run failed jobs count mismatch at seq {exp_ev.seq}: expected {exp_fail}, observed {obs_fail}",
                                seq=exp_ev.seq,
                                expected=exp_fail,
                                observed=obs_fail,
                            )
                        )

            elif i < len(expected_events):
                total_comparisons += 1
                exp_ev = expected_events[i]
                divergences.append(
                    DivergenceRecord(
                        category=DivergenceCategory.EVENT,
                        message=f"Missing observed event at seq {exp_ev.seq}: expected '{exp_ev.event_type.value}'",
                        seq=exp_ev.seq,
                        expected=exp_ev.event_type.value,
                        observed=None,
                        job_id=exp_ev.job_id,
                        attempt_id=exp_ev.attempt_id,
                        worker_id=exp_ev.worker_id,
                    )
                )

            else:
                total_comparisons += 1
                obs_ev = observed_events[i]
                divergences.append(
                    DivergenceRecord(
                        category=DivergenceCategory.EVENT,
                        message=f"Unexpected extra observed event at seq {obs_ev.seq}: observed '{obs_ev.event_type.value}'",
                        seq=obs_ev.seq,
                        expected=None,
                        observed=obs_ev.event_type.value,
                        job_id=obs_ev.job_id,
                        attempt_id=obs_ev.attempt_id,
                        worker_id=obs_ev.worker_id,
                    )
                )

        # Step 2: Reconstructed State Level Comparisons
        # 1. Run state comparison
        total_comparisons += 1
        if expected_replay.final_run_state != observed_replay.final_run_state:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.STATE,
                    message=f"Final run state mismatch: expected '{expected_replay.final_run_state}', observed '{observed_replay.final_run_state}'",
                    expected=expected_replay.final_run_state,
                    observed=observed_replay.final_run_state,
                )
            )

        # 2. Reconstructed Job States comparison
        all_jobs = sorted(
            set(expected_replay.reconstructed_job_states.keys())
            | set(observed_replay.reconstructed_job_states.keys())
        )
        for jid in all_jobs:
            total_comparisons += 1
            exp_js = expected_replay.reconstructed_job_states.get(jid)
            obs_js = observed_replay.reconstructed_job_states.get(jid)
            if exp_js != obs_js:
                cat = (
                    DivergenceCategory.OUTCOME
                    if exp_js in ("COMPLETED", "FAILED") and obs_js in ("COMPLETED", "FAILED")
                    else DivergenceCategory.STATE
                )
                divergences.append(
                    DivergenceRecord(
                        category=cat,
                        message=f"Job {jid} state mismatch: expected '{exp_js}', observed '{obs_js}'",
                        job_id=jid,
                        expected=exp_js,
                        observed=obs_js,
                    )
                )

        # 3. Retry counts & attempt counts
        total_comparisons += 1
        if expected_replay.retries != observed_replay.retries:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.RETRY,
                    message=f"Total retries mismatch: expected {expected_replay.retries}, observed {observed_replay.retries}",
                    expected=expected_replay.retries,
                    observed=observed_replay.retries,
                )
            )

        total_comparisons += 1
        if expected_replay.attempts != observed_replay.attempts:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.RETRY,
                    message=f"Total execution attempts mismatch: expected {expected_replay.attempts}, observed {observed_replay.attempts}",
                    expected=expected_replay.attempts,
                    observed=observed_replay.attempts,
                )
            )

        # 4. Worker States & Lifecycle counts
        all_workers = sorted(
            set(expected_replay.reconstructed_worker_states.keys())
            | set(observed_replay.reconstructed_worker_states.keys())
        )
        for wid in all_workers:
            total_comparisons += 1
            exp_ws = expected_replay.reconstructed_worker_states.get(wid)
            obs_ws = observed_replay.reconstructed_worker_states.get(wid)
            if exp_ws != obs_ws:
                divergences.append(
                    DivergenceRecord(
                        category=DivergenceCategory.WORKER,
                        message=f"Worker {wid} state mismatch: expected '{exp_ws}', observed '{obs_ws}'",
                        worker_id=wid,
                        expected=exp_ws,
                        observed=obs_ws,
                    )
                )

        total_comparisons += 1
        if expected_replay.worker_failures != observed_replay.worker_failures:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.WORKER,
                    message=f"Worker failures count mismatch: expected {expected_replay.worker_failures}, observed {observed_replay.worker_failures}",
                    expected=expected_replay.worker_failures,
                    observed=observed_replay.worker_failures,
                )
            )

        total_comparisons += 1
        if expected_replay.worker_replacements != observed_replay.worker_replacements:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.WORKER,
                    message=f"Worker replacements count mismatch: expected {expected_replay.worker_replacements}, observed {observed_replay.worker_replacements}",
                    expected=expected_replay.worker_replacements,
                    observed=observed_replay.worker_replacements,
                )
            )

        # 5. Summary metrics terminal outcomes
        exp_comp_jobs = expected_replay.summary_metrics.get("completed_jobs", 0)
        obs_comp_jobs = observed_replay.summary_metrics.get("completed_jobs", 0)
        total_comparisons += 1
        if exp_comp_jobs != obs_comp_jobs:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.OUTCOME,
                    message=f"Summary completed jobs mismatch: expected {exp_comp_jobs}, observed {obs_comp_jobs}",
                    expected=exp_comp_jobs,
                    observed=obs_comp_jobs,
                )
            )

        exp_fail_jobs = expected_replay.summary_metrics.get("failed_jobs", 0)
        obs_fail_jobs = observed_replay.summary_metrics.get("failed_jobs", 0)
        total_comparisons += 1
        if exp_fail_jobs != obs_fail_jobs:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.OUTCOME,
                    message=f"Summary failed jobs mismatch: expected {exp_fail_jobs}, observed {obs_fail_jobs}",
                    expected=exp_fail_jobs,
                    observed=obs_fail_jobs,
                )
            )

        # Build summary by category
        summary_by_category: dict[str, int] = {}
        for d in divergences:
            cat_name = d.category.value if isinstance(d.category, DivergenceCategory) else str(d.category)
            summary_by_category[cat_name] = summary_by_category.get(cat_name, 0) + 1

        first_divergence = divergences[0] if divergences else None

        return FidelityResult(
            equivalent=len(divergences) == 0,
            total_comparisons=total_comparisons,
            divergence_count=len(divergences),
            divergences=divergences,
            first_divergence=first_divergence,
            summary_by_category=summary_by_category,
            expected_events_count=len(expected_events),
            observed_events_count=len(observed_events),
        )

    @classmethod
    def compare_files(cls, expected_path: str | Path, observed_path: str | Path) -> FidelityResult:
        """Compare execution traces stored in two files."""
        return cls.compare(expected=expected_path, observed=observed_path)

    @classmethod
    def compare_replay_results(
        cls,
        expected: ReplayResult,
        observed: ReplayResult,
    ) -> FidelityResult:
        """Compare two ReplayResult instances directly at the state level."""
        divergences: list[DivergenceRecord] = []
        total_comparisons = 0

        total_comparisons += 1
        if expected.final_run_state != observed.final_run_state:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.STATE,
                    message=f"Final run state mismatch: expected '{expected.final_run_state}', observed '{observed.final_run_state}'",
                    expected=expected.final_run_state,
                    observed=observed.final_run_state,
                )
            )

        all_jobs = sorted(
            set(expected.reconstructed_job_states.keys()) | set(observed.reconstructed_job_states.keys())
        )
        for jid in all_jobs:
            total_comparisons += 1
            exp_js = expected.reconstructed_job_states.get(jid)
            obs_js = observed.reconstructed_job_states.get(jid)
            if exp_js != obs_js:
                cat = (
                    DivergenceCategory.OUTCOME
                    if exp_js in ("COMPLETED", "FAILED") and obs_js in ("COMPLETED", "FAILED")
                    else DivergenceCategory.STATE
                )
                divergences.append(
                    DivergenceRecord(
                        category=cat,
                        message=f"Job {jid} state mismatch: expected '{exp_js}', observed '{obs_js}'",
                        job_id=jid,
                        expected=exp_js,
                        observed=obs_js,
                    )
                )

        total_comparisons += 1
        if expected.retries != observed.retries:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.RETRY,
                    message=f"Total retries mismatch: expected {expected.retries}, observed {observed.retries}",
                    expected=expected.retries,
                    observed=observed.retries,
                )
            )

        total_comparisons += 1
        if expected.attempts != observed.attempts:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.RETRY,
                    message=f"Total execution attempts mismatch: expected {expected.attempts}, observed {observed.attempts}",
                    expected=expected.attempts,
                    observed=observed.attempts,
                )
            )

        all_workers = sorted(
            set(expected.reconstructed_worker_states.keys()) | set(observed.reconstructed_worker_states.keys())
        )
        for wid in all_workers:
            total_comparisons += 1
            exp_ws = expected.reconstructed_worker_states.get(wid)
            obs_ws = observed.reconstructed_worker_states.get(wid)
            if exp_ws != obs_ws:
                divergences.append(
                    DivergenceRecord(
                        category=DivergenceCategory.WORKER,
                        message=f"Worker {wid} state mismatch: expected '{exp_ws}', observed '{obs_ws}'",
                        worker_id=wid,
                        expected=exp_ws,
                        observed=obs_ws,
                    )
                )

        total_comparisons += 1
        if expected.worker_failures != observed.worker_failures:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.WORKER,
                    message=f"Worker failures count mismatch: expected {expected.worker_failures}, observed {observed.worker_failures}",
                    expected=expected.worker_failures,
                    observed=observed.worker_failures,
                )
            )

        total_comparisons += 1
        if expected.worker_replacements != observed.worker_replacements:
            divergences.append(
                DivergenceRecord(
                    category=DivergenceCategory.WORKER,
                    message=f"Worker replacements count mismatch: expected {expected.worker_replacements}, observed {observed.worker_replacements}",
                    expected=expected.worker_replacements,
                    observed=observed.worker_replacements,
                )
            )

        summary_by_category: dict[str, int] = {}
        for d in divergences:
            cat_name = d.category.value if isinstance(d.category, DivergenceCategory) else str(d.category)
            summary_by_category[cat_name] = summary_by_category.get(cat_name, 0) + 1

        first_divergence = divergences[0] if divergences else None

        return FidelityResult(
            equivalent=len(divergences) == 0,
            total_comparisons=total_comparisons,
            divergence_count=len(divergences),
            divergences=divergences,
            first_divergence=first_divergence,
            summary_by_category=summary_by_category,
            expected_events_count=expected.total_events,
            observed_events_count=observed.total_events,
        )

