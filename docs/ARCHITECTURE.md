# Titan Architecture

This document serves as the architectural source of truth for Titan. It explicitly distinguishes between what is already implemented, what is planned, and what remains undecided.

---

## 1. Confirmed Architecture

As of Milestone 7, the confirmed architecture consists of the **Failure-Aware Multi-Process Runtime with Structured Event Tracing, Deterministic Replay Engine, Replay Fidelity / Divergence Detection, and Deterministic Failure Classification & Root-Cause Analysis**:

```
                                  [ Titan CLI ]
                              (src/titan/cli.py)
                                       |
                                       v
                    +-------------------------------------+
                    |       StaticRuntime Coordinator     |
                    |        (src/titan/runtime.py)       |
                    |  - In-Flight Ownership Tracker      |
                    |  - Process Death Detector           |
                    |  - Deduplication & Terminal Account |
                    +------------------+------------------+
                                       |
                      +----------------+----------------+
                      |                                 |
                      v (Job Enqueue & Retries)         | (Events: Acquired + Results)
           +---------------------+                      v
           |   In-Memory Queue   |           +---------------------+
           |    (job_queue)      |           |   In-Memory Queue   |
           +----------+----------+           |   (event_queue)     |
                      |                      +----------^----------+
        +-------------+-------------+                   |
        |             |             |                   |
        v             v             v                   |
   +---------+   +---------+   +---------+              |
   | Worker  |   | Worker  |   | Worker  |              |
   | Process |   | Process |   | Process |              |
   |    0    |   |    1    |   |   N-1   |              |
   +----+----+   +----+----+   +----+----+              |
        |             |             |                   |
        +-------------+-------------+-------------------+
                      | (Execute Deterministic Workload)
                      v
           +---------------------+
           |   Metrics Engine    |
           | (src/titan/metrics) |
           +---------------------+
```

### 1.1 Process Model & Failure Detection
- **Process Isolation**: The runtime executes workers as separate OS processes (`multiprocessing.Process` using the `spawn` context).
- **Process Death Detection**: The coordinator continuously monitors worker process health using native OS lifecycle facilities (`process.is_alive()` and `process.exitcode`).
- **Failure Classification**: The coordinator explicitly distinguishes:
  1. *Normal Worker Shutdown*: Triggered by coordinator sentinel tokens during `stop()`; worker exits cleanly with exit code `0`.
  2. *Intentional Test Failure Injection*: Triggered by CLI flags (`--kill-worker` and `--kill-after-jobs`); worker executes an immediate OS-level exit via `os._exit(42)`.
  3. *Unexpected Worker Termination*: Unplanned process crash or signal termination (`exitcode != 0` and `exitcode != 42` during active run).

### 1.2 Execution Model: Logical Jobs vs. Execution Attempts
Titan strictly distinguishes between a **logical job** and a **concrete execution attempt**:
```
Logical Job (stable job_id)
       │
       ├── Attempt 1 (AttemptKey = (job_id, 1)) ──> Worker W1 ──> worker failure (LOST)
       │
       ├── Attempt 2 (AttemptKey = (job_id, 2)) ──> Worker W2 ──> completes (COMPLETED)
       │
       └── Logical Job Terminal Outcome: COMPLETED
```

- **Logical Job (`Job`)**:
  - A unit of work with a stable identity (`job_id`) that never mutates across retries.
  - Represents the authoritative task submitted by the producer.
  - Lifecycle states (`JobStatus`): `PENDING`, `RUNNING`, `RETRY_PENDING`, `COMPLETED`, `FAILED`.
- **Execution Attempt (`ExecutionAttempt`)**:
  - A concrete physical execution of a logical job.
  - Has an explicit, composite identity: `AttemptKey = (job_id, attempt_id)`.
  - Attempts are **never collapsed** into the logical job identity.
  - Lifecycle states (`AttemptStatus`): `CREATED`, `ASSIGNED`, `RUNNING`, `COMPLETED`, `FAILED`, `LOST`, `RETRY_PENDING`.
- **Worker Entity (`WorkerRecord`)**:
  - Stable worker identity (e.g. `worker-0`).
  - When replacement is enabled, a replacement worker receives a new distinct identity (e.g. `worker-0-r1`). The historical record of the original failed worker is permanently preserved.

