# Titan

Titan is an experimental distributed-systems research platform designed to investigate adaptive execution strategies under dynamic workloads and fault conditions.

---

## Research Question

The central scientific and engineering inquiry governing all work in Titan is:

> **Can adaptive execution policies outperform static execution policies when workload characteristics and system failures change, while maintaining measurable reliability and performance?**

Titan answers this question through empirical measurement, reproducible trial runs, and comparative analysis between static baseline policies and adaptive execution policies.

---

## Current Status (Milestone 8: TitanBench Failure Corpus & Scenario Runner)

Titan has implemented **TitanBench: A Versioned, Reproducible Failure Corpus and Scenario Runner**, building atop its authoritative failure-aware runtime, deterministic scenario definitions, structured event tracing, deterministic replay, fidelity divergence detection, and root-cause failure analysis.

### What Currently Exists
- **TitanBench Failure Corpus & Scenario Runner (`src/titan/bench/`)**:
  - Systematic, versioned failure corpus containing 9 canonical scenario classes (A through I) with stable identifiers (`TB-A-001` through `TB-I-001`).
  - Automated benchmark pipeline: Scenario Definition -> Titan Execution -> Trace Artifact -> Trace Replay -> Root-Cause Failure Analysis -> Oracle Evaluation -> Machine-Readable Result Artifacts.
  - Deterministic oracles (`ExpectedBehavior`): Evaluates execution, replay validity, root-cause classifications, and failure recoveries against explicit assertions.
  - Distinguishes expected failure behavior (e.g. unrecovered retry exhaustion) from framework errors.
  - Standardized JSON result artifacts (`scenario.json`, `trace.json`, `replay.json`, `analysis.json`, `result.json`) persisted under `results/<scenario-id>/`.
  - Dedicated CLI commands: `titan bench list`, `titan bench run <id> [--json]`, and `titan bench run-all [--json]`.
- **Deterministic Failure Classification & Root-Cause Analysis (`src/titan/analysis.py`)**:
  - Deterministic rule-based analysis consuming canonical traces, replay state, and divergence results without mutating them.
  - Answers what failed, where, which logical entity was affected, immediate failure mode, recovery action, and recovery outcome.
  - Failure taxonomy (`FailureClass`): `WORKER_FAILURE`, `JOB_FAILURE`, `LOST_EXECUTION`, `RETRY_EXHAUSTION`, `OWNERSHIP_FAILURE`, `REPLAY_DIVERGENCE`, and `RUN_FAILURE`.
  - Distinguishes root causes from downstream consequences (e.g., worker crash is root cause; lost execution is a consequence).
  - Reconstructs strictly ordered causal chains (`CausalChainNode`) from `ROOT_CAUSE` -> `CONSEQUENCE` -> `RECOVERY_ACTION` -> `TERMINAL_OUTCOME` ordered by canonical sequence numbers (`seq`).
  - Classifies recovery status (`RecoveryOutcome`): `RECOVERED`, `UNRECOVERED`, or `NOT_APPLICABLE`.
  - First-class CLI support via `analyze` with human-readable and structured JSON reports (`AnalysisReport`).
- **Replay Fidelity & Divergence Detection (`src/titan/replay.py`)**:
  - Compares observed execution traces or replay results against expected deterministic execution contracts.
  - Explicit divergence model (`DivergenceCategory`, `DivergenceRecord`) distinguishing `EVENT`, `STATE`, `OWNERSHIP`, `RETRY`, `WORKER`, and `OUTCOME` divergences.
  - Strict deterministic equivalence: evaluates sequence ordering, event types, job/attempt identities, worker ownership, retry decisions, and terminal outcomes while ignoring wall-clock timestamps and latency.
  - 100% deterministic first-divergence localization.
  - CLI integration via `--compare <expected_trace_file>` with `REPLAY EQUIVALENT` vs `REPLAY DIVERGED` human-readable reporting and structured JSON diagnostics (`FidelityResult`).
- **Deterministic Trace Replay Engine (`src/titan/replay.py`)**:
  - Reconstructs and validates the logical execution history of a run strictly from its structured trace.
  - Dedicated replay state model (`ReplayState`, `ReplayWorkerState`, `ReplayJobState`, `ReplayAttemptState`).
  - Purely observational: executes zero workload code, spawns zero workers, invokes zero fault injection, and has no dependency on wall-clock time.
  - Strict canonical ordering via sequence numbers (`seq`).
  - Rigorous lifecycle transition validation: detects sequence breaks, run boundary violations, unknown entities, unassigned starts, illegal retries/reassignments, and duplicate completions.
  - Structured JSON and human-readable diagnostic reporting (`ReplayResult`).
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
  - [ARCHITECTURE.md](docs/ARCHITECTURE.md): Confirmed runtime architecture, execution model, failure recovery semantics, structured event tracing, replay engine, and fidelity detection.
  - [DECISIONS.md](docs/DECISIONS.md): Architecture Decision Records (ADR-001 through ADR-016, including ADR-016 on replay fidelity and divergence detection).
  - [EXPERIMENTS.md](docs/EXPERIMENTS.md): Formal protocol template and completed trials for EXP-002.

### What Does NOT Exist Yet (Intentionally Unimplemented)
To preserve architectural simplicity and scientific rigor:
- **No Adaptive Scheduling**: No dynamic concurrency limits, adaptive backpressure, or load-sensitive routing yet (scheduled for subsequent milestones).
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

### Replaying Execution Traces
Replay a captured trace file and validate its logical consistency:
```powershell
python src/titan/cli.py replay trace.json
```

Replay a trace file and output structured JSON diagnostics:
```powershell
python src/titan/cli.py replay trace.json --json
```

Compare an observed trace against an expected trace for fidelity and divergence detection:
```powershell
python src/titan/cli.py replay trace.json --compare expected_trace.json
```

Compare traces with structured JSON divergence output:
```powershell
python src/titan/cli.py replay trace.json --compare expected_trace.json --json
```

### Analyzing Execution Traces
Perform deterministic failure classification and root-cause analysis on a trace:
```powershell
python src/titan/cli.py analyze trace.json
```

Output structured failure analysis report as JSON:
```powershell
python src/titan/cli.py analyze trace.json --json
```

Perform failure analysis with expected trace divergence detection:
```powershell
python src/titan/cli.py analyze trace.json --expected expected_trace.json
```

### Running TitanBench Scenarios
List all canonical failure scenarios registered in the TitanBench corpus:
```powershell
python src/titan/cli.py bench list
```

Run an individual benchmark scenario by stable ID:
```powershell
python src/titan/cli.py bench run TB-B-001
```

Run an individual benchmark scenario and export structured result as JSON:
```powershell
python src/titan/cli.py bench run TB-B-001 --json
```

Execute the full canonical TitanBench failure corpus (Classes A through I) with automated oracle verification:
```powershell
python src/titan/cli.py bench run-all
```

### Running Custom Workloads & Fault Injection
Execute a custom workload with deterministic failure injection:
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000 --kill-worker 2 --kill-after-jobs 5
```

Check platform status, milestone version, and available scenario presets:
```powershell
python src/titan/cli.py status
```

### Running Automated Tests
Run the 141-test automated suite using Python's built-in standard library runner (zero external dependencies required):
```powershell
python -m unittest discover -s tests -v
```

Or using `pytest` (if installed in your Python environment):
```powershell
pytest -v
```


