# Titan Architecture

This document serves as the architectural source of truth for Titan. It explicitly distinguishes between what is already implemented, what is planned, and what remains undecided.

---

## 1. Confirmed Architecture

As of Milestone 2, the confirmed architecture consists of the **Static Baseline Multi-Process Runtime**:

```
                                  [ Titan CLI ]
                              (src/titan/cli.py)
                                       |
                                       v
                    +-------------------------------------+
                    |       StaticRuntime Coordinator     |
                    |        (src/titan/runtime.py)       |
                    +------------------+------------------+
                                       |
                      +----------------+----------------+
                      |                                 |
                      v (Job Enqueue)                   | (Result Drain)
           +---------------------+                      v
           |   In-Memory Queue   |           +---------------------+
           |    (job_queue)      |           |   In-Memory Queue   |
           +----------+----------+           |   (result_queue)    |
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

### 1.1 Process Model
- **Process Isolation**: The runtime executes workers as separate OS processes (`multiprocessing.Process` using the `spawn` context) rather than threads. This provides genuine CPU parallelism across hardware cores and isolates worker address spaces.
- **Worker Concurrency**: The number of worker processes is statically configured at runtime instantiation (e.g. 1, 2, 4, 8) and remains fixed throughout execution.
- **Process Termination Tolerance**: If an individual worker process crashes or terminates unexpectedly, the coordinator process does not crash. Surviving workers continue processing remaining queue items, and the coordinator detects missing completions during result draining.

### 1.2 Queue Semantics & Job Lifecycle
- **Job Enqueue**: The coordinator (producer) enqueues immutable `Job` records onto `job_queue` using standard library inter-process communication (`multiprocessing.Queue`).
- **Job Acquisition**: Workers invoke blocking `.get()` calls on `job_queue`. Jobs are distributed among available workers in first-available order by the OS kernel and queue locks.
- **Job Lifecycle States**:
  1. `PENDING`: Job created and enqueued with timestamp `created_at`.
  2. `RUNNING`: Worker acquires the job and records timestamp `started_at`.
  3. `COMPLETED`: Worker successfully executes `execute_workload(work_units)` and records timestamp `completed_at`.
  4. `FAILED`: An uncaught exception occurs during execution, or the job is marked lost.
- **Acknowledgment & Representation**: Completed jobs are represented as immutable `JobResult` records containing timing telemetry, worker ID, execution status, and computation result, posted to `result_queue`.
- **Clean Shutdown**: The coordinator enqueues one `None` sentinel token per worker process onto `job_queue`. Upon encountering a sentinel, the worker exits its processing loop cleanly. The coordinator joins each process with a timeout before terminating lingering processes.

### 1.3 Deterministic Workload
- Implemented in `src/titan/workload.py`.
- Executes pure, deterministic modular arithmetic for a specified number of `work_units`.
- Eliminates non-deterministic timing jitter or external I/O variance, ensuring measurements isolate system scheduling and queuing overheads.

### 1.4 Metrics & Telemetry
- Implemented in `src/titan/metrics.py`.
- **Wall-Clock Duration ($T_{\text{wall}}$)**: Total elapsed seconds from initial job submission until all results are drained.
- **Throughput**: $N_{\text{completed}} / T_{\text{wall}}$ (completed jobs per wall-clock second).
- **Per-Job Latency ($L_i$)**: $T_{\text{completed}, i} - T_{\text{created}, i}$. Measures end-to-end turnaround time including queue waiting and worker compute.
- **Worker Processing Duration ($D_i$)**: $T_{\text{completed}, i} - T_{\text{started}, i}$. Measures active compute duration on the worker process.
- **Average Latency**: Arithmetic mean of completed job latencies.
- **Percentiles ($p50, p95, p99$)**: Calculated using standard scientific linear interpolation over sorted latencies.

### 1.5 Known Limitations of Milestone 2 Baseline
- **At-Most-Once Delivery**: No job persistence or write-ahead logging. If a worker process is terminated mid-execution before posting its `JobResult`, that job is dropped and counted as failed/unreported.
- **No Automatic Worker Restart**: Crashed workers are not automatically revived in this baseline.
- **Local IPC Only**: Worker communication is limited to local inter-process queues on a single host.
- **Static Scheduling Only**: Jobs are pooled in a single shared queue; no adaptive routing, backpressure, or dynamic concurrency adjustments exist yet.

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
      |       Workload Generator      |  |       Failure Injector        |
      |   (Synthesizes bursty, Poisson|  |    (Injects worker stalls,    |
      |    and heavy-tailed arrivals) |  |     crashes, and drops)       |
      +---------------+---------------+  +---------------+---------------+
                      |                                  |
                      +------------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |       Execution Engine        |
                         |   (Applies execution policy)  |
                         +---------------+---------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                       v                                   v
        +-----------------------------+     +-----------------------------+
        |   Static Execution Policy   |     |  Adaptive Execution Policy  |
        |  (Fixed workers, FIFO queue,|     |  (Dynamic concurrency limits|
        |   fixed static dispatch)    |     |   backpressure, load-aware) |
        +-----------------------------+     +-----------------------------+
```

### 2.1 Workload Generator (Milestone 3)
- Will synthesize non-uniform arrival distributions (bursty arrival spikes, Poisson processes) and variable job service times to stress test scheduling behavior.

### 2.2 Failure Injector (Milestone 4)
- Will systematically inject worker crashes, execution stalls, and queue backlogs to evaluate resiliency.

### 2.3 Adaptive Execution Policies (Milestone 5)
- Will implement dynamic policies (e.g., adaptive concurrency control, dynamic worker scaling, backpressure throttling) to empirically compare against this static baseline.

---

## 3. Unresolved Decisions

1. **Networked Node Communication Protocol**:
   - For multi-machine evaluation: evaluating raw TCP sockets with lightweight binary framing vs HTTP/JSON vs gRPC.
2. **Telemetry Storage Format for Multi-Trial Sweeps**:
   - Evaluating streaming newline-delimited JSON (`.jsonl`) vs in-memory structured binary arrays exported to Parquet/CSV.
3. **Failure Recovery Semantics**:
   - Determining whether recovery should use coordinator-tracked lease renewals / heartbeats or an acknowledged transaction queue.