### 1.3 In-Flight Work Ownership & State Transitions
- **Unambiguous Ownership**: At any point where an attempt is executing, the coordinator maintains an authoritative mapping: `_attempt_ownership[AttemptKey] = worker_id`.
- **Acquisition Event**: Workers emit `JobAcquired(job_id, worker_id, attempt_id, acquired_at)` immediately upon dequeuing. This transitions the attempt to `RUNNING` and establishes worker ownership.
- **Worker Termination & Recovery**:
  1. Worker process crashes or exits abruptly (`process.is_alive() == False`).
  2. Coordinator revokes ownership of all in-flight attempts held by that worker (`_attempt_ownership.pop(AttemptKey)`).
  3. Affected attempts transition to `AttemptStatus.LOST`.
  4. If $attempt\_id < max\_retries$, the logical job transitions to `JobStatus.RETRY_PENDING` and a brand new attempt ($attempt\_id + 1$) is instantiated with `AttemptStatus.CREATED` and placed onto `job_queue`.
  5. If retries are exhausted, the logical job transitions to terminal `JobStatus.FAILED`.

### 1.4 At-Least-Once Processing & Coordinator Deduplication
- **At-Least-Once Execution**: Computation may physically execute more than once across failures.
- **Coordinator-Authoritative Terminal State**: Workers report attempt outcomes (`JobResult`); the coordinator alone determines logical job completion.
- **Deduplication Categories (`CompletionCategory`)**:
  1. *Valid Completion (`VALID`)*: A completion for the currently active attempt that transitions the logical job to `COMPLETED`.
  2. *Duplicate Completion (`DUPLICATE`)*: Repeated arrival of a result for an already-completed job attempt. Suppressed without side effects.
  3. *Stale Completion (`STALE`)*: Late arrival of a result from an older superseded attempt (e.g., Attempt 1 arrives after Attempt 2 completed or was dispatched). Safely discarded without modifying terminal state.
- **Terminal Accounting Invariant**:
  $$\text{completed\_unique} + \text{failed\_unique} == \text{total\_unique\_submitted}$$

### 1.5 Worker Replacement & Identity Semantics
- When a worker process terminates, the coordinator spawns a replacement worker process (e.g. `worker-0-r1`) to restore active pool capacity back to `--workers`.
- **Identity Distinction**: The replacement worker receives a new, distinct worker identity. The historical identity and lifecycle of the failed worker remain intact in `WorkerRecord`.
- Worker replacement is strictly a capacity restoration mechanism, not an autoscaler.

### 1.6 Metrics & Telemetry
- Implemented in `src/titan/metrics.py`.
- **Primary Throughput**: $\text{total\_completed\_unique} / T_{\text{wall}}$ (unique jobs/second).
- **Attempt Throughput**: $\text{total\_execution\_attempts} / T_{\text{wall}}$ (total execution attempts/second).
- **Recovery Duration**: Elapsed time from the detection of the first worker failure until all recovered jobs reach terminal state.
- **Failure Telemetry**: Tracks `worker_failures`, `jobs_recovered`, `jobs_permanently_failed`, `total_retries`, and `duplicate_results_ignored`.

### 1.7 Deterministic Scenario & Fault-Injection System
Implemented in `src/titan/scenario.py`:
- **Scenario Abstraction (`Scenario`)**:
  - Encapsulates a repeatable test configuration: `name`, `num_workers`, `num_jobs`, `work_units`, `pattern` (`uniform`, `linear`, `bimodal`), `seed`, `max_retries`, `replace_failed_workers`, `fault_config`, and `timeout`.
  - Fully decoupled from core coordinator logic. The scenario generates deterministic sequences of logical `Job` instances and executes them against the runtime.
  - Predefined named presets: `baseline` (normal execution), `worker-crash` (injected crash of worker-0), and `stress-recovery` (concurrency stress with recovery).
- **Deterministic Fault Injection (`FaultConfig`)**:
  - Explicitly targets a specific worker entity (`target_worker_id`) and trigger point (`kill_after_jobs` threshold or `target_job_id`).
  - Disabled by default.
  - Strict pre-execution validation: bounds-checks worker indices, enforces non-negative thresholds, and prevents thresholds exceeding total job count.
  - Triggered synchronously inside the target worker process mid-execution via `os._exit(42)`.
