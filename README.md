# Titan

**Deterministic Reliability & Failure Replay Engine**

> *"Turn distributed failure from an irreproducible incident into a reproducible experiment."*

---

## 1. What Titan Is

**Titan** is an experimental distributed-systems research platform engineered to make distributed execution failures 100% reproducible, auditable, and scientifically verifiable. 

Rather than treating process crashes, network dropouts, and retry cascades as non-deterministic runtime accidents, Titan captures execution lifecycle transitions as canonical, structured event traces. These traces enable offline sub-millisecond trace replay, deterministic contract divergence detection, automated root-cause classification, and side-by-side recovery policy evaluation—all without external runtime dependencies.

---

## 2. The Problem Titan Solves

Distributed systems are notoriously difficult to debug because production failures are rarely reproducible:
- **Heisenbugs & Concurrency Jitter**: Crashes and race conditions depend on non-deterministic thread/process scheduling and network timing.
- **Observability Blindness**: Standard distributed tracing records spans and timestamps, but cannot reconstruct intermediate distributed state or prove whether an execution invariant was violated.
- **Uncontrolled Recovery Cascades**: Systems frequently trigger retry storms or capacity loss without clear visibility into the exact cost or efficacy of their recovery policies.

Titan solves this by providing **deterministic fault injection, canonical event tracing, state-reconstructing offline replay, and automated root-cause analysis**.

---

## 3. Why Failure Reproduction Matters

In mission-critical distributed systems, knowing *that* a system failed is insufficient; engineers must know *why* it failed, *which* worker or attempt was responsible, and *whether* a candidate recovery policy would have prevented permanent data loss. 

Titan replaces post-mortem speculation with mathematical certainty:
1. **Monotonic Event Sequencing**: Every lifecycle event has an immutable, strictly increasing sequence number (`seq`).
2. **Replay Fidelity Verification**: Replays an observed trace against an expected execution contract, isolating the exact sequence number and category of the first divergence.
3. **Automated Root-Cause Analysis**: Distinguishes root causes (e.g., worker crash) from downstream consequences (e.g., lost execution attempt) and compiles ordered causal chains.

---

## 4. Core Architecture

Titan is built around a centralized coordinator and a pool of isolated worker processes using standard OS multiprocessing (`multiprocessing.get_context('spawn')`):

```
+-------------------------------------------------------------------------+
|                              COORDINATOR                                |
|  - Workload Dispatcher        - Health Monitor (process.is_alive)       |
|  - In-Flight Ownership Table  - Deduplication & Attempt Accounting     |
|  - Dynamic Worker Replacement - Structured Trace Collector             |
+---------------------+------------------------------+--------------------+
                      |                              ^
          [ job_queue ]                              | [ event_queue ]
                      v                              |
    +-----------------------------------------------------------------+
    |                     WORKER POOL (0 .. N-1)                      |
    |  - Process Isolation       - Fault Injection (os._exit mid-job) |
    |  - Job Acquisition Events  - Deterministic Compute Workloads    |
    +-----------------------------------------------------------------+
```

### Key Architectural Invariants
- **Job vs. ExecutionAttempt Separation**: A logical `Job` is immutable. Physical executions are modeled as distinct `ExecutionAttempt` instances identified by `AttemptKey = (job_id, attempt_id)`.
- **In-Flight Work Ownership**: Workers emit `JobAcquired` events upon dequeuing work. The coordinator tracks `_in_flight[worker_id][job_id]`, enabling instant discovery of orphaned work upon worker death.
- **Idempotent Deduplication**: Stale or duplicate results arriving from crashed or delayed workers are safely suppressed without corrupting completed metrics.
- **Terminal Accounting Invariant**: Across all executions, $\text{completed\_unique} + \text{failed\_unique} == \text{total\_unique\_submitted}$.
- **Zero External Dependencies**: The entire platform—including event tracing, replay engine, statistical aggregation, and vector SVG figure generation—runs natively on standard CPython (>= 3.10).

---

## 5. The Titan Pipeline

```mermaid
graph TD
    A[Scenario Definition & Workload Preset] --> B[Runtime Execution & Fault Injection]
    B --> C[Structured Execution Trace (.json)]
    C --> D[Deterministic Replay Engine]
    C --> E[Fidelity & Divergence Engine]
    C --> F[Root-Cause Failure Analysis & RCA]
    B --> G[Recovery Policy Experimentation]
    G --> H[TitanBench Canonical Failure Corpus]
    H --> I[Research Evaluation & Reproducibility Suite]
    I --> J[Publication Tables & Vector SVG Figures]
```

