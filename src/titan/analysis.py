"""Deterministic failure classification and root-cause analysis layer for Titan.

Consumes canonical structured execution traces, replay state, and divergence results
to deterministically classify failures, separate root causes from consequences,
reconstruct sequential causal chains, and evaluate recovery outcomes without mutating
underlying authoritative state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from titan.replay import (
    DivergenceCategory,
    DivergenceRecord,
    FidelityResult,
    ReplayEngine,
    ReplayFidelityEngine,
    ReplayJobStatus,
    ReplayResult,
    ReplayRunStatus,
    ReplayState,
    ReplayWorkerStatus,
)
from titan.trace import EventType, ExecutionTrace, TraceEvent

__all__ = [
    "FailureClass",
    "RecoveryOutcome",
    "FailureSeverity",
    "CausalRole",
    "CausalChainNode",
    "FailureRecord",
    "AnalysisReport",
    "FailureAnalyzer",
]


class FailureClass(str, Enum):
    """Deterministic taxonomy of Titan execution and validation failures."""

    WORKER_FAILURE = "WORKER_FAILURE"
    JOB_FAILURE = "JOB_FAILURE"
    LOST_EXECUTION = "LOST_EXECUTION"
    RETRY_EXHAUSTION = "RETRY_EXHAUSTION"
    OWNERSHIP_FAILURE = "OWNERSHIP_FAILURE"
    REPLAY_DIVERGENCE = "REPLAY_DIVERGENCE"
    RUN_FAILURE = "RUN_FAILURE"


class RecoveryOutcome(str, Enum):
    """Deterministic classification of recovery status for a detected failure."""

    RECOVERED = "RECOVERED"
    UNRECOVERED = "UNRECOVERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FailureSeverity(str, Enum):
    """Deterministic severity classification of a failure."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class CausalRole(str, Enum):
    """Role of an individual event node in a reconstructed failure causal chain."""

    ROOT_CAUSE = "ROOT_CAUSE"
    CONSEQUENCE = "CONSEQUENCE"
    RECOVERY_ACTION = "RECOVERY_ACTION"
    TERMINAL_OUTCOME = "TERMINAL_OUTCOME"