- **System Guarantees**:
  - *Repeatability*: Identical scenario parameters and seed produce identical job payloads, identical failure points, and identical terminal outcomes.
  - *Provenance & Observability*: Scenario metadata and fault status are reported alongside metrics without mixing scenario data into authoritative `Job` or `ExecutionAttempt` records.
- **Intentional Milestone Boundaries**:
  - No random/unseeded packet loss or stochastic clock drift.
  - No Byzantine fault models or network split-brain simulations.
  - No external orchestrators or distributed log persistence.

### 1.8 Structured Event Tracing & Execution History
Implemented in `src/titan/trace.py`:
- **Canonical Event Model (`TraceEvent`)**:
  - An immutable structured event capturing an authoritative logical state transition:
    - `seq: int`: Strictly monotonically increasing sequence number assigned by the coordinator.
    - `event_type: EventType`: Canonical enum category for the transition.
    - `timestamp: float`: Monotonic observation time (`time.perf_counter()`).
    - `job_id: str | None`: Logical job identifier when applicable.
    - `attempt_id: int | None`: Concrete attempt identifier when applicable.
    - `worker_id: str | None`: Worker entity identifier when applicable.
    - `data: dict[str, Any]`: Structured contextual telemetry and failure metadata.
- **Logical Execution Events vs Implementation Noise**:
  - Titan traces meaningful lifecycle events, not arbitrary debug statements or internal loop counters:
    - *Run Lifecycle*: `RUN_STARTED`, `RUN_COMPLETED`.
    - *Worker Pool Lifecycle*: `WORKER_STARTED`, `WORKER_EXITED`, `WORKER_FAILED`, `WORKER_REPLACED`.
    - *Job & Attempt Lifecycle*: `JOB_CREATED`, `JOB_ASSIGNED`, `JOB_STARTED`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_LOST`, `RETRY_SCHEDULED`, `JOB_REASSIGNED`.
- **Event Ordering Semantics**:
  - The canonical ordering of execution events is strictly defined by the coordinator's monotonic sequence number (`seq`).
  - Wall-clock timestamps are purely informational telemetry and are **never** used as the source of ordering, preventing clock skew or timer jitter from corrupting execution history.
- **Separation of Authoritative State vs Observational Trace**:
  - The trace is an **observational collector** (`ExecutionTrace`).
  - The runtime coordinator alone maintains authoritative state (`_job_states`, `_attempt_states`, `_attempt_ownership`, `_completed_jobs`).
  - Runtime scheduling, retries, deduplication, and termination decisions never read, query, or depend on the trace collector.
  - Normal execution proceeds identically whether a trace consumer is present, inspecting, or exporting the trace.

### 1.9 Deterministic Replay Engine
Implemented in `src/titan/replay.py`:
- **Observational Replay Architecture**:
  - Reconstructs and validates the logical execution history of a run strictly from its structured trace.
  - **Zero Execution / Purely Observational**: Replay does *not* execute workload tasks, does *not* spawn OS worker processes, does *not* invoke fault injection, does *not* touch network or disk IPC queues, and has *no* dependency on wall-clock time.
  - Replay is completely non-destructive: it never alters, mutates, or truncates the original trace.
- **Dedicated Replay State Model**:
  - Completely decoupled from mutable runtime state (`StaticRuntime`).
  - Represents reconstructed state entities:
    - `ReplayState`: Root state tracking run status, workers, jobs, attempts, in-flight ownership, and counts.
    - `ReplayRunStatus`: `NOT_STARTED`, `RUNNING`, `COMPLETED`.
    - `ReplayWorkerState`: Worker entity lifecycle (`IDLE`, `BUSY`, `FAILED`, `EXITED`, `REPLACED`) and assignment counters.
    - `ReplayJobState`: Logical job lifecycle (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `LOST`, `RETRY_PENDING`).
    - `ReplayAttemptState`: Concrete attempt lifecycle, owning worker, and terminal outcomes.
- **Deterministic Ordering**:
  - Events are processed in strict sequence order defined exclusively by the monotonic sequence number `seq`.
  - Timestamps are ignored for ordering purposes, guaranteeing bit-for-bit identical replay results across different machines, operating systems, and CPU loads.
- **Rigorous Event Transition Validation**:
  - Enforces authoritative lifecycle transition invariants:
    - Monotonic sequence continuity ($seq_{k+1} == seq_k + 1$).
    - Run boundary validity: `RUN_STARTED` must occur exactly once at start; events after `RUN_COMPLETED` are prohibited (with the sole exception of expected clean worker process termination `WORKER_EXITED` during shutdown).
    - Unknown entity rejection: jobs or workers must be created/started before being assigned or completed.
    - Attempt ownership integrity: jobs cannot start or complete without an active worker assignment and running attempt.
    - Retry and reassignment validity: retries are only legal following lost/failed attempts; reassignments require an active retry attempt.
    - Duplicate terminal outcome prevention: attempts and jobs cannot be completed or failed more than once.
    - Worker replacement integrity: replacement events require a previously failed or exited worker entity.
- **Replay Result & Diagnostics (`ReplayResult`)**:
  - Produces structured, JSON-serializable diagnostic records including validation status (`valid`), total event counts, final run state, reconstructed job and worker states, attempt and retry totals, worker failure and replacement metrics, and detailed diagnostic error strings.
- **Relationship Between Runtime State, Trace, and Replay**:
  ```
  [ Runtime Execution ] ---> Emits Events ---> [ ExecutionTrace ]
  (StaticRuntime, Workers)                     (TraceEvent Log)
                                                      |
                                                      v (Read-Only)
                                             [ ReplayEngine ]
                                                      |
                                                      v (Reconstruct & Validate)
                                             [ ReplayResult ]
                                             - Logical State Audit
                                             - Transition Invariant Check
                                             - Telemetry Verification
