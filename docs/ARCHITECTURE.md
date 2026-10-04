# Titan Architecture

This document serves as the architectural source of truth for Titan. It explicitly distinguishes between what is already implemented, what is planned, and what remains undecided.

---

## 1. Confirmed Architecture

As of Milestone 3, the confirmed architecture consists of the **Failure-Aware Multi-Process Runtime**:

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

### 1.8 Known Limitations of Milestone 3
- **In-Memory IPC Queues**: Jobs and ownership state exist in memory. A crash of the coordinator process loses all state (persistent distributed logs are not yet implemented).
- **Single-Host Distribution**: All workers execute on the local machine via OS process IPC pipes.
- **Static Concurrency Only**: Worker pool size is restored to its static baseline upon failure; no load-aware dynamic autoscaling is implemented.

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