@dataclass(frozen=True)
class CausalChainNode:
    """Ordered event reference within a reconstructed failure causal chain.

    Attributes:
        seq: Canonical event sequence number establishing causality.
        event_type: Explicit lifecycle event type string.
        role: Causal role (ROOT_CAUSE, CONSEQUENCE, RECOVERY_ACTION, TERMINAL_OUTCOME).
        description: Human-readable deterministic explanation of this step.
        job_id: Associated job identifier, if applicable.
        attempt_id: Associated execution attempt identifier, if applicable.
        worker_id: Associated worker process identifier, if applicable.
    """

    seq: int
    event_type: str
    role: CausalRole | str
    description: str
    job_id: str | None = None
    attempt_id: int | None = None
    worker_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize causal chain node to dictionary."""
        return {
            "seq": self.seq,
            "event_type": self.event_type,
            "role": self.role.value if isinstance(self.role, CausalRole) else str(self.role),
            "description": self.description,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalChainNode:
        """Construct CausalChainNode from serialized dictionary."""
        role_val = data["role"]
        role = CausalRole(role_val) if role_val in CausalRole._value2member_map_ else role_val
        return cls(
            seq=data["seq"],
            event_type=data["event_type"],
            role=role,
            description=data["description"],
            job_id=data.get("job_id"),
            attempt_id=data.get("attempt_id"),
            worker_id=data.get("worker_id"),
        )


@dataclass(frozen=True)
class FailureRecord:
    """Structured, evidence-based failure record."""

    failure_id: str
    failure_class: FailureClass
    severity: FailureSeverity
    seq: int | None
    job_id: str | None
    attempt_id: int | None
    worker_id: str | None
    immediate_cause: str
    affected_entity: str
    recovery_action: str | None
    recovery_outcome: RecoveryOutcome
    final_outcome: str | None
    supporting_events: list[int]
    causal_chain: list[CausalChainNode]
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize failure record to a dictionary suitable for JSON export."""
        return {
            "failure_id": self.failure_id,
            "failure_class": (
                self.failure_class.value
                if isinstance(self.failure_class, FailureClass)
                else str(self.failure_class)
            ),
            "severity": (
                self.severity.value
                if isinstance(self.severity, FailureSeverity)
                else str(self.severity)
            ),
            "seq": self.seq,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "worker_id": self.worker_id,
            "immediate_cause": self.immediate_cause,
            "affected_entity": self.affected_entity,
            "recovery_action": self.recovery_action,
            "recovery_outcome": (
                self.recovery_outcome.value
                if isinstance(self.recovery_outcome, RecoveryOutcome)
                else str(self.recovery_outcome)
            ),
            "final_outcome": self.final_outcome,
            "supporting_events": list(self.supporting_events),
            "causal_chain": [node.to_dict() for node in self.causal_chain],
            "explanation": self.explanation,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailureRecord:
        """Construct FailureRecord from serialized dictionary."""
        fclass_val = data["failure_class"]
        fclass = (
            FailureClass(fclass_val)
            if fclass_val in FailureClass._value2member_map_
            else FailureClass[fclass_val]
        )
        sev_val = data["severity"]
        sev = (
            FailureSeverity(sev_val)
            if sev_val in FailureSeverity._value2member_map_
            else FailureSeverity[sev_val]
        )
        rec_val = data["recovery_outcome"]
        rec = (
            RecoveryOutcome(rec_val)
            if rec_val in RecoveryOutcome._value2member_map_
            else RecoveryOutcome[rec_val]
        )
        return cls(
            failure_id=data["failure_id"],
            failure_class=fclass,
            severity=sev,
            seq=data.get("seq"),
            job_id=data.get("job_id"),
            attempt_id=data.get("attempt_id"),
            worker_id=data.get("worker_id"),
            immediate_cause=data.get("immediate_cause", ""),
            affected_entity=data.get("affected_entity", ""),
            recovery_action=data.get("recovery_action"),
            recovery_outcome=rec,
            final_outcome=data.get("final_outcome"),
            supporting_events=list(data.get("supporting_events", [])),
            causal_chain=[CausalChainNode.from_dict(n) for n in data.get("causal_chain", [])],
            explanation=data.get("explanation", ""),
            details=dict(data.get("details", {})),
        )


@dataclass(frozen=True)
class AnalysisReport:
    """Complete deterministic failure analysis report for a Titan execution trace."""

    valid: bool
    overall_status: str
    total_events: int
    root_failures_count: int
    root_failures: list[FailureRecord]
    consequences_count: int
    consequences: list[FailureRecord]
    failure_classes_summary: dict[str, int]
    affected_jobs: list[str]
    affected_workers: list[str]
    recovery_summary: dict[str, int]
    reconstructed_run_state: str
    validation_errors: list[str]
    divergences_count: int = 0
    divergences: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize analysis report to dictionary suitable for JSON export."""
        return {
            "valid": self.valid,
            "overall_status": self.overall_status,
            "total_events": self.total_events,
            "root_failures_count": self.root_failures_count,
            "root_failures": [rf.to_dict() for rf in self.root_failures],
            "consequences_count": self.consequences_count,
            "consequences": [c.to_dict() for c in self.consequences],
            "failure_classes_summary": self.failure_classes_summary,
            "affected_jobs": self.affected_jobs,
            "affected_workers": self.affected_workers,
            "recovery_summary": self.recovery_summary,
            "reconstructed_run_state": self.reconstructed_run_state,
            "validation_errors": self.validation_errors,
            "divergences_count": self.divergences_count,
            "divergences": self.divergences,
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize analysis report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisReport:
        """Construct AnalysisReport from serialized dictionary."""
        return cls(
            valid=data["valid"],
            overall_status=data["overall_status"],
            total_events=data["total_events"],
            root_failures_count=data["root_failures_count"],
            root_failures=[FailureRecord.from_dict(rf) for rf in data.get("root_failures", [])],
            consequences_count=data.get("consequences_count", 0),
            consequences=[FailureRecord.from_dict(c) for c in data.get("consequences", [])],
            failure_classes_summary=dict(data.get("failure_classes_summary", {})),
            affected_jobs=list(data.get("affected_jobs", [])),
            affected_workers=list(data.get("affected_workers", [])),
            recovery_summary=dict(data.get("recovery_summary", {})),
            reconstructed_run_state=data.get("reconstructed_run_state", "UNKNOWN"),
            validation_errors=list(data.get("validation_errors", [])),
            divergences_count=data.get("divergences_count", 0),
            divergences=list(data.get("divergences", [])),
        )


class FailureAnalyzer:
    """Deterministic failure classifier and root-cause analysis engine."""

    @classmethod
    def analyze(
        cls,
        trace_input: ExecutionTrace | Sequence[TraceEvent] | Sequence[dict[str, Any]] | str | Path,
        expected_trace: (
            ExecutionTrace
            | Sequence[TraceEvent]
            | Sequence[dict[str, Any]]
            | str
            | Path
            | None
        ) = None,
    ) -> AnalysisReport:
        """Perform comprehensive deterministic failure and root-cause analysis.

        Args:
            trace_input: Observed execution trace to analyze.
            expected_trace: Optional reference trace to detect replay divergence.

        Returns:
            AnalysisReport containing classified root failures, causal chains,
            consequences, and deterministic recovery evaluation.
        """
        # 1. Normalize and replay trace using authoritative ReplayEngine
        try:
            events = ReplayEngine._normalize_trace(trace_input)
        except Exception as exc:
            return AnalysisReport(
                valid=False,
                overall_status="INVALID_TRACE",
                total_events=0,
                root_failures_count=0,
                root_failures=[],
                consequences_count=0,
                consequences=[],
                failure_classes_summary={},
                affected_jobs=[],
                affected_workers=[],
                recovery_summary={"RECOVERED": 0, "UNRECOVERED": 0, "NOT_APPLICABLE": 0},
                reconstructed_run_state="NOT_STARTED",
                validation_errors=[f"Failed to load or parse execution trace: {exc}"],
                divergences_count=0,
                divergences=[],
            )

        replay_result = ReplayEngine.replay(events)
        if not replay_result.valid:
            # Structurally invalid trace: defer to existing replay validation result
            return AnalysisReport(
                valid=False,
                overall_status="INVALID_TRACE",
                total_events=len(events),
                root_failures_count=0,
                root_failures=[],
                consequences_count=0,
                consequences=[],
                failure_classes_summary={},
                affected_jobs=[],
                affected_workers=[],
                recovery_summary={"RECOVERED": 0, "UNRECOVERED": 0, "NOT_APPLICABLE": 0},
                reconstructed_run_state=replay_result.final_run_state,
                validation_errors=list(replay_result.validation_errors),
                divergences_count=0,
                divergences=[],
            )

        # 2. Check for replay divergence if expected trace was supplied
        divergence_records: list[FailureRecord] = []
        raw_divergences: list[dict[str, Any]] = []
        if expected_trace is not None:
            try:
                fidelity_result = ReplayFidelityEngine.compare(expected_trace, events)
                if not fidelity_result.equivalent:
                    for idx, div in enumerate(fidelity_result.divergences, 1):
                        raw_divergences.append(div.to_dict())
                        entity = (
                            f"job:{div.job_id}"
                            if div.job_id
                            else f"worker:{div.worker_id}"
                            if div.worker_id
                            else "trace"
                        )
                        div_node = CausalChainNode(
                            seq=div.seq if div.seq is not None else 0,
                            event_type="REPLAY_DIVERGENCE",
                            role=CausalRole.ROOT_CAUSE,
                            description=div.message,
                            job_id=div.job_id,
                            attempt_id=div.attempt_id,
                            worker_id=div.worker_id,
                        )
                        divergence_records.append(
                            FailureRecord(
                                failure_id=f"fail-div-{idx:04d}",
                                failure_class=FailureClass.REPLAY_DIVERGENCE,
                                severity=FailureSeverity.ERROR,
                                seq=div.seq,
                                job_id=div.job_id,
                                attempt_id=div.attempt_id,
                                worker_id=div.worker_id,
                                immediate_cause=div.message,
                                affected_entity=entity,
                                recovery_action=None,
                                recovery_outcome=RecoveryOutcome.NOT_APPLICABLE,
                                final_outcome=None,
                                supporting_events=[div.seq] if div.seq is not None else [],
                                causal_chain=[div_node],
                                explanation=f"Replay divergence detected ({div.category.value}): {div.message}",
                                details=div.details,
                            )
                        )
            except Exception as exc:
                raw_divergences.append({"error": f"Fidelity comparison failed: {exc}"})

        # 3. Categorize trace events by entity and lifecycle
        root_failures: list[FailureRecord] = []
        consequences: list[FailureRecord] = []
        affected_jobs_set: set[str] = set()
        affected_workers_set: set[str] = set()

        worker_failed_events: list[TraceEvent] = []
        worker_replaced_events: list[TraceEvent] = []
        job_lost_events: list[TraceEvent] = []
        retry_scheduled_events: list[TraceEvent] = []
        job_failed_events: list[TraceEvent] = []
        job_completed_events: list[TraceEvent] = []
        job_assigned_events: list[TraceEvent] = []

        for ev in events:
            if ev.event_type == EventType.WORKER_FAILED:
                worker_failed_events.append(ev)
            elif ev.event_type == EventType.WORKER_REPLACED:
                worker_replaced_events.append(ev)
            elif ev.event_type == EventType.JOB_LOST:
                job_lost_events.append(ev)
            elif ev.event_type == EventType.RETRY_SCHEDULED:
                retry_scheduled_events.append(ev)
            elif ev.event_type == EventType.JOB_FAILED:
                job_failed_events.append(ev)
            elif ev.event_type == EventType.JOB_COMPLETED:
                job_completed_events.append(ev)
            elif ev.event_type in (EventType.JOB_ASSIGNED, EventType.JOB_REASSIGNED):
                job_assigned_events.append(ev)

        # Index terminal job states from replay result
        job_terminal_states = replay_result.reconstructed_job_states

        # Set of jobs whose failures/losses are causally linked to worker failures
        handled_job_ids_from_workers: set[str] = set()
        failure_idx = 1
        consequence_idx = 1

        # 4. Analyze WORKER_FAILURE root causes and their causal chains
        for wf_ev in sorted(worker_failed_events, key=lambda e: e.seq):
            w_id = wf_ev.worker_id or "unknown-worker"
            affected_workers_set.add(w_id)
            exit_code = wf_ev.data.get("exit_code")
            cause = f"Worker {w_id} exited unexpectedly with exit code {exit_code}"

            # Identify all JOB_LOST events attributable to this worker failure
            # In Titan's coordinator, in-flight jobs on w_id are marked JOB_LOST immediately after WORKER_FAILED
            associated_losses = [
                ev for ev in job_lost_events
                if ev.worker_id == w_id and ev.seq > wf_ev.seq
            ]

            # Build causal chain nodes
            chain_nodes: list[CausalChainNode] = [
                CausalChainNode(
                    seq=wf_ev.seq,
                    event_type=wf_ev.event_type.value,
                    role=CausalRole.ROOT_CAUSE,
                    description=cause,
                    worker_id=w_id,
                )
            ]
            supporting_seqs: list[int] = [wf_ev.seq]

            # Find replacement worker, if any
            rep_ev = next(
                (ev for ev in worker_replaced_events if ev.data.get("replaced_worker_id") == w_id),
                None,
            )
            if rep_ev is not None:
                chain_nodes.append(
                    CausalChainNode(
                        seq=rep_ev.seq,
                        event_type=rep_ev.event_type.value,
                        role=CausalRole.RECOVERY_ACTION,
                        description=f"Replacement worker {rep_ev.worker_id} spawned for {w_id}",
                        worker_id=rep_ev.worker_id,
                    )
                )
                supporting_seqs.append(rep_ev.seq)
                if rep_ev.worker_id:
                    affected_workers_set.add(rep_ev.worker_id)

            recovery_actions_list: list[str] = []
            if rep_ev is not None:
                recovery_actions_list.append(f"WORKER_REPLACED({rep_ev.worker_id})")

            all_affected_jobs_recovered = True
            affected_jobs_for_this_worker: set[str] = set()

            for lost_ev in associated_losses:
                j_id = lost_ev.job_id or "unknown-job"
                att_id = lost_ev.attempt_id or 1
                affected_jobs_set.add(j_id)
                affected_jobs_for_this_worker.add(j_id)
                handled_job_ids_from_workers.add(j_id)
                supporting_seqs.append(lost_ev.seq)

                # Add consequence node
                loss_desc = f"Execution attempt {att_id} lost on failed worker {w_id}"
                chain_nodes.append(
                    CausalChainNode(
                        seq=lost_ev.seq,
                        event_type=lost_ev.event_type.value,
                        role=CausalRole.CONSEQUENCE,
                        description=loss_desc,
                        job_id=j_id,
                        attempt_id=att_id,
                        worker_id=w_id,
                    )
                )

                # Check if retry was scheduled
                retry_ev = next(
                    (
                        ev for ev in retry_scheduled_events
                        if ev.job_id == j_id and ev.attempt_id == att_id + 1 and ev.seq > lost_ev.seq
                    ),
                    None,
                )
                if retry_ev is not None:
                    chain_nodes.append(
                        CausalChainNode(
                            seq=retry_ev.seq,
                            event_type=retry_ev.event_type.value,
                            role=CausalRole.RECOVERY_ACTION,
                            description=f"Retry attempt {retry_ev.attempt_id} scheduled for {j_id}",
                            job_id=j_id,
                            attempt_id=retry_ev.attempt_id,
                        )
                    )
                    supporting_seqs.append(retry_ev.seq)
                    recovery_actions_list.append(f"RETRY_SCHEDULED({j_id}#att{retry_ev.attempt_id})")

                    # Check reassignment / subsequent attempts
                    reassign_ev = next(
                        (
                            ev for ev in job_assigned_events
                            if ev.job_id == j_id and ev.attempt_id == retry_ev.attempt_id and ev.seq > retry_ev.seq
                        ),
                        None,
                    )
                    if reassign_ev is not None:
                        chain_nodes.append(
                            CausalChainNode(
                                seq=reassign_ev.seq,
                                event_type=reassign_ev.event_type.value,
                                role=CausalRole.RECOVERY_ACTION,
                                description=f"Retry attempt {retry_ev.attempt_id} assigned to worker {reassign_ev.worker_id}",
                                job_id=j_id,
                                attempt_id=retry_ev.attempt_id,
                                worker_id=reassign_ev.worker_id,
                            )
                        )
                        supporting_seqs.append(reassign_ev.seq)

                # Evaluate final outcome for this job
                final_job_status = job_terminal_states.get(j_id, "UNKNOWN")
                term_ev = next(
                    (
                        ev for ev in events
                        if ev.job_id == j_id
                        and ev.event_type in (EventType.JOB_COMPLETED, EventType.JOB_FAILED)
                        and ev.seq > lost_ev.seq
                    ),
                    None,
                )
                if term_ev is not None:
                    supporting_seqs.append(term_ev.seq)
                    term_desc = (
                        f"Job {j_id} completed successfully on attempt {term_ev.attempt_id}"
                        if term_ev.event_type == EventType.JOB_COMPLETED
                        else f"Job {j_id} permanently failed on attempt {term_ev.attempt_id}"
                    )
                    chain_nodes.append(
                        CausalChainNode(
                            seq=term_ev.seq,
                            event_type=term_ev.event_type.value,
                            role=CausalRole.TERMINAL_OUTCOME,
                            description=term_desc,
                            job_id=j_id,
                            attempt_id=term_ev.attempt_id,
                            worker_id=term_ev.worker_id,
                        )
                    )

                job_rec_outcome = (
                    RecoveryOutcome.RECOVERED
                    if final_job_status == "COMPLETED"
                    else RecoveryOutcome.UNRECOVERED
                )
                if job_rec_outcome != RecoveryOutcome.RECOVERED:
                    all_affected_jobs_recovered = False

                # Create explicit downstream consequence record for this lost execution
                consequences.append(
                    FailureRecord(
                        failure_id=f"cons-{consequence_idx:04d}",
                        failure_class=FailureClass.LOST_EXECUTION,
                        severity=FailureSeverity.WARNING,
                        seq=lost_ev.seq,
                        job_id=j_id,
                        attempt_id=att_id,
                        worker_id=w_id,
                        immediate_cause=f"In-flight execution lost due to crash of worker {w_id}",
                        affected_entity=f"attempt:{j_id}#{att_id}",
                        recovery_action=(
                            f"Retry attempt {att_id + 1} scheduled"
                            if retry_ev is not None
                            else "No retry scheduled"
                        ),
                        recovery_outcome=job_rec_outcome,
                        final_outcome=final_job_status,
                        supporting_events=[wf_ev.seq, lost_ev.seq] + ([term_ev.seq] if term_ev else []),
                        causal_chain=[
                            CausalChainNode(
                                seq=wf_ev.seq,
                                event_type=wf_ev.event_type.value,
                                role=CausalRole.ROOT_CAUSE,
                                description=cause,
                                worker_id=w_id,
                            ),
                            CausalChainNode(
                                seq=lost_ev.seq,
                                event_type=lost_ev.event_type.value,
                                role=CausalRole.CONSEQUENCE,
                                description=loss_desc,
                                job_id=j_id,
                                attempt_id=att_id,
                                worker_id=w_id,
                            ),
                        ] + ([CausalChainNode(
                            seq=term_ev.seq,
                            event_type=term_ev.event_type.value,
                            role=CausalRole.TERMINAL_OUTCOME,
                            description=term_desc,
                            job_id=j_id,
                            attempt_id=term_ev.attempt_id,
                            worker_id=term_ev.worker_id,
                        )] if term_ev else []),
                        explanation=(
                            f"Attempt {att_id} of job {j_id} was lost when worker {w_id} crashed. "
                            f"Outcome: {job_rec_outcome.value} ({final_job_status})."
                        ),
                        details={"root_worker": w_id, "root_seq": wf_ev.seq},
                    )
                )
                consequence_idx += 1

                # If this job permanently failed because max retries were exceeded, also record
                # RETRY_EXHAUSTION as a consequence
                if final_job_status == "FAILED":
                    consequences.append(
                        FailureRecord(
                            failure_id=f"cons-{consequence_idx:04d}",
                            failure_class=FailureClass.RETRY_EXHAUSTION,
                            severity=FailureSeverity.ERROR,
                            seq=term_ev.seq if term_ev else lost_ev.seq,
                            job_id=j_id,
                            attempt_id=term_ev.attempt_id if term_ev else att_id,
                            worker_id=w_id,
                            immediate_cause=f"Job {j_id} exhausted permitted retry attempts",
                            affected_entity=f"job:{j_id}",
                            recovery_action="None (retries exhausted)",
                            recovery_outcome=RecoveryOutcome.UNRECOVERED,
                            final_outcome="FAILED",
                            supporting_events=[wf_ev.seq, lost_ev.seq] + ([term_ev.seq] if term_ev else []),
                            causal_chain=sorted(chain_nodes, key=lambda n: n.seq),
                            explanation=f"Job {j_id} failed permanently following retry exhaustion after worker {w_id} crashed.",
                            details={"root_worker": w_id, "job_id": j_id},
                        )
                    )
                    consequence_idx += 1

            # Determine worker failure overall recovery outcome
            # If no in-flight jobs were lost, recovery is successful if replacement/run completed
            overall_rec = (
                RecoveryOutcome.RECOVERED
                if all_affected_jobs_recovered and replay_result.final_run_state == "COMPLETED"
                else RecoveryOutcome.UNRECOVERED
            )

            # Sort causal chain strictly by sequence number
            sorted_chain = sorted(chain_nodes, key=lambda n: n.seq)
            sorted_supporting = sorted(set(supporting_seqs))

            root_failures.append(
                FailureRecord(
                    failure_id=f"fail-{failure_idx:04d}",
                    failure_class=FailureClass.WORKER_FAILURE,
                    severity=FailureSeverity.CRITICAL if overall_rec == RecoveryOutcome.UNRECOVERED else FailureSeverity.ERROR,
                    seq=wf_ev.seq,
                    job_id=None,
                    attempt_id=None,
                    worker_id=w_id,
                    immediate_cause=cause,
                    affected_entity=f"worker:{w_id}",
                    recovery_action=", ".join(recovery_actions_list) if recovery_actions_list else "None",
                    recovery_outcome=overall_rec,
                    final_outcome=replay_result.final_run_state,
                    supporting_events=sorted_supporting,
                    causal_chain=sorted_chain,
                    explanation=(
                        f"Worker {w_id} crashed unexpectedly at seq {wf_ev.seq}. "
                        f"{len(associated_losses)} in-flight job(s) lost. "
                        f"Recovery outcome: {overall_rec.value}."
                    ),
                    details={
                        "exit_code": exit_code,
                        "affected_jobs_count": len(associated_losses),
                        "affected_jobs": sorted(affected_jobs_for_this_worker),
                        "replaced": rep_ev is not None,
                        "replacement_worker": rep_ev.worker_id if rep_ev else None,
                    },
                )
            )
            failure_idx += 1

        # 5. Analyze standalone JOB_FAILURE and RETRY_EXHAUSTION (independent of worker crash)
        for jf_ev in sorted(job_failed_events, key=lambda e: e.seq):
            j_id = jf_ev.job_id or "unknown-job"
            if j_id in handled_job_ids_from_workers:
                # Already captured causally under WORKER_FAILURE
                continue

            att_id = jf_ev.attempt_id or 1
            w_id = jf_ev.worker_id
            affected_jobs_set.add(j_id)
            if w_id:
                affected_workers_set.add(w_id)

            err_msg = jf_ev.data.get("error", "Task execution error")
            max_retries_exceeded = bool(jf_ev.data.get("max_retries_exceeded", False))

            # Build causal chain for this job failure
            job_chain: list[CausalChainNode] = [
                CausalChainNode(
                    seq=jf_ev.seq,
                    event_type=jf_ev.event_type.value,
                    role=CausalRole.ROOT_CAUSE,
                    description=f"Attempt {att_id} failed: {err_msg}",
                    job_id=j_id,
                    attempt_id=att_id,
                    worker_id=w_id,
                )
            ]
            supporting_seqs = [jf_ev.seq]

            # Check if retry followed
            retry_ev = next(
                (
                    ev for ev in retry_scheduled_events
                    if ev.job_id == j_id and ev.attempt_id == att_id + 1 and ev.seq > jf_ev.seq
                ),
                None,
            )

            final_job_status = job_terminal_states.get(j_id, "FAILED")
            term_ev = next(
                (
                    ev for ev in events
                    if ev.job_id == j_id
                    and ev.event_type in (EventType.JOB_COMPLETED, EventType.JOB_FAILED)
                    and ev.seq > jf_ev.seq
                ),
                None,
            )

            if retry_ev is not None:
                job_chain.append(
                    CausalChainNode(
                        seq=retry_ev.seq,
                        event_type=retry_ev.event_type.value,
                        role=CausalRole.RECOVERY_ACTION,
                        description=f"Retry attempt {retry_ev.attempt_id} scheduled for {j_id}",
                        job_id=j_id,
                        attempt_id=retry_ev.attempt_id,
                    )
                )
                supporting_seqs.append(retry_ev.seq)

            if term_ev is not None:
                supporting_seqs.append(term_ev.seq)
                term_desc = (
                    f"Job {j_id} completed successfully on attempt {term_ev.attempt_id}"
                    if term_ev.event_type == EventType.JOB_COMPLETED
                    else f"Job {j_id} permanently failed on attempt {term_ev.attempt_id}"
                )
                job_chain.append(
                    CausalChainNode(
                        seq=term_ev.seq,
                        event_type=term_ev.event_type.value,
                        role=CausalRole.TERMINAL_OUTCOME,
                        description=term_desc,
                        job_id=j_id,
                        attempt_id=term_ev.attempt_id,
                        worker_id=term_ev.worker_id,
                    )
                )

            is_recovered = final_job_status == "COMPLETED"
            rec_outcome = (
                RecoveryOutcome.RECOVERED if is_recovered else RecoveryOutcome.UNRECOVERED
            )

            # If retry exhausted, classify as RETRY_EXHAUSTION; else JOB_FAILURE
            fclass = (
                FailureClass.RETRY_EXHAUSTION
                if (max_retries_exceeded or not is_recovered)
                else FailureClass.JOB_FAILURE
            )

            root_failures.append(
                FailureRecord(
                    failure_id=f"fail-{failure_idx:04d}",
                    failure_class=fclass,
                    severity=FailureSeverity.ERROR,
                    seq=jf_ev.seq,
                    job_id=j_id,
                    attempt_id=att_id,
                    worker_id=w_id,
                    immediate_cause=err_msg,
                    affected_entity=f"job:{j_id}",
                    recovery_action=(
                        f"Retry attempt {att_id + 1} scheduled"
                        if retry_ev is not None
                        else "No retry permitted"
                    ),
                    recovery_outcome=rec_outcome,
                    final_outcome=final_job_status,
                    supporting_events=sorted(set(supporting_seqs)),
                    causal_chain=sorted(job_chain, key=lambda n: n.seq),
                    explanation=(
                        f"Job {j_id} encountered {fclass.value} at seq {jf_ev.seq}: {err_msg}. "
                        f"Outcome: {rec_outcome.value}."
                    ),
                    details={
                        "max_retries_exceeded": max_retries_exceeded,
                        "attempt_id": att_id,
                    },
                )
            )
            failure_idx += 1

        # 6. Check for unhandled LOST_EXECUTION (e.g. without prior WORKER_FAILED)
        for lost_ev in job_lost_events:
            j_id = lost_ev.job_id or "unknown-job"
            if j_id not in handled_job_ids_from_workers:
                affected_jobs_set.add(j_id)
                final_job_status = job_terminal_states.get(j_id, "UNKNOWN")
                root_failures.append(
                    FailureRecord(
                        failure_id=f"fail-{failure_idx:04d}",
                        failure_class=FailureClass.LOST_EXECUTION,
                        severity=FailureSeverity.ERROR,
                        seq=lost_ev.seq,
                        job_id=j_id,
                        attempt_id=lost_ev.attempt_id,
                        worker_id=lost_ev.worker_id,
                        immediate_cause=lost_ev.data.get("reason", "Execution lost"),
                        affected_entity=f"job:{j_id}",
                        recovery_action=None,
                        recovery_outcome=(
                            RecoveryOutcome.RECOVERED
                            if final_job_status == "COMPLETED"
                            else RecoveryOutcome.UNRECOVERED
                        ),
                        final_outcome=final_job_status,
                        supporting_events=[lost_ev.seq],
                        causal_chain=[
                            CausalChainNode(
                                seq=lost_ev.seq,
                                event_type=lost_ev.event_type.value,
                                role=CausalRole.ROOT_CAUSE,
                                description=f"Execution lost for {j_id}",
                                job_id=j_id,
                                attempt_id=lost_ev.attempt_id,
                                worker_id=lost_ev.worker_id,
                            )
                        ],
                        explanation=f"Lost execution detected for job {j_id} without prior worker failure.",
                    )
                )
                failure_idx += 1

        # 7. Check for RUN_FAILURE (overall run failed unrecovered)
        if replay_result.final_run_state != "COMPLETED":
            root_failures.append(
                FailureRecord(
                    failure_id=f"fail-{failure_idx:04d}",
                    failure_class=FailureClass.RUN_FAILURE,
                    severity=FailureSeverity.CRITICAL,
                    seq=events[-1].seq if events else 0,
                    job_id=None,
                    attempt_id=None,
                    worker_id=None,
                    immediate_cause="Workload execution ended in non-completed terminal state",
                    affected_entity="run",
                    recovery_action=None,
                    recovery_outcome=RecoveryOutcome.UNRECOVERED,
                    final_outcome=replay_result.final_run_state,
                    supporting_events=[events[-1].seq] if events else [],
                    causal_chain=[
                        CausalChainNode(
                            seq=events[-1].seq if events else 0,
                            event_type=events[-1].event_type.value if events else "RUN_TERMINATED",
                            role=CausalRole.TERMINAL_OUTCOME,
                            description=f"Run reached terminal state: {replay_result.final_run_state}",
                        )
                    ],
                    explanation=f"Run terminated with state {replay_result.final_run_state}.",
                )
            )
            failure_idx += 1

        # Add any divergence records into root failures
        root_failures.extend(divergence_records)

        # 8. Sort root failures deterministically by sequence number and failure_id
        root_failures.sort(key=lambda rf: (rf.seq if rf.seq is not None else -1, rf.failure_id))
        consequences.sort(key=lambda c: (c.seq if c.seq is not None else -1, c.failure_id))

        # 9. Compute failure classes summary (including both root failures and consequences)
        failure_classes_summary: dict[str, int] = {}
        for rf in root_failures:
            fc_val = rf.failure_class.value
            failure_classes_summary[fc_val] = failure_classes_summary.get(fc_val, 0) + 1
        for c in consequences:
            fc_val = c.failure_class.value
            failure_classes_summary[fc_val] = failure_classes_summary.get(fc_val, 0) + 1

        # Sort summary deterministically
        sorted_classes_summary = {k: failure_classes_summary[k] for k in sorted(failure_classes_summary.keys())}

        # 10. Compute recovery summary
        rec_summary = {"RECOVERED": 0, "UNRECOVERED": 0, "NOT_APPLICABLE": 0}
        for rf in root_failures:
            ro_val = rf.recovery_outcome.value
            if ro_val in rec_summary:
                rec_summary[ro_val] += 1

        # 11. Determine overall status
        if divergence_records:
            overall_status = "DIVERGENT"
        elif not root_failures:
            overall_status = "CLEAN"
        elif rec_summary["UNRECOVERED"] > 0:
            overall_status = "UNRECOVERED"
        elif rec_summary["RECOVERED"] > 0 and rec_summary["UNRECOVERED"] == 0:
            overall_status = "RECOVERED"
        else:
            overall_status = "NOT_APPLICABLE"

        return AnalysisReport(
            valid=True,
            overall_status=overall_status,
            total_events=len(events),
            root_failures_count=len(root_failures),
            root_failures=root_failures,
            consequences_count=len(consequences),
            consequences=consequences,
            failure_classes_summary=sorted_classes_summary,
            affected_jobs=sorted(affected_jobs_set),
            affected_workers=sorted(affected_workers_set),
            recovery_summary=rec_summary,
            reconstructed_run_state=replay_result.final_run_state,
            validation_errors=[],
            divergences_count=len(divergence_records),
            divergences=raw_divergences,
        )

    @classmethod
    def analyze_file(
        cls,
        path: str | Path,
        expected_path: str | Path | None = None,
    ) -> AnalysisReport:
        """Load execution trace from file and perform failure analysis."""
        return cls.analyze(path, expected_trace=expected_path)