### 1.10 Replay Fidelity & Divergence Detection
Implemented in `src/titan/replay.py`:
- **Concept of Replay Fidelity in Titan**:
  - Beyond structural integrity validation (Milestone 5), replay fidelity evaluates whether an observed execution trace conforms exactly to an expected canonical execution contract.
  - Replay fidelity provides the foundational comparison layer for regression detection, divergence analysis, and fault verification across trials.
- **Constituents of Deterministic Equivalence**:
  Two execution traces are deemed *equivalent* if and only if all canonical deterministic dimensions match:
  1. *Sequence Ordering & Event Types*: Identical canonical sequence order and event types (`seq`, `event_type`).
  2. *Job & Attempt Identity*: Identical logical job identities and attempt numbers across all transitions.
  3. *In-Flight Ownership*: Identical worker assignment and execution ownership for every attempt.
  4. *Retry & Reassignment History*: Identical retry decisions, attempt counts, and reassignment targets.
  5. *Worker Pool Lifecycle & Topology*: Identical worker startup, failure, replacement, and exit events.
  6. *Terminal Outcomes & State*: Identical per-job terminal outcomes (`COMPLETED` vs `FAILED`), result payloads, and aggregate run counters.
- **Intentionally Ignored Metadata**:
  The fidelity comparison engine strictly ignores nondeterministic telemetry:
  - Wall-clock observation timestamps (`timestamp`, `acquired_at`, `completed_at`, `duration`).
  - Host execution details (OS process PIDs, CPU core IDs, thread IDs).
  - Internal memory addresses or Python object IDs.
- **Explicit Divergence Classification (`DivergenceCategory`)**:
  Divergences are classified into explicit, structured categories:
  - `EVENT`: Sequence number discontinuity, event type mismatch, missing event, or unexpected extra event.
  - `STATE`: Reconstructed run or job lifecycle state differs from expected state.
  - `OWNERSHIP`: Worker executing an attempt differs from expected worker assignment.
  - `RETRY`: Retry count, retry attempt number, or retry scheduling decision differs.
  - `WORKER`: Worker lifecycle entity, failure event, replacement mapping, or pool status differs.
  - `OUTCOME`: Final job completion result, error payload, or run completion count differs.
- **Deterministic Reporting Contract (`FidelityResult`, `DivergenceRecord`)**:
  - The comparison engine walks events in strict canonical sequence order ($seq = 1, 2, \dots$), guaranteeing that the *first divergence* reported is 100% deterministic and reproducible.
  - Generates structured, JSON-serializable payloads containing equivalence status, total comparisons, divergence count, ordered divergence records, first divergence, and category summaries.
