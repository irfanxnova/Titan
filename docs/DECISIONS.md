# Architecture Decision Records (ADR)

This document records the architectural decisions made for the Titan project. Each record details the context, the decision taken, and the consequences.

---

## ADR-001: Minimal Repository Foundation and Runtime Selection

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Milestone 1 requires establishing a reproducible, minimal engineering foundation without introducing unnecessary technologies or dependencies. The host environment contains Python 3.10.11, Node.js v24, Java 22, Git, and pytest. Docker, Go, and Rust are not installed.
- **Decision**: 
  1. Select Python 3.10 as the primary language for Titan.
  2. Implement Milestone 1 using exclusively standard library modules (`argparse`, `dataclasses`, `os`, `sys`, `unittest`).
  3. Ensure compatibility with both standard `unittest` and `pytest` runners without requiring additional build tools.
- **Consequences**:
  - *Positive*: Zero installation overhead, instant onboarding, highly auditable code, portable across developer environments.
  - *Negative*: Performance is lower than compiled languages (C++/Rust/Go); compute-heavy synthetic jobs must account for Python interpreter characteristics.

---

## ADR-002: Rejection of Premature Infrastructure

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Common distributed systems projects frequently incorporate heavy third-party infrastructure (Kafka, Kubernetes, Redis, Docker, cloud services) before defining their primary research problems.
- **Decision**: 
  1. Explicitly ban Kafka, Kubernetes, Redis, Docker, and external message brokers from the initial architecture.
  2. Forbid cloud-only deployments and third-party database engines at this stage.
  3. Defer AI/ML models until baseline statistical/heuristic policies are established and empirical need is demonstrated.
- **Consequences**:
  - *Positive*: Keeps the codebase lean, understandable, directly debuggable, and tightly focused on the research question. Avoids operational complexity and hidden failure modes of third-party platforms.
  - *Negative*: We cannot rely on off-the-shelf distributed state management or orchestration; we must build only the minimal primitives strictly required by our experiments.

---

## ADR-003: Intentional Minimality of Initial Implementation

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: There is a common temptation in systems engineering to write speculative "placeholder" interfaces, mock distributed nodes, or stub schedulers before experimental requirements are formalized.
- **Decision**: 
  1. Milestone 1 includes strictly an application entry point (`titan.cli`), an immutable configuration dataclass (`titan.config`), and test verification.
  2. No distributed abstractions, workers, schedulers, or storage engines will be mocked or pre-coded.
- **Consequences**:
  - *Positive*: Eliminates phantom abstractions that would otherwise need refactoring once real workload requirements emerge. Ensures every added line of code serves an active purpose.
  - *Negative*: The repository contains only foundational plumbing at this stage and cannot yet execute distributed experiments.

---

## ADR-004: Strict Separation of Confirmed vs. Speculative Architecture

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Architectural documentation often drifts into aspirational descriptions of components that do not actually exist, misleading researchers and contributors.
- **Decision**: 
  1. Maintain explicit boundaries in `ARCHITECTURE.md` between Confirmed Architecture, Planned Architecture, and Unresolved Decisions.
  2. No component may be documented as confirmed until its code and tests are merged into the repository.
- **Consequences**:
  - *Positive*: High document integrity and trustworthiness. Readers know exactly what the system is currently capable of executing.
  - *Negative*: Requires continuous document updates as milestones are completed.

---

## ADR-005: Multi-Process Baseline Runtime Architecture

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Milestone 2 requires implementing the first minimal working distributed runtime for Titan to establish a static baseline. Workers could theoretically be implemented as threads, async coroutines, or separate OS processes.
- **Decision**:
  1. Implement workers as separate OS processes using Python's standard library `multiprocessing` with the `spawn` context.
  2. Use standard library `multiprocessing.Queue` for inter-process communication (`job_queue` and `result_queue`).
  3. Prohibit threading for worker execution to avoid Global Interpreter Lock (GIL) concurrency bottlenecks and to guarantee genuine memory isolation between workers.
- **Consequences**:
  - *Positive*: True CPU parallelism across multiple hardware cores; crash isolation between worker processes; no third-party daemons required.
  - *Negative*: IPC serialization overhead via pickle on queues; process creation overhead during initial startup.

---