1. **Scenario Definition**: Configure workers, job volume, workload distribution pattern, and deterministic fault triggers (`FaultConfig`).
2. **Execution & Fault Injection**: Coordinator dispatches work; target workers trigger intentional crash-stop faults (`os._exit(42)`).
3. **Structured Tracing**: Observational trace collector captures canonical lifecycle transitions with zero execution interference.
4. **Offline Replay**: Trace replayed in isolation, reconstructing state without executing workload code or spawning processes.
5. **Divergence Detection**: Compares observed trace against expected contract; pinpoints first divergence sequence and category.
6. **Failure Analysis**: Compiles causal chains (`ROOT_CAUSE -> CONSEQUENCE -> RECOVERY_ACTION -> TERMINAL_OUTCOME`).
7. **Policy Experimentation**: Compares recovery policies (`R0` full recovery, `R1` degraded capacity, `R2` limited retry, `R3` fail-fast).
8. **TitanBench Corpus**: Evaluates 9 canonical failure scenario classes against deterministic oracles.
9. **Research Package**: Compiles empirical metrics, Markdown/CSV tables, and vector SVG charts.

---

## 6. TitanBench Failure Corpus

TitanBench provides a versioned benchmark suite of 9 canonical failure scenario classes:

| Scenario ID | Class Name | Description | Injected Fault | Expected Outcome |
| :--- | :--- | :--- | :---: | :---: |
| **TB-A-001** | `CLASS_A_BASELINE` | Baseline clean run without faults | None | `CLEAN` (100% Recovery) |
| **TB-B-001** | `CLASS_B_SINGLE_WORKER_FAILURE` | Mid-batch worker crash with replacement | Worker crash | `RECOVERED` (100% Recovery) |
| **TB-C-001** | `CLASS_C_IN_FLIGHT_FAILURE` | In-flight worker crash holding active work | Worker crash | `RECOVERED` (100% Recovery) |
| **TB-D-001** | `CLASS_D_REPEATED_FAILURE` | Sequential failures across multiple workers | Multiple crashes | `RECOVERED` (100% Recovery) |
| **TB-E-001** | `CLASS_E_RETRY_PRESSURE` | Retry exhaustion under strict budget (`max_retries=1`) | Worker crash | `UNRECOVERED` (Permanent Failure) |
| **TB-F-001** | `CLASS_F_DUPLICATE_STALE` | Duplicate and stale result suppression | Stale results | `CLEAN` (Duplicates Suppressed) |
| **TB-G-001** | `CLASS_G_CAPACITY_LOSS` | Worker failure without replacement | No replacement | `RECOVERED` (Degraded Goodput) |
| **TB-H-001** | `CLASS_H_ADVERSARIAL_TIMING` | Immediate fault on very first dispatched job | Immediate crash | `RECOVERED` (100% Recovery) |
| **TB-I-001** | `CLASS_I_LARGE_WORKLOAD` | High-volume scaling baseline | None | `CLEAN` (100% Recovery) |

---

## 7. Key Empirical Findings (Research Evaluation)

All empirical metrics are extracted from machine-readable trial artifacts under `research/`:

- **Replay Fidelity (RQ1)**: 100% equivalence rate across canonical traces. Synthetic mutations detected with 100% precision and localized to the exact sequence number.
- **Failure Classification Accuracy (RQ2)**: 100% accuracy in root-cause classification (`WORKER_FAILURE`), affected entity localization, and terminal recovery assessment against injected ground truth.
- **Recovery Policy Trade-offs (RQ3)**: Policy `R0` (automatic replacement + retries) achieves 100% recovery. Policy `R1` (no replacement) completes with a 44% goodput penalty. Policy `R2` (limited retry) terminates with unrecovered failures.
- **Tracing Overhead (RQ4)**: Tracing adds modest runtime overhead (+4.09% on 10 jobs), which amortizes to sub-4% on larger workloads. Trace files average ~158 bytes per event.
- **Replay Performance (RQ4, RQ5)**: Replay execution takes <90 microseconds; event throughput reaches ~900,000 events/second.
- **Mechanism Ablations (RQ6)**: Disabling worker replacement (`A1`) causes severe goodput degradation; eliminating retry budgets (`A2`) causes 100% job recovery failure.

---

## 8. Interactive Demo Walkthrough (9-Step Interview Tour)

Run this self-contained demonstration in under 2 minutes:

```powershell
# 1. Induce a deterministic worker crash and observe automatic recovery
python src/titan/cli.py run --scenario worker-crash --trace-file trace_crash.json

# 2. Run a clean baseline run for comparative verification
python src/titan/cli.py run --scenario baseline --trace-file trace_baseline.json

# 3. Replay the captured crash trace offline (validating state transitions)
python src/titan/cli.py replay trace_crash.json

# 4. Check replay fidelity against expected execution contract (detects divergence)
python src/titan/cli.py replay trace_crash.json --compare trace_baseline.json

# 5. Perform automated failure classification and causal chain extraction
python src/titan/cli.py analyze trace_crash.json

# 6. Compare recovery policies side-by-side (R0 full recovery vs R1 degraded capacity)
python src/titan/cli.py experiment compare TB-B-001 --policies R0,R1

# 7. Execute a canonical benchmark from the TitanBench corpus with oracle verification
python src/titan/cli.py bench run TB-B-001

# 8. Verify end-to-end research reproducibility across all plans and artifacts
python src/titan/cli.py research verify

# 9. Inspect publication-grade research tables and vector SVG figures
python src/titan/cli.py research tables
python src/titan/cli.py research figures
```

---

## 9. Installation & Prerequisites

- **Python Version**: Python 3.10 or later.
- **Dependencies**: Zero external runtime dependencies. Runs exclusively on Python's built-in standard library.
- **Installation** (editable mode):
  ```powershell
  pip install -e .
  ```

---

## 10. CLI Command Reference

### Workload Execution (`titan run`)
```powershell
# Run baseline scenario preset
python src/titan/cli.py run --scenario baseline

# Run worker crash scenario with live trace visualization
python src/titan/cli.py run --scenario worker-crash --trace

# Run custom workload with deterministic failure injection
python src/titan/cli.py run --workers 4 --jobs 50 --work-units 1000 --kill-worker worker-0 --kill-after-jobs 5
```

### Trace Replay & Divergence Detection (`titan replay`)
```powershell
# Validate trace integrity offline
python src/titan/cli.py replay trace.json

# Output structured replay diagnostics as JSON
python src/titan/cli.py replay trace.json --json

# Compare observed trace against expected contract for divergence detection
python src/titan/cli.py replay trace.json --compare expected_trace.json
```

### Root-Cause Analysis & Diagnostics (`titan analyze`)
```powershell
# Display human-readable failure analysis and causal chains
python src/titan/cli.py analyze trace.json

# Export structured analysis report as JSON
python src/titan/cli.py analyze trace.json --json
```

### TitanBench Failure Corpus (`titan bench`)
```powershell
# List all 9 canonical scenarios
python src/titan/cli.py bench list

# Execute an individual scenario
python src/titan/cli.py bench run TB-B-001

# Run full failure corpus with oracle verification
python src/titan/cli.py bench run-all
```

### Recovery Policy Experiments (`titan experiment`)
```powershell
# List registered recovery policies (R0, R1, R2, R3)
python src/titan/cli.py experiment list-policies

# Run multi-trial experiment under a specific policy
python src/titan/cli.py experiment run TB-B-001 R0 --trials 3

# Compare multiple recovery policies on the same scenario
python src/titan/cli.py experiment compare TB-B-001 --policies R0,R1,R2
```

### Research Evaluation & Reproducibility (`titan research`)
```powershell
# Execute full research evaluation suites (E1-E6 and Ablations A1-A5)
python src/titan/cli.py research run --trials 3

# Validate reproducibility of generated research artifacts
python src/titan/cli.py research verify

# List all formal evaluation plans
python src/titan/cli.py research list-plans

# Inspect generated research report
python src/titan/cli.py research report

# List generated summary tables (Markdown & CSV)
python src/titan/cli.py research tables

# List generated publication vector figures (SVG)
python src/titan/cli.py research figures
```

### Platform Status & Automated Tests
```powershell
# Check platform milestone and operational status
python src/titan/cli.py status

# Run the 207-test automated regression suite
python -m unittest discover -s tests -v
```

---

## 11. Reproducibility & Research Artifacts

Titan produces machine-readable artifacts under `research/`:

```
research/
├── plans/               # JSON evaluation plan specifications (E1-E7)
├── runs/                # Sanitized execution environment metadata
├── raw/                 # Machine-readable trial records (E1, E2, E3, Ablations)
├── summaries/           # Aggregate numerical summary metrics
├── tables/              # Tables 1–8 in Markdown (.md) and CSV (.csv)
├── figures/             # Figures 1–5 in vector SVG with companion data JSON
└── reports/             # Empirical research report (titan_research_report.md)
```

Verify the complete research package with a single command:
```powershell
python src/titan/cli.py research verify
```

---

## 12. Repository Structure