- **Limitations of the Comparison Model**:
  - Comparison operates over structured trace records and reconstructed state; it does not perform deep AST code diffs of workload functions.
  - While single-worker deterministic executions produce bit-for-bit identical traces across separate physical runs, multi-worker concurrent executions subject to OS process scheduling jitter may interleave independent jobs differently unless synchronized by the coordinator.

### 1.11 Deterministic Failure Classification & Root-Cause Analysis
Implemented in `src/titan/analysis.py`:
- **Consuming Architecture & Layering**:
  The failure analysis layer is strictly observational and analytical. It builds directly upon the authoritative pipeline:
  ```
  runtime state ──> event trace ──> replay engine ──> divergence engine ──> failure analysis
  (authoritative)   (canonical)     (reconstructed)   (comparison)          (evidence-based)
  ```
  The failure-analysis layer consumes these sources but never mutates them, maintaining a strict architectural boundary so that analysis never becomes a second runtime control plane.
- **Core Diagnostic Questions Answered**:
  1. *WHAT failed?*: Explicitly classified via `failure_class` (e.g. `WORKER_FAILURE`, `LOST_EXECUTION`, `RETRY_EXHAUSTION`).
  2. *WHERE did it fail?*: Localized to canonical sequence number `seq`, worker ID, job ID, and attempt ID.
  3. *WHICH logical entity was affected?*: Identified via `affected_entity` (e.g. `worker:worker-0`, `job:job-000003`, `attempt:job-000003#1`, `run`).
  4. *WHAT was the immediate failure mode?*: Captured in `immediate_cause` (e.g. non-zero exit code, unhandled task exception, missing worker).
  5. *WHAT recovery action followed?*: Documented in `recovery_action` (e.g. `WORKER_REPLACED`, `RETRY_SCHEDULED`, `JOB_REASSIGNED`).
  6. *WAS the final outcome recovered or unrecovered?*: Formally classified via `recovery_outcome` (`RECOVERED`, `UNRECOVERED`, or `NOT_APPLICABLE`).
  7. *CAN the failure be classified deterministically from the available evidence?*: Yes, 100% deterministic rule-based analysis without probabilistic inference or machine-learning heuristics.
- **Deterministic Failure Taxonomy (`FailureClass`)**:
  - `WORKER_FAILURE`: Worker process terminates unexpectedly while execution is active.
  - `JOB_FAILURE`: Independent task/attempt execution error independent of worker replacement semantics.
  - `LOST_EXECUTION`: An active execution attempt becomes lost because its worker disappears.
  - `RETRY_EXHAUSTION`: A failed or lost job cannot obtain another permitted retry under policy.
  - `OWNERSHIP_FAILURE`: Trace or replay validation reveals an invalid or inconsistent ownership transition.
  - `REPLAY_DIVERGENCE`: Replay fidelity comparison detects an execution divergence.
  - `RUN_FAILURE`: The overall run terminates in an unrecovered failure state.
- **Separation of Root Cause vs. Downstream Consequences**:
  - Explicit distinction between the initiating root failure and subsequent consequences or recovery actions.
  - Example causal progression:
    $$\text{WORKER\_FAILURE} \longrightarrow \text{JOB\_LOST (Consequence)} \longrightarrow \text{RETRY\_SCHEDULED (Recovery)} \longrightarrow \text{JOB\_COMPLETED (Outcome)}$$
  - The analysis layer preserves `WORKER_FAILURE` as the sole root cause; `JOB_LOST` is cataloged as a downstream consequence rather than an independent root cause.
  - Multiple genuinely independent failures (e.g., separate worker crashes or distinct task errors) are preserved separately and deterministically.
- **Deterministic Causal Chains (`CausalChainNode`)**:
  - Reconstructs the exact, ordered sequence of evidence leading from root failure to consequence, recovery actions, and terminal outcome.
  - Causal chains are ordered strictly by canonical event sequence numbers (`seq`). Wall-clock timestamps are never used to infer or establish causality.
- **Recovery Outcome Semantics (`RecoveryOutcome`)**:
  - `RECOVERED`: All affected logical jobs successfully retried and reached `COMPLETED`.
  - `UNRECOVERED`: Retries exhausted or unrecovered, job in terminal `FAILED`, or run unrecovered.
  - `NOT_APPLICABLE`: For observational replay divergence or informational checks.
