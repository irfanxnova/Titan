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