## ADR-006: At-Most-Once Delivery and Absence of Premature Recovery in Milestone 2

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: In distributed systems, worker crash recovery, message acknowledgment, and redelivery mechanisms add considerable architectural complexity. Implementing complex recovery before establishing a clean static baseline risks coupling failure semantics with baseline measurements.
- **Decision**:
  1. Milestone 2 implements strict at-most-once delivery semantics.
  2. If a worker process terminates mid-execution, its active job is lost and not automatically recovered or redelivered.
  3. The coordinator remains resilient to worker termination: it does not crash, drains surviving worker results, and accounts for missing jobs as uncompleted/failed in the metrics report.
  4. Explicitly document this absence of automatic recovery as a known system limitation.
- **Consequences**:
  - *Positive*: The baseline remains simple, verifiable, and transparent. We avoid premature speculative recovery protocols.
  - *Negative*: The runtime is not yet fault-tolerant against crash-stop failures; fault tolerance remains a planned topic for Milestone 4.

---

## ADR-007: Continued Rejection of External Message Brokers (Kafka, Redis) and Databases

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Standard distributed systems implementations often adopt external brokers (e.g., Apache Kafka, RabbitMQ, Redis) for task distribution.
- **Decision**:
  1. Continue using standard library IPC (`multiprocessing.Queue`) exclusively.
  2. Continue banning Kafka, Redis, and external databases.
- **Consequences**:
  - *Positive*: Zero operational dependencies; experiments run locally in milliseconds with deterministic process control. We observe the execution policy rather than third-party broker queuing algorithms.
  - *Negative*: Task queues cannot scale across physically separate servers without networking extensions.

---

## ADR-008: At-Least-Once Processing and Rejection of Exactly-Once Execution Claims

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Milestone 3 implements failure recovery when a worker disappears while executing a job. In distributed systems literature, systems frequently conflate "at-least-once processing", "effectively-once processing", and "exactly-once execution".
- **Decision**:
  1. Titan implements **at-least-once processing semantics**. When a worker dies, in-flight jobs are requeued and re-executed. A job's computation may physically execute more than once across failures.
  2. Titan enforces **at-most-one final successful result** per unique job ID at the coordinator via idempotent deduplication. Stale or duplicate results arriving from previous attempts are safely discarded.
  3. Titan explicitly **rejects** claiming "exactly-once execution" or "exactly-once processing". In any distributed crash-stop model with non-transactional external computation, true exactly-once physical execution is impossible.
- **Consequences**:
  - *Positive*: High scientific and engineering precision; prevents misleading claims; guarantees auditable state transitions without hidden edge-case anomalies.
  - *Negative*: Workloads that produce external side-effects must be idempotent, as an attempt may partially or completely execute before an acknowledgment failure causes a retry.

---

## ADR-009: In-Flight Job Ownership Tracking and Deterministic Worker Failure Recovery

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: To recover work when a worker dies, the system must know which jobs were held by that worker without relying merely on inspecting whether the queue is empty.
- **Decision**:
  1. Introduce explicit ownership tracking: workers emit a `JobAcquired` event immediately upon dequeuing a job.
  2. The coordinator maintains an in-flight mapping (`_in_flight[worker_id][job_id] = Job`).
  3. The coordinator uses native OS process monitoring (`process.is_alive()` and `process.exitcode`) to detect process termination.
  4. When a dead worker is detected, all uncompleted jobs registered in `_in_flight[worker_id]` are requeued with an incremented attempt counter ($attempt + 1$) up to `max_retries`.
  5. Provide deterministic CLI failure injection (`--kill-worker` and `--kill-after-jobs`) invoking real OS process termination (`os._exit(42)`).
- **Consequences**:
  - *Positive*: Completely deterministic, observable failure recovery; zero polling timeouts required to infer process death; strict terminal accounting invariant (`completed + failed == submitted`).
  - *Negative*: Requires bidirectional messaging over the event queue for acquisition and completion.

---

## ADR-010: Capacity-Restoring Worker Replacement vs. Dynamic Scaling

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: When a worker process terminates, surviving workers can continue processing the queue, but available system concurrency is reduced.
- **Decision**:
  1. The coordinator optionally spawns a replacement worker process (e.g. `worker-X-r1`) upon worker termination to restore active concurrency back to the configured capacity (`num_workers`).
  2. Worker replacement is strictly a **capacity restoration mechanism**, not an adaptive or dynamic autoscaler. The target concurrency remains fixed at the static baseline parameter.
- **Consequences**:
  - *Positive*: Prevents starvation when worker count is small (e.g. 1 worker); ensures long benchmarks maintain consistent processing capacity after an injected failure.
  - *Negative*: Incurs OS process creation overhead on `spawn` platforms when a worker dies.