- **Integration with Replay and Divergence**:
  - Structurally invalid traces are rejected upfront via existing `ReplayEngine.replay()` validation results rather than attempting unsupported analysis.
  - Replay divergence comparison results from `ReplayFidelityEngine.compare()` are cleanly integrated as `REPLAY_DIVERGENCE` records with `NOT_APPLICABLE` recovery status.

### 1.12 TitanBench: Reproducible Failure Corpus & Scenario Runner
Implemented in `src/titan/bench/`:
- **Purpose and Architecture**:
  - TitanBench is a versioned, deterministic failure-corpus and scenario runner layered on top of Titan's scenario, trace, replay, and analysis subsystems.
  - Conceptual pipeline:
    ```
    Benchmark Scenario (Corpus)
               │
               ▼
       TitanBench Runner
               │
               ▼
        Titan Execution ──> Trace Artifact (trace.json)
                                   │
                                   ├─> Replay Engine (replay.json)
                                   │
                                   └─> Failure Analysis (analysis.json)
                                               │
                                               ▼
                                      Oracle Evaluation
                                               │
                                               ▼
                                       Benchmark Result
                             (PASS / FAIL / INVALID + result.json)
    ```
  - The benchmark layer remains completely separate from Titan's core runtime logic and is independently usable via a small, clean Python API or the CLI.
- **Canonical Scenario Classes (A through I)**:
  - `CLASS_A_BASELINE` (`TB-A-001`): Clean deterministic execution without worker failure.
  - `CLASS_B_SINGLE_WORKER_FAILURE` (`TB-B-001`): Controlled single-worker failure and recovery.
  - `CLASS_C_IN_FLIGHT_FAILURE` (`TB-C-001`): In-flight attempt loss and recovery during execution.
  - `CLASS_D_REPEATED_FAILURE` (`TB-D-001`): Sequential multi-worker failures across distinct worker processes.
  - `CLASS_E_RETRY_PRESSURE` (`TB-E-001`): Retry exhaustion under `max_retries=1` causing expected unrecovered failure.
  - `CLASS_F_DUPLICATE_STALE` (`TB-F-001`): Arrival of duplicate completions verifying coordinator suppression.
  - `CLASS_G_CAPACITY_LOSS` (`TB-G-001`): Worker disappearance without replacement (`replace_failed_workers=False`).
  - `CLASS_H_ADVERSARIAL_TIMING` (`TB-H-001`): Failure injected at execution boundary on first job acquisition (`kill_after_jobs=0`).
  - `CLASS_I_LARGE_WORKLOAD` (`TB-I-001`): Higher concurrency (4 workers, 40 jobs) under baseline conditions.
- **Deterministic Oracle Expectations (`ExpectedBehavior`)**:
  - Every benchmark scenario specifies explicit assertions covering replay validity, reconstructed run state, failure classification, root-cause counts, worker failure counts, worker replacement counts, retry bounds, completed/failed job counts, and duplicate result suppression.
  - Differentiates *expected failure behavior* from *framework errors*: a scenario expecting unrecovered retry exhaustion (e.g. `TB-E-001`) passes when the observed failure matches expected assertions.
- **Machine-Readable Artifact Layout**:
  - Every execution writes standardized artifacts under `results/<scenario-id>/`:
    - `scenario.json`: Serialized benchmark scenario specification and configuration.
    - `trace.json`: Canonical structured execution trace event array.
    - `replay.json`: Deterministic trace replay and validation report.
    - `analysis.json`: Root-cause failure analysis report with causal chains.
### 1.13 Recovery-Policy Experimentation Framework
Implemented in `src/titan/experiment/`:
- **Conceptual Pipeline**:
  ```
  TitanBench Scenario + Recovery Policy
                  ↓
              Titan Run
                  ↓
                Trace
                  ↓
           Replay + Analysis
                  ↓
           Metric Extraction
                  ↓
           Experiment Result
                  ↓
           Policy Comparison
  ```
