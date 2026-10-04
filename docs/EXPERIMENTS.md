# Titan Experiment Framework

This document outlines the standard protocol for conducting and documenting experiments in Titan.

All empirical evaluations comparing static, failure-aware, and adaptive execution policies must be specified using the template below before execution.

---

## Experiment Registry

| Experiment ID | Title | Baseline Policy | Candidate Policy / Variables | Status |
|:---|:---|:---|:---|:---|
| **EXP-001** | Static Baseline Worker Scaling (1, 2, 4, 8 workers) | Static 1-Worker Runtime | Static N-Workers (1, 2, 4, 8) | Planned |
| **EXP-002** | Worker Failure Recovery under Batch Workload | Baseline (No Failure) | Single Injected Worker Failure (`--kill-worker 2 --kill-after-jobs 5`) | Completed |

---

## Specification & Results: EXP-002

# Experiment EXP-002: Worker Failure Recovery

- **Experiment ID**: EXP-002
- **Date**: 2026-09-16
- **Status**: Completed (Milestone 3 Verification Trial)

### 1. Hypothesis
When a worker process experiences an abrupt crash mid-execution holding in-flight work, the failure-aware runtime will:
1. Detect process termination via OS exit codes without crashing the coordinator.
2. Identify in-flight jobs owned by the terminated worker and requeue them.
3. Complete 100% of unique submitted jobs ($\text{completed} + \text{failed} == \text{submitted}$) without double-counting completions.
4. Incur a measurable recovery overhead in total execution attempts and tail latency compared to the baseline.

### 2. Baseline
Trial A: Normal static multi-process runtime execution with 4 workers and 0 injected failures.

### 3. Independent Variables
- Failure injection condition:
  - Trial A: Baseline (no worker killed).
  - Trial B: Injected failure (`--kill-worker 2 --kill-after-jobs 5`).

### 4. Dependent Variables (Metrics)
- Total unique jobs submitted ($N_{\text{submitted}}$)
- Total execution attempts ($N_{\text{attempts}}$)
- Total unique jobs completed ($N_{\text{completed}}$)
- Total unique jobs failed ($N_{\text{failed}}$)
- Total retries initiated
- Worker failures detected
- In-flight jobs recovered
- Recovery duration (seconds)
- Wall-clock time (seconds)
- Primary throughput (unique jobs/second)
- Attempt throughput (attempts/second)
- Average latency (milliseconds)
- p50 / p95 / p99 latency (milliseconds)

### 5. Workload Profile
- Total unique jobs: 100
- Work units per job: 2,000 units (deterministic modular arithmetic)
- Concurrency: 4 worker processes

### 6. Failure Scenario
- Trial A: None.
- Trial B: Worker `worker-2` terminates abruptly via `os._exit(42)` immediately after acquiring its 6th job (having completed 5 jobs).

### 7. Measurement Method & Telemetry
- Monotonic timestamps (`time.perf_counter()`) captured for job submission, acquisition, started, and completed.
- Coordinator monitors process health and computes aggregated `RunMetrics`.

### 8. Expected Result
- Trial A will have exactly 100 execution attempts for 100 jobs, with 0 retries and 0 failures.
- Trial B will detect 1 worker failure, initiate 1 retry, recover 1 job, and achieve exactly 100 completed unique jobs across 101 execution attempts.

### 9. Actual Result (Observed in Milestone 3)

| Metric | Trial A (Baseline) | Trial B (Injected Failure) | Delta / Impact |
|:---|:---|:---|:---|
| **Command** | `python src/titan/cli.py run -w 4 -j 100 -u 2000` | `python src/titan/cli.py run -w 4 -j 100 -u 2000 --kill-worker 2 --kill-after-jobs 5` | — |
| **Configured Workers** | 4 | 4 | Identical |
| **Killed Worker** | None | `worker-2` | 1 worker killed |
| **Failure Point** | None | After 5 jobs completed | Mid-execution |
| **Jobs Submitted (Unique)** | 100 | 100 | 100 |
| **Total Execution Attempts** | 100 | 101 | +1 attempt |
| **Jobs Completed (Unique)** | 100 | 100 | 100% completed |
| **Jobs Failed (Unique)** | 0 | 0 | 0 |
| **Total Retries** | 0 | 1 | +1 retry |
| **Worker Failures** | 0 | 1 | 1 detected |
| **Jobs Recovered** | 0 | 1 | 1 recovered |
| **Duplicate Results Ignored** | 0 | 0 | 0 |
| **Recovery Duration** | 0.0000 s | 0.0165 s | +16.5 ms recovery |
| **Wall-Clock Time** | 0.1549 s | 0.1440 s | Comparable |
| **Primary Throughput** | 645.62 unique jobs/s | 694.62 unique jobs/s | Nominal |
| **Attempt Throughput** | 645.62 attempts/s | 701.56 attempts/s | Nominal |
| **Average Latency** | 157.233 ms | 186.722 ms | +29.489 ms |
| **p50 Latency** | 157.763 ms | 186.428 ms | +28.665 ms |
| **p95 Latency** | 163.792 ms | 190.095 ms | +26.303 ms |
| **p99 Latency** | 164.120 ms | 190.957 ms | +26.837 ms |