---

## ADR-011: Strict Separation of Logical Job Identity from Execution Attempt Identity

- **Status**: Accepted
- **Date**: 2026-10-04
- **Context**: In initial prototypes, `Job` held an internal `attempt` counter, effectively conflating the logical unit of work with physical execution attempts. In distributed systems failure analysis and replay, a single logical task may undergo multiple executions across distinct workers and time intervals. Conflating these concepts prevents clean event tracing, provenance tracking, and divergence analysis.
- **Decision**:
  1. Formally separate `Job` (the stable logical unit of work, identified by `job_id`) from `ExecutionAttempt` (a concrete physical execution, uniquely identified by `AttemptKey = (job_id, attempt_id)`).
  2. A retry must never reuse an earlier attempt identity; every retry instantiates a brand new `ExecutionAttempt` with an incremented sequential `attempt_id`.
  3. Workers execute `ExecutionAttempt` instances and report attempt-level results, without authority over logical job state.
- **Consequences**:
  - *Positive*: Unambiguous attempt identity; transparent provenance of which worker executed which attempt; foundational substrate for future trace recording and deterministic replay.
  - *Negative*: Slightly more dataclasses and state mappings in coordinator memory.

---

## ADR-012: Explicit Attempt Lifecycle and Coordinator-Authoritative Deduplication

- **Status**: Accepted
- **Date**: 2026-10-04
- **Context**: When workers fail or network delays occur, late results from earlier attempts may arrive after a subsequent retry has already completed or is currently active. The coordinator must prevent state corruption, race conditions, or duplicate side effects.
- **Decision**:
  1. Define explicit attempt lifecycle states: `CREATED`, `ASSIGNED`, `RUNNING`, `COMPLETED`, `FAILED`, `LOST`, `RETRY_PENDING`.
  2. Maintain unambiguous worker ownership at the coordinator (`_attempt_ownership[AttemptKey] = worker_id`). When a worker dies, ownership is revoked immediately, and the attempt is marked `LOST`.
  3. Enforce coordinator authority over logical job outcomes (`JobStatus`):
     - **Valid Completion**: Current active attempt finishes; transitions job to `COMPLETED`.
     - **Duplicate Completion**: Repeated arrival for an already-completed job; safely ignored.
     - **Stale Completion**: Arrival from an older superseded attempt (e.g., attempt 1 arrives after attempt 2 completed or became active); safely ignored.
- **Consequences**:
  - *Positive*: Elimination of duplicate completion anomalies; deterministic accounting; robust to worker death and out-of-order event delivery.
  - *Negative*: Requires coordinator to maintain historical attempt indices per job.

---

## ADR-013: Deterministic Scenario and Fault-Injection Layer

- **Status**: Accepted
- **Date**: 2026-10-04
- **Context**: Milestone 3 requires reliably reproducing specific distributed execution and failure situations for automated testing and comparative evaluation. Stochastic or uncoordinated failure injection creates flaky experiments and undermines scientific auditability. Furthermore, embedding scenario generation directly into coordinator logic would couple experimental setups with core runtime mechanics.
- **Decision**:
  1. Isolate scenario definitions and workload generators in a dedicated module (`src/titan/scenario.py`), completely separate from `StaticRuntime`.
  2. Implement `Scenario` as an immutable configuration supporting deterministic patterns (`uniform`, `linear`, `bimodal`) and seeded repeatability.
  3. Implement `FaultConfig` for deterministic worker failure injection triggered at an exact completion threshold (`kill_after_jobs`) or target job (`target_job_id`) via real process termination (`os._exit(42)`). Fault injection is disabled by default.
  4. Perform strict upfront validation of fault targets and parameters prior to execution, failing fast rather than partially executing.
  5. Provide first-class CLI support (`--scenario`, `--pattern`, `--seed`) while maintaining 100% backward compatibility with existing CLI arguments.
- **Consequences**:
  - *Positive*: Perfect reproducibility across test runs; clear separation between experimental scenarios and runtime mechanics; rich observability payloads without polluting authoritative job domain models.
  - *Negative*: Scenarios are limited to deterministic single-node process crash-stop failures at this stage; networked partition scenarios remain for future milestones.

---

## ADR-014: Structured Execution Event Tracing