- **Explicit Recovery Policy Model (`RecoveryPolicy`, `PolicyRegistry`)**:
  - Encapsulates recovery behaviors independently from workload scenarios.
  - Frozen, immutable dataclass configuration with stable string identifiers:
    - `R0` (Baseline Recovery): Standard automatic worker replacement (`replace_failed_workers=True`) and default retry budget (`max_retries=3`).
    - `R1` (No Worker Replacement): Failed workers are not replaced (`replace_failed_workers=False`); surviving workers process retried work under degraded pool capacity.
    - `R2` (Limited Retry Budget): Worker replacement is enabled (`replace_failed_workers=True`), but retry budget is minimized (`max_retries=1`, allowing zero retries upon failure).
    - `R3` (Minimal Recovery): Both worker replacement and retries are disabled/minimized (`replace_failed_workers=False`, `max_retries=1`).
- **Fair Comparison Invariant**:
  - `policy.apply_to_scenario(benchmark_scenario.scenario)` derives a new `Scenario` preserving 100% of non-policy workload variables: `num_workers`, `num_jobs`, `work_units`, `pattern`, `seed`, `fault_config`, `fault_configs`, `duplicate_jobs`, and `timeout`.
  - Only recovery-policy parameters (`replace_failed_workers`, `max_retries`) are overridden.
- **Metric Extraction & The Metric Honesty Rule (`ExperimentMetrics`)**:
  - Reports strictly empirical, non-fabricated metrics:
    - *Reliability*: `recovery_rate` (1.0 if CLEAN/RECOVERED with 0 failed jobs, else 0.0), `unrecovered_failure_rate`, `invariant_violations`.
    - *Work*: `total_jobs`, `completed_jobs`, `failed_jobs`, `total_attempts`, `retries`, `duplicate_work` ($\max(0, \text{attempts} - \text{completed})$), `lost_work` (aborted in-flight attempts), `retry_overhead`, `duplicate_completions_ignored`.
    - *Recovery*: `worker_failures`, `worker_replacements`, `recovery_classification`, `recovery_duration_sec`.
    - *Performance*: `wall_clock_duration_sec`, `goodput_jobs_per_sec` ($\text{completed\_jobs} / \text{wall\_clock}$).
    - *Latency*: `avg_latency_ms`, `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`.
  - Intentionally unavailable metrics (`cpu_utilization_pct`, `memory_rss_bytes`, `network_io_bytes`, `intra_job_partial_work_lost`, `failure_detection_latency`) are cataloged with explicit technical rationales rather than fabricating proxy numbers.
- **Multi-Trial Repetition and Aggregation (`ExperimentResult`, `PolicyComparison`)**:
  - Supports $N$ repeated trials to observe variance under identical deterministic inputs.
  - Computes sample counts, mean, min, and max for all numeric telemetry.
  - Side-by-side policy comparisons generate ASCII tables and evidence-based factual observations without premature winner declarations.
- **Machine-Readable Artifact Layout**:
  - Standardized under `experiments/results/<experiment-id>/`:
    - `experiment.json`: Metadata, base scenario specification, and effective scenario configuration.
    - `summary.json`: Aggregated trial statistics and recovery rate.
    - `trials/trial-NNN.json`: Structured trial telemetry.
    - `trials/trace-NNN.json`: Canonical execution trace.
    - `comparisons/<scenario-id>/comparison.json`: Multi-policy side-by-side comparative evaluation.

### 1.14 Replay / Tracing Overhead and System Stress Evaluation Framework
Implemented in `src/titan/experiment/evaluation.py`:
- **Purpose and Architecture**:
  - Provides a rigorous, reproducible evaluation harness to answer research questions RQ4 (*tracing overhead*) and RQ5 (*replay scaling cost and system stress behavior*).
  - Explicitly decouples three operational evaluation modes:
    - `Mode A` (`no_trace`): Runtime execution with trace collection disabled (`enable_tracing=False`). Bypasses trace event dataclass instantiation, copying, and append overhead while running the exact same logical workload.
    - `Mode B` (`with_trace`): Runtime execution with canonical structured event tracing active (`enable_tracing=True`).
    - `Mode C` (`replay_only`): Offline deterministic replay of previously captured traces measuring graph reconstruction runtime and event throughput.
