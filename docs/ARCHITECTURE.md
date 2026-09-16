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

### 1.2 In-Flight Work Ownership Tracking
- To answer the critical recovery question: *"Which jobs were assigned to worker X and had not produced a final result when X died?"*, workers emit an immediate `JobAcquired` event to `event_queue` prior to starting computation.
- The coordinator maintains an in-memory ownership registry: `_in_flight[worker_id][job_id] = Job`.
- When a worker dies, the coordinator scans `_in_flight[worker_id]` to identify all uncompleted jobs owned by that worker for immediate recovery.

### 1.3 At-Least-Once Processing & Deduplication Semantics
- **At-Least-Once Execution**: If a worker terminates mid-job, the job is requeued and re-executed by a surviving or replacement worker. A job may therefore be executed more than once across failures.
- **Result Deduplication**: The coordinator enforces that each unique `job_id` has **at most one final successful result** recorded.
- **Stale Result Suppression**: If an earlier slow or presumed-lost attempt eventually deposits a result after a subsequent retry has already succeeded, the coordinator discards the stale result and records it as an ignored duplicate (`duplicate_results_ignored`).
- **Terminal Accounting Invariant**: At the end of execution, the accounting invariant strictly holds:
  $$\text{completed\_unique} + \text{failed\_unique} == \text{total\_unique\_submitted}$$

### 1.4 Retry Policy & Job Lifecycle
- **Configurable Retry Ceiling**: Configured via `--max-retries` (default: 3).
- **Lifecycle States**:
  1. `PENDING`: Enqueued and awaiting acquisition.
  2. `RUNNING`: Acquired by a worker; in-flight ownership established.
  3. `REQUEUED`: Worker died while job was in-flight; attempt counter incremented ($attempt < max\_retries$) and job placed back onto `job_queue`.
  4. `COMPLETED`: Workload successfully executed and acknowledged by the coordinator.
  5. `FAILED`: Max retries exceeded without successful completion, or unrecoverable error.

### 1.5 Worker Replacement
- When a worker dies, the coordinator spawns a replacement worker process (e.g. `worker-X-r1`) to restore the active worker pool back to the statically configured capacity (`--workers`).
- Worker replacement restores lost capacity; it does not dynamically scale or adapt worker counts based on load.

### 1.6 Metrics & Telemetry
- Implemented in `src/titan/metrics.py`.
- **Primary Throughput**: $\text{total\_completed\_unique} / T_{\text{wall}}$ (unique jobs/second).
- **Attempt Throughput**: $\text{total\_execution\_attempts} / T_{\text{wall}}$ (total execution attempts/second).
- **Recovery Duration**: Elapsed time from the detection of the first worker failure until all recovered jobs reach terminal state.
- **Failure Telemetry**: Tracks `worker_failures`, `jobs_recovered`, `jobs_permanently_failed`, `total_retries`, and `duplicate_results_ignored`.

### 1.7 Known Limitations of Milestone 3
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
