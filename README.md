# Titan

Titan is an experimental distributed-systems research platform designed to investigate adaptive execution strategies under dynamic workloads and fault conditions.

---

## Research Question

The central scientific and engineering inquiry governing all work in Titan is:

> **Can adaptive execution policies outperform static execution policies when workload characteristics and system failures change, while maintaining measurable reliability and performance?**

Titan answers this question through empirical measurement, reproducible trial runs, and comparative analysis between static baseline policies and adaptive execution policies.

---

## Current Status (Milestone 4: Structured Event Tracing & Execution History)

Titan has implemented its **Failure-Aware Multi-Process Runtime with Structured Event Tracing**, featuring in-flight ownership tracking, deterministic failure injection, at-least-once processing semantics, coordinator deduplication, capacity-restoring worker replacement, and canonical execution event tracing.

### What Currently Exists
- **Structured Execution Event Tracing (`src/titan/trace.py`)**:
  - Canonical logical event model (`TraceEvent`) with monotonic sequence numbers (`seq`), explicit lifecycle event types (`EventType`), observation timestamps, and structured payloads.
  - Lifecycle transitions: `RUN_STARTED`, `RUN_COMPLETED`, `WORKER_STARTED`, `WORKER_EXITED`, `WORKER_FAILED`, `WORKER_REPLACED`, `JOB_CREATED`, `JOB_ASSIGNED`, `JOB_STARTED`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_LOST`, `RETRY_SCHEDULED`, `JOB_REASSIGNED`.
  - Strict separation of concerns: observational trace collector (`ExecutionTrace`) records history without competing with or influencing authoritative coordinator state.
  - First-class JSON export and CLI visualization via `--trace` and `--trace-file`.
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
- **Deterministic Scenario & Fault-Injection System (`src/titan/scenario.py`)**:
  - Repeatable workload and failure scenario definitions (`Scenario`, `FaultConfig`, `ScenarioResult`).
  - Strict input validation preventing out-of-range targets or partial execution.
  - Workload distribution patterns: `uniform`, `linear`, and seeded `bimodal`.
  - Standard presets: `baseline` (normal execution), `worker-crash` (injected crash of worker-0), and `stress-recovery` (concurrency stress with recovery).
- **Explicit Execution Model (`src/titan/job.py`, `src/titan/runtime.py`)**:
  - Clear separation between logical jobs (`Job`) and concrete physical executions (`ExecutionAttempt`).
  - Distinguishable composite attempt identity: `AttemptKey = (job_id, attempt_id)`.
  - Attempt lifecycle tracking (`AttemptStatus`): `CREATED`, `ASSIGNED`, `RUNNING`, `COMPLETED`, `FAILED`, `LOST`, `RETRY_PENDING`.
  - Authoritative coordinator ownership registry: `_attempt_ownership[AttemptKey] = worker_id`.
  - Robust deduplication distinguishing valid, duplicate, and stale completions.
- **Worker Replacement & Entity Tracking (`src/titan/runtime.py`)**:
  - Automatically spawns replacement workers (e.g. `worker-0-r1`) with distinct identities while preserving historical records (`WorkerRecord`).
- **Recovery Telemetry Subsystem (`src/titan/metrics.py`)**:
  - Computes wall-clock time, primary throughput (unique jobs/sec), attempt throughput, worker failures, retries, recovered jobs, permanently failed jobs, duplicate results ignored, and recovery duration.
- **Authoritative Documentation**:
  - [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md): Non-negotiable principles, research scope, and non-goals.
  - [ARCHITECTURE.md](docs/ARCHITECTURE.md): Confirmed runtime architecture, execution model, failure recovery semantics, structured event tracing, and limitations.
  - [DECISIONS.md](docs/DECISIONS.md): Architecture Decision Records (ADR-001 through ADR-014, including ADR-014 on structured event tracing).
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
4. **Failure Injection**: If configured (`--kill-worker`, `--kill-after-jobs`, or `--scenario worker-crash`), target worker triggers `os._exit(42)` mid-job.
5. **Detection & Recovery**: Coordinator detects dead worker, scans `_in_flight[worker_id]`, increments attempt count, and requeues uncompleted jobs onto `job_queue`.
6. **Worker Replacement**: Coordinator spawns a replacement worker to restore configured concurrency.
7. **Deduplication**: If a duplicate or stale result arrives from an earlier attempt, it is discarded without inflating completed counts.

---

## Quickstart

### Prerequisites
- Python 3.10 or later
- Standard library modules (zero external dependencies)

### Running Predefined Scenarios
Run baseline execution (2 workers, 20 jobs, no failures):
```powershell
python src/titan/cli.py run --scenario baseline
```

Run deterministic worker crash and recovery scenario:
```powershell
python src/titan/cli.py run --scenario worker-crash
```

Run scenario with structured execution trace visualization:
```powershell
python src/titan/cli.py run --scenario worker-crash --trace
```

Run stress recovery scenario formatted as JSON (including trace array):
```powershell
python src/titan/cli.py run --scenario stress-recovery --json
```

Export execution trace to a JSON file:
```powershell
python src/titan/cli.py run --scenario baseline --trace-file trace.json
```

### Running Custom Workloads & Fault Injection
Execute a custom workload with deterministic failure injection:
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000 --kill-worker 2 --kill-after-jobs 5
```

Check platform status and available scenario presets:
```powershell
python src/titan/cli.py status
```

### Running Automated Tests
Run the 67-test automated suite using Python's built-in standard library runner (zero external dependencies required):
```powershell
python -m unittest discover -s tests -v
```

Or using `pytest` (if installed in your Python environment):
```powershell
pytest -v
```