```
Titan/
├── docs/
│   ├── ARCHITECTURE.md          # Comprehensive architectural specification
│   ├── DECISIONS.md             # Architecture Decision Records (ADR-001 - ADR-022)
│   ├── EXPERIMENTS.md           # Experimental methodology & evaluation protocols
│   └── PROJECT_CONSTITUTION.md  # Core principles, research scope, and non-goals
├── research/                    # Machine-readable experimental evaluation package
│   ├── figures/                 # Publication-ready vector SVG charts (Figures 1-5)
│   ├── plans/                   # Canonical evaluation plans (E1-E7)
│   ├── reports/                 # Comprehensive empirical research report
│   ├── tables/                  # Result tables in Markdown & CSV (Tables 1-8)
│   └── summaries/               # Statistical metric aggregations
├── src/titan/
│   ├── analysis.py              # Deterministic root-cause analysis & causal chains
│   ├── cli.py                   # Unified CLI entry point
│   ├── job.py                   # Job and ExecutionAttempt model
│   ├── metrics.py               # Recovery and latency telemetry
│   ├── replay.py                # Trace replay & fidelity divergence engine
│   ├── runtime.py               # Coordinator process & worker lifecycle
│   ├── scenario.py              # Deterministic scenario definitions & fault config
│   ├── trace.py                 # Structured execution event tracing
│   ├── worker.py                # Worker process loop & fault execution
│   ├── bench/                   # TitanBench canonical failure corpus & runner
│   ├── experiment/              # Recovery policy models & comparison harness
│   └── research/                # Research suites, baselines, ablations & tables
├── tests/                       # 207 automated unit and integration tests
├── pyproject.toml               # Package configuration & metadata
└── README.md                    # Project documentation & demonstration guide
```

---

## 13. Key Architectural Decisions (ADR Summary)

All major design decisions are documented in [`docs/DECISIONS.md`](docs/DECISIONS.md):
- **ADR-001**: Clean-slate repository initialization and project constitution.
- **ADR-002**: Local multi-process concurrency model using standard library primitives.
- **ADR-003**: Deterministic failure injection via `os._exit(42)` process termination.
- **ADR-004**: Explicit Job and ExecutionAttempt model with AttemptKey tracking.
- **ADR-005**: In-flight work ownership and idempotent deduplication.
- **ADR-007**: Structured execution event tracing with monotonic sequencing.
- **ADR-008**: Deterministic offline trace replay engine.
- **ADR-009**: Replay fidelity verification and divergence category taxonomy.
- **ADR-010**: Rule-based root-cause failure analysis and causal chain reconstruction.
- **ADR-011**: TitanBench systematic canonical failure corpus.
- **ADR-014**: Recovery policy modeling (`R0` through `R3`) and fair comparison invariant.
- **ADR-020**: Tracing overhead, replay cost, and system stress evaluation.
- **ADR-021**: Research-grade evaluation framework, baselines, and vector graphics.
- **ADR-022**: Final system architecture freeze, verification baseline, and release readiness.

---

## 14. Scope Boundaries & Technical Limitations

In accordance with scientific honesty:
- **Local Multiprocessing Boundary**: Titan is evaluated on a single physical host using OS processes. Cross-host network partitions, clock skews, and asymmetric packet drops are outside the current static runtime scope.
- **Windows Process Spawning Overhead**: Under Windows `spawn`, process initialization incurs ~50–200ms latency. This startup overhead dominates very short micro-benchmarks (<20 jobs) but amortizes as batch sizes scale.
- **Synthetic Compute Workloads**: Workload units simulate CPU-bound execution via arithmetic operations; external I/O stalls and database locking dynamics are not simulated.
- **Sample Size Boundaries**: Timing-sensitive evaluations use bounded repetitions ($N=3$ to $N=5$) suitable for fast regression testing. Minor latency jitter reflects host OS scheduling variations.

---

## 15. Honest Guarantees & Assumptions

- **What Titan Guarantees**:
  - Deterministic replay state equivalence across identical canonical traces.
  - 100% localization of trace contract violations to the exact sequence number.
  - Zero zombie worker process leaks upon coordinator shutdown or scenario completion.
  - Terminal accounting invariant: no submitted job is lost or counted multiple times.
  - Pure standard-library execution with zero external runtime dependencies.
- **What Titan Does NOT Claim**:
  - Does NOT claim infinite distributed scalability or multi-datacenter consensus.
  - Does NOT claim zero tracing overhead (tracing introduces a measurable +4.09% overhead on small runs).
  - Does NOT claim recovery under zero retry budgets (retries are mathematically necessary when worker crashes destroy in-flight attempts).