- **Status**: Accepted
- **Date**: 2026-10-04
- **Context**: As Titan coordinates multi-process workloads, deterministic failure injection, retries, and capacity restoration, post-run analysis requires an auditable, reconstructable history of what physically happened during a run. Relying on raw logs, print statements, or ad-hoc metrics counters creates parsing fragility and fails to preserve the exact logical sequence of state transitions across jobs, execution attempts, and worker entities. Furthermore, the tracing layer must remain strictly observational and decoupled from runtime decision-making.
- **Decision**:
  1. Define a canonical logical event model (`TraceEvent` in `src/titan/trace.py`) with explicit schema fields:
     - `seq: int`: Strictly monotonically increasing sequence number assigned by the coordinator.
     - `event_type: EventType`: Explicit lifecycle transition enum member.
     - `timestamp: float`: Monotonic observation timestamp.
     - `job_id: str | None`: Logical job identifier when applicable.
     - `attempt_id: int | None`: Concrete attempt identifier when applicable.
     - `worker_id: str | None`: Worker entity identifier when applicable.
     - `data: dict[str, Any]`: Structured details and telemetry payload.
  2. Implement canonical lifecycle event types covering complete run, worker, and job lifecycles:
     - Run: `RUN_STARTED`, `RUN_COMPLETED`
     - Worker: `WORKER_STARTED`, `WORKER_EXITED`, `WORKER_FAILED`, `WORKER_REPLACED`
     - Job/Attempt: `JOB_CREATED`, `JOB_ASSIGNED`, `JOB_STARTED`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_LOST`, `RETRY_SCHEDULED`, `JOB_REASSIGNED`
  3. Enforce canonical ordering semantics via monotonic sequence numbers (`seq`), never wall-clock timestamps.
  4. Maintain strict architectural separation between authoritative runtime state and the observational trace collector (`ExecutionTrace`). Runtime decisions (retries, deduplication, terminations) never read or depend on trace events.
  5. Provide first-class JSON export and CLI inspection (`--trace` and `--trace-file <path>`), and include trace telemetry in `--json` payloads.
- **Consequences**:
  - *Positive*: Enables exact, deterministic reconstruction of execution history, failure points, and retry flows; clean separation of concerns; provides foundation for future replay and failure analysis milestones.
  - *Negative*: Slight memory overhead for collecting event objects during large runs; addressed by lightweight dataclasses and optional collector resets.

---

## ADR-015: Deterministic Execution Trace Replay Engine

- **Status**: Accepted
- **Date**: 2026-10-04
- **Context**: Milestone 4 established canonical structured execution tracing (`TraceEvent`, `ExecutionTrace`). However, post-run failure analysis, anomaly detection, and empirical debugging require an authoritative mechanism to inspect previously captured traces and verify their internal logical consistency. Simply running arbitrary code again is non-deterministic and can produce different interleavings. An engine is needed that can reconstruct the exact logical execution history, check state invariants, and detect impossible transitions without side effects.
- **Decision**:
  1. Build a dedicated, observational replay engine (`ReplayEngine` in `src/titan/replay.py`) operating strictly over structured traces.
  2. Implement an isolated, read-only replay state model (`ReplayState`, `ReplayWorkerState`, `ReplayJobState`, `ReplayAttemptState`) rather than reusing mutable runtime coordinator state.
  3. Enforce strictly observational semantics: the replay engine never executes workload computation, never spawns worker processes, never invokes fault injection, does not modify traces, and does not depend on wall-clock time.
  4. Enforce sequence numbers (`seq`) as the sole canonical ordering mechanism, completely ignoring timestamps for ordering decisions.
  5. Validate authoritative lifecycle state transitions and detect corruptions:
     - Strict sequence continuity ($seq_{k+1} == seq_k + 1$)
     - Single run lifecycle bounds (`RUN_STARTED` at start, prohibition of job events after `RUN_COMPLETED`)
     - Unknown job or worker detection
     - Unassigned attempt starts or completions
     - Illegal retries without preceding lost/failed attempts
     - Reassignments without corresponding retries
     - Duplicate terminal completions for attempts or jobs
     - Worker replacement validity checks
  6. Return a structured, JSON-serializable `ReplayResult` containing validation outcome (`valid`), reconstructed state summaries, failure/retry metrics, and diagnostic error lists.
  7. Provide first-class CLI support via `python src/titan/cli.py replay <trace-file> [--json]`.
- **Consequences**:
  - *Positive*: Establishes a rock-solid, deterministic audit layer for execution history; enables offline verification of runs; provides the foundational tool for divergence detection and automated failure analysis in subsequent research milestones.
  - *Negative*: Trace replay validates the logical sequence recorded in the trace, but cannot verify external state outside the captured trace schema.