- **Fair Overhead Comparison Invariant**:
  - Mode A and Mode B evaluations execute with bit-for-bit identical workload parameters: worker count, job count, work units, pattern, seed, fault configurations, and retry limits.
  - Only trace event recording is varied.
- **Overhead & Replay Metrics**:
  - `absolute_overhead_sec = with_trace_sec - no_trace_sec`
  - `relative_overhead_pct = ((with_trace_sec - no_trace_sec) / no_trace_sec) * 100` (safe when `no_trace_sec > 0`)
  - `trace_size_bytes`: Serialized UTF-8 JSON trace size on disk.
  - `bytes_per_event = trace_size_bytes / event_count`
  - `replay_events_per_sec = replay_events_processed / replay_duration_sec`: Quantifies in-memory replay engine throughput (graph reconstruction and transition invariant checks), which is explicitly distinct from physical workload throughput.
- **Stress & Scaling Evaluation Matrix**:
  - Systematically evaluates increasing complexity across:
    - *Concurrency & Workload Scaling*: Small (2 workers, 10 jobs), Medium (2 workers, 50 jobs), Large (4 workers, 100 jobs).
    - *Failure Intensity*: Single worker crash and recovery, repeated sequential worker failures across distinct worker processes.
    - *Retry Pressure*: Normal retry recovery vs. limited-retry fail-fast (`max_retries=1`).
- **Environmental Controls & Logical Determinism**:
  - Optional warm-up iterations allow OS process spawning and runtime import caching to stabilize prior to measured timing trials.
  - Strict conceptual separation between *logical determinism* (reproducible event sequences, state reconstruction, recovery classifications) and *physical timing variability* (Windows process spawning latency, OS scheduling jitter).
  - Raw timing samples across repeated trials ($N \ge 3$) are preserved alongside aggregate summary statistics (`count`, `mean`, `median`, `min`, `max`).

### 1.15 Known Limitations of Milestone 10
- **In-Memory IPC Queues**: Jobs and ownership state exist in memory during active execution. A crash of the coordinator process loses all runtime state.
- **Single-Host Distribution**: All workers execute on the local machine via OS process IPC pipes (`multiprocessing.Queue`).
- **OS Process Spawning Jitter**: On Windows, child processes spawned via `multiprocessing.spawn` incur non-deterministic process startup latency (typically 50–200ms per pool). Wall-clock measurements reflect this host scheduling variance.
- **Summary Statistics Only**: Metrics report sample counts, means, medians, min, and max. Final research-grade inference (confidence intervals, ANOVA, hypothesis testing) is intentionally deferred to Milestone 11.
- **No Learned Recovery**: Policies are static configurations; dynamic or machine-learning-based recovery selection is out of scope.

---

## 2. Planned Architecture

The following components will be introduced in subsequent research milestones:

```
+--------------------------------------------------------------------------+
|                       Experiment Orchestrator                            |
|  - Automates parameter matrices, runs baselines, records trials          |
+---------------------+------------------------------+---------------------+
                      |                              |
                      v                              v
      +-------------------------------+  +-------------------------------+
      |       Workload Generator      |  |   Extended Failure Injector   |
      |   (Synthesizes bursty, Poisson|  |   (Injects network partitions,|
      |    and heavy-tailed arrivals) |  |    asymmetric stalls, drops)  |
      +---------------+---------------+  +---------------+---------------+
                      |                                  |
                      +------------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |   Adaptive Execution Engine   |
                         |   (Dynamic concurrency limits,|
                         |    backpressure throttling)   |
                         +---------------+---------------+
```

### 2.1 Workload Generator (Milestone 4)
- Will synthesize non-uniform arrival distributions (bursty arrival spikes, Poisson processes) and variable job service times to stress test scheduling behavior.

### 2.2 Adaptive Execution Policies (Milestone 5)
- Will implement dynamic policies (e.g., adaptive concurrency control, dynamic backpressure throttling) to empirically compare against this static baseline with recovery.

---

## 3. Unresolved Decisions

1. **Networked Inter-Node RPC Protocol**:
   - Evaluating raw TCP framing vs lightweight HTTP/1.1 vs gRPC for multi-host clusters.
2. **Persistent Telemetry Formats**:
   - Evaluating JSON Lines (`.jsonl`) logs vs structured Parquet arrays for large automated multi-run experiment sweeps.