### 10. Conclusion
1. **Hypothesis Confirmed**: The coordinator detected the abrupt termination of `worker-2`, identified the in-flight job held by `worker-2`, and successfully requeued it.
2. **Terminal Accounting Verified**: $\text{completed\_unique} (100) + \text{failed\_unique} (0) == \text{submitted} (100)$. Exactly 101 execution attempts were executed, reflecting the single recovered job attempt.
3. **No Double-Counting**: Every unique job ID received exactly one final successful result.
4. **Latency Impact**: The failure recovery cycle introduced a ~28 ms shift in p50 latency and a 16.5 ms recovery interval, reflecting worker replacement initialization and job re-execution.

---

## TitanBench: Canonical Failure Corpus for Future Experiments

Beginning in Milestone 8, **TitanBench** (`src/titan/bench/`) serves as Titan's authoritative failure corpus and experimental harness. All future recovery-policy comparisons, ablation studies, and fault evaluations will draw directly from the standardized TitanBench scenario specifications and runner.

### Canonical Scenarios Overview

| Scenario ID | Class | Description | Workers | Jobs | Faults | Expected Outcome |
|:---|:---|:---|:---:|:---:|:---|:---|
| **TB-A-001** | `CLASS_A_BASELINE` | Clean deterministic baseline | 2 | 10 | None | CLEAN (0 failures, 10 completed) |
| **TB-B-001** | `CLASS_B_SINGLE_WORKER_FAILURE` | Single worker failure and replacement | 2 | 10 | Worker 0 killed after 2 jobs | RECOVERED (1 root failure, 10 completed) |
| **TB-C-001** | `CLASS_C_IN_FLIGHT_FAILURE` | In-flight execution interruption | 2 | 8 | Worker 0 killed after 1 job | RECOVERED (1 root failure, 8 completed) |
| **TB-D-001** | `CLASS_D_REPEATED_FAILURE` | Sequential failures across workers | 3 | 15 | Worker 0 (2 jobs), Worker 1 (4 jobs) | RECOVERED (2 root failures, 15 completed) |
| **TB-E-001** | `CLASS_E_RETRY_PRESSURE` | Retry exhaustion under max_retries=1 | 2 | 6 | Worker 0 killed after 1 job | UNRECOVERED (1 root failure, 1 failed job) |
| **TB-F-001** | `CLASS_F_DUPLICATE_STALE` | Duplicate completion result suppression | 2 | 10 | 2 duplicate completions injected | CLEAN (2 duplicates ignored, 10 completed) |
| **TB-G-001** | `CLASS_G_CAPACITY_LOSS` | Worker loss without replacement | 2 | 10 | Worker 0 killed (no replacement) | RECOVERED (1 root failure, 0 replacements) |
| **TB-H-001** | `CLASS_H_ADVERSARIAL_TIMING` | Lifecycle boundary fault on acquisition | 2 | 8 | Worker 0 killed at kill_after_jobs=0 | RECOVERED (1 root failure, 8 completed) |
| **TB-I-001** | `CLASS_I_LARGE_WORKLOAD` | Scaled worker concurrency and workload | 4 | 40 | None | CLEAN (0 failures, 40 completed) |

### Executing the Corpus

```bash
# List all registered canonical scenarios
python src/titan/cli.py bench list

# Run a specific benchmark scenario
python src/titan/cli.py bench run TB-B-001

# Run the complete failure corpus with automated oracle evaluation
python src/titan/cli.py bench run-all

# Output machine-readable JSON results
python src/titan/cli.py bench run TB-B-001 --json
```

Artifacts are deterministically structured under `results/<scenario-id>/` containing `scenario.json`, `trace.json`, `replay.json`, `analysis.json`, and `result.json`.
