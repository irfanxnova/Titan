# Titan

Titan is an experimental distributed-systems research platform designed to investigate adaptive execution strategies under dynamic workloads and fault conditions.

---

## Research Question

The central scientific and engineering inquiry governing all work in Titan is:

> **Can adaptive execution policies outperform static execution policies when workload characteristics and system failures change, while maintaining measurable reliability and performance?**

Titan answers this question through empirical measurement, reproducible trial runs, and comparative analysis between static baseline policies and adaptive execution policies.

---

## Current Status (Milestone 3: Failure Injection + Recovery)

Titan has implemented its **Failure-Aware Multi-Process Runtime**, featuring in-flight ownership tracking, deterministic failure injection, at-least-once processing semantics, coordinator deduplication, and capacity-restoring worker replacement.

### What Currently Exists
- **Failure Detection & Process Lifecycle (`src/titan/runtime.py`)**:
  - Continuous health monitoring via OS process inspection (`process.is_alive()` and `process.exitcode`).
  - Strict categorization: normal shutdown, intentional test failure injection (`os._exit(42)`), and unexpected process crashes.
- **In-Flight Work Ownership Tracking (`src/titan/job.py`, `src/titan/worker.py`)**:
  - Explicit `JobAcquired` ownership events emitted by workers upon dequeuing.
  - Coordinator maintains `_in_flight[worker_id][job_id]` registry to instantly identify unfinished work if a worker dies.
- **At-Least-Once Semantics & Deduplication (`src/titan/runtime.py`, `src/titan/metrics.py`)**:
  - Automatic retry and requeuing up to `--max-retries` (default: 3).
  - Idempotent deduplication: each unique `job_id` has at most one final completed result. Stale or duplicate results from earlier attempts are safely dropped.
  - Strict terminal accounting invariant: $\text{completed\_unique} + \text{failed\_unique} == \text{total\_unique\_submitted}$.
- **Deterministic Failure Injection (`src/titan/cli.py`, `src/titan/worker.py`)**:
  - Deterministic CLI flags: `--kill-worker <ID>` and `--kill-after-jobs <N>` trigger real OS process exits (`os._exit(42)`).
- **Worker Replacement (`src/titan/runtime.py`)**:
  - Automatically spawns replacement workers (e.g. `worker-0-r1`) to restore active worker pool capacity back to the configured count.
- **Recovery Telemetry Subsystem (`src/titan/metrics.py`)**:
  - Computes wall-clock time, primary throughput (unique jobs/sec), attempt throughput, worker failures, retries, recovered jobs, permanently failed jobs, duplicate results ignored, and recovery duration.
- **Authoritative Documentation**:
  - [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md): Non-negotiable principles, research scope, and non-goals.
  - [ARCHITECTURE.md](docs/ARCHITECTURE.md): Confirmed runtime architecture, failure recovery semantics, and limitations.
  - [DECISIONS.md](docs/DECISIONS.md): Architecture Decision Records (ADR-001 through ADR-010, including ADR-008 rejecting exactly-once execution claims).
  - [EXPERIMENTS.md](docs/EXPERIMENTS.md): Formal protocol template and completed trials for EXP-002.

### What Does NOT Exist Yet (Intentionally Unimplemented)
To preserve architectural simplicity and scientific rigor:
- **No Adaptive Scheduling**: No dynamic concurrency limits, adaptive backpressure, or load-sensitive routing yet (scheduled for Milestone 5).
- **No External Message Brokers**: Zero Kafka, RabbitMQ, or Redis. Standard library IPC queues are used exclusively.
- **No Orchestrators or Cloud Dependencies**: Zero Kubernetes, Docker, or cloud APIs.
- **No Databases**: No disk persistence or database layers.
- **No Web Frontends or Dashboards**: All output is console- and JSON-based.
- **No AI / Machine Learning**: Pure algorithmic and systems-level measurement.

---

## Process Model & Recovery Flow

```
Producer (Coordinator) ---> [ job_queue ] ---> Worker Processes (0..N-1)
      |                            ^                    | (Acquired & Results)
      | (Requeue on worker death)  |                    v
      +----------------------------+ <----------- [ event_queue ]
                                                        |
Deduplication & Accounting <----------------------------+
```

1. **Submission**: Coordinator enqueues immutable `Job` records.
2. **Acquisition**: Worker grabs job, emits `JobAcquired` event, establishing coordinator in-flight ownership.
3. **Execution**: Worker computes deterministic workload and posts `JobResult`.
4. **Failure Injection**: If configured (`--kill-worker`, `--kill-after-jobs`), worker triggers `os._exit(42)` mid-job.
5. **Detection & Recovery**: Coordinator detects dead worker, scans `_in_flight[worker_id]`, increments attempt count, and requeues uncompleted jobs onto `job_queue`.
6. **Worker Replacement**: Coordinator spawns a replacement worker to restore configured concurrency.
7. **Deduplication**: If a duplicate or stale result arrives from an earlier attempt, it is discarded without inflating completed counts.

---

## Quickstart

### Prerequisites
- Python 3.10 or later
- Standard library modules (zero external dependencies)

### Running Baseline Workload (No Failures)
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000
```

### Running Workload with Deterministic Worker Failure & Recovery
Kill worker 2 after it completes 5 jobs:
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000 --kill-worker 2 --kill-after-jobs 5
```

Inspect recovery telemetry formatted as JSON:
```powershell
python src/titan/cli.py run --workers 4 --jobs 50 --work-units 2000 --kill-worker 1 --kill-after-jobs 5 --json
```

Check platform status:
```powershell
python src/titan/cli.py status
```

### Running Automated Tests
Run the 21-test automated suite using Python's built-in runner:
```powershell
python -m unittest discover -s tests -v
```

Or using `pytest`:
```powershell
pytest -v
```
