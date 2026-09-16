# Titan

Titan is an experimental distributed-systems research platform designed to investigate adaptive execution strategies under dynamic workloads and fault conditions.

---

## Research Question

The core research question guiding this project is:

> **Can adaptive execution policies outperform static execution policies when workload characteristics and system failures change, while maintaining measurable reliability and performance?**

Titan answers this question through empirical measurement, reproducible trial runs, and comparative analysis between static baseline policies and adaptive execution policies.

---

## Current Status (Milestone 2: Static Baseline Runtime)

Titan has established its **Static Baseline Multi-Process Runtime**.

### What Currently Exists
- **Multi-Process Architecture (`src/titan/runtime.py`)**:
  - Coordinator executing workers as separate OS processes (`multiprocessing.Process` via `spawn`).
  - Inter-process communication queues (`multiprocessing.Queue`) for job dispatch and result draining.
  - Configurable worker count (1, 2, 4, 8, etc.).
  - Clean shutdown via sentinel tokens.
  - Worker termination tolerance (coordinator survives worker termination).
- **Job & Workload Model (`src/titan/job.py`, `src/titan/workload.py`)**:
  - Explicit, immutable `Job` and `JobResult` records with monotonic timestamps.
  - Deterministic computation eliminating non-system execution variance.
- **Metrics Engine (`src/titan/metrics.py`)**:
  - High-precision telemetry calculating wall-clock duration, throughput (jobs/sec), per-job latency, worker compute duration, and latency percentiles ($p50, p95, p99$).
- **CLI Runner (`src/titan/cli.py`)**:
  - `status` subcommand for inspecting platform configuration.
  - `run` subcommand supporting arbitrary worker counts, job batches, and JSON output.
- **Automated Test Suite (`tests/`)**:
  - 16 comprehensive automated unit and integration tests covering single-worker, multi-worker scaling, metric calculations, clean shutdown, and worker drop tolerance.
- **Authoritative Documentation**:
  - [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md): Non-negotiable principles, research scope, and non-goals.
  - [ARCHITECTURE.md](docs/ARCHITECTURE.md): Confirmed runtime architecture, queue semantics, and limitations.
  - [DECISIONS.md](docs/DECISIONS.md): Architecture Decision Records (ADR-001 through ADR-007).
  - [EXPERIMENTS.md](docs/EXPERIMENTS.md): Formal protocol template and specification for EXP-001.

### What Does NOT Exist Yet (Intentionally Unimplemented)
To keep the baseline minimal, transparent, and auditable:
- **No Adaptive Execution Policies**: No dynamic worker scaling, adaptive backpressure, or load-sensitive routing yet (scheduled for Milestone 5).
- **No Automatic Failure Recovery**: If a worker crashes mid-job, the job is not re-queued or recovered (at-most-once delivery). Failure injection and recovery are scheduled for Milestone 4.
- **No External Message Brokers**: Zero Kafka, RabbitMQ, or Redis. Standard library IPC is used exclusively.
- **No Orchestrators or Cloud Dependencies**: Zero Kubernetes, Docker, or cloud APIs.
- **No Databases**: No disk persistence or database layers.
- **No Web Frontends or Dashboards**: All output is console- and JSON-based.
- **No AI / Machine Learning**: Pure algorithmic and systems-level measurement.

---

## Process Model & Queue Semantics

```
Producer (Coordinator) ---> [ job_queue ] ---> Worker Processes (0..N-1)
                                                       |
Metrics Engine <----------- [ result_queue ] <---------+
```

1. **Submission**: Coordinator puts immutable `Job` records into `job_queue`.
2. **Acquisition**: Available worker processes acquire jobs via blocking `job_queue.get()`.
3. **Execution**: Worker executes the deterministic workload and records timestamps.
4. **Completion**: Worker deposits immutable `JobResult` into `result_queue`.
5. **Drain & Metrics**: Coordinator collects all results and calculates summary telemetry.
6. **Clean Shutdown**: Coordinator pushes `None` sentinel tokens to gracefully stop workers.

---

## Metric Definitions

- **Wall-Clock Duration ($T_{\text{wall}}$)**: Total elapsed seconds from workload submission to final result collection.
- **Throughput**: $\text{Completed Jobs} / T_{\text{wall}}$ (jobs per second).
- **Per-Job Latency**: $T_{\text{completed}} - T_{\text{created}}$ (queue wait time + processing time).
- **Processing Duration**: $T_{\text{completed}} - T_{\text{started}}$ (active compute time on the worker).
- **Percentiles ($p50, p95, p99$)**: Linear interpolation over sorted latencies.

---

## Quickstart

### Prerequisites
- Python 3.10 or later
- Standard library modules (no third-party dependencies required)

### Running a Workload via CLI
Execute a batch of 100 jobs across 4 worker processes:
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000
```

Execute with machine-readable JSON metrics:
```powershell
python src/titan/cli.py run --workers 4 --jobs 100 --work-units 2000 --json
```

Scale worker counts for comparison (e.g. 1, 2, 4, 8 workers):
```powershell
python src/titan/cli.py run --workers 1 --jobs 200 --work-units 2000
python src/titan/cli.py run --workers 2 --jobs 200 --work-units 2000
python src/titan/cli.py run --workers 4 --jobs 200 --work-units 2000
python src/titan/cli.py run --workers 8 --jobs 200 --work-units 2000
```

Check platform status:
```powershell
python src/titan/cli.py status
```

### Running Tests
Execute tests using the standard library `unittest` runner:
```powershell
python -m unittest discover -s tests -v
```

Or using `pytest`:
```powershell
python -m pytest -v
```
