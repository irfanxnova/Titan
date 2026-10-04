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

---

## Recovery-Policy Experimentation Framework (Milestone 9)

Beginning in Milestone 9, Titan provides an automated, fair, and reproducible framework (`src/titan/experiment/`) to evaluate and compare recovery policies on canonical TitanBench scenarios.

### 1. Research Question
> **How do different recovery policies affect recovery time, duplicate work, lost work, goodput, latency, and resource usage under controlled distributed failures?**

### 2. Recovery Policy Model
Policies are defined as immutable configurations with stable identifiers:

| Policy ID | Name | Replace Workers | Max Retries | Description |
|:---|:---|:---:|:---:|:---|
| **R0** | `baseline-full-recovery` | True | 3 | Standard Titan baseline: automatic worker replacement and default retry budget. |
| **R1** | `no-worker-replacement` | False | 3 | Failed workers are not replaced; surviving workers shoulder remaining workload. |
| **R2** | `limited-retry` | True | 1 | Worker replacement enabled; retry budget minimized (zero retries allowed upon failure). |
| **R3** | `minimal-recovery-disabled` | False | 1 | Minimal recovery: replacement disabled and retry budget minimized. |

### 3. Fair Comparison Invariant
When comparing policies on a benchmark scenario, **all non-policy variables are held strictly constant**:
- Identical workload jobs count, work units, and distribution pattern.
- Identical initial worker concurrency.
- Identical random seed and deterministic execution sequence.
- Identical failure injection timing, target worker ID, and threshold.
- Identical measurement harness, trace capture, and replay validator.
- Only policy-specific recovery parameters (`replace_failed_workers`, `max_retries`) vary.

### 4. Rigorous Metric Definitions & Honesty Rule

Every metric has an explicit mathematical formula, units, and scope:

| Metric | Formula | Units | Scope | Limitations |
|:---|:---|:---:|:---|:---|
| **Recovery Rate** | $1.0$ if $\text{status} \in \{\text{CLEAN}, \text{RECOVERED}\} \land \text{failed} == 0$ else $0.0$ | ratio | Trial / Policy | Binary per-trial outcome; partial completion with failures counts as 0.0. |
| **Useful Completions** | $\text{count}(\text{distinct completed jobs})$ | jobs | Workload | Ignores duplicate deliveries. |
| **Total Attempts** | $\text{count}(\text{attempts dispatched})$ | attempts | Workload | Includes initial attempts and retries. |
| **Retry Count** | $\text{count}(\text{EventType.RETRY\_SCHEDULED})$ | retries | Workload | Scheduled retry actions. |
| **Duplicate Work** | $\max(0, \text{total\_attempts} - \text{useful\_completions})$ | executions | Workload | Physical attempt dispatches spent beyond unique jobs. |
| **Lost Work** | $\text{count}(\text{EventType.JOB\_LOST})$ | attempts | Workload | In-flight attempts aborted mid-execution by worker crashes. |
| **Worker Replacements**| $\text{count}(\text{EventType.WORKER\_REPLACED})$ | workers | Workload | Replacement processes spawned. |
| **Recovery Duration** | $t_{\text{end}} - t_{\text{first\_failure}}$ if failure else $0.0$ | seconds | Failure interval | Includes execution of remaining jobs after requeue. |
| **Goodput** | $\text{useful\_completions} / t_{\text{wall\_clock}}$ | jobs/s | Workload | Excludes redundant retries or failed attempts from numerator. |
| **Average Latency** | $\text{mean}(t_{\text{complete}} - t_{\text{submit}}) \times 1000$ | ms | Completed jobs | End-to-end elapsed latency. |

#### Intentionally Unavailable Metrics (Metric Honesty Rule)
- **CPU Utilization (%)**: Not polled in-process to avoid runtime scheduling distortion.
- **Worker Memory RSS**: Subprocess memory consumption is not continuously polled in the static runtime.
- **Network I/O**: Inter-process communication uses OS pipes/queues, not network packets.
- **Partial Job Progress Lost**: Titan jobs execute as atomic units; intra-job progress is uncommitted and discarded as a unit upon failure.
- **Failure Detection Latency**: Exact OS process termination time is not recorded separately from coordinator queue poll detection.

---

### 5. Empirical Results: Required Milestone 9 Verification Matrix

The 6 canonical experiments were executed through the Titan experiment runner:

| Experiment | Scenario | Policy | Recovery Rate | Completed / Total | Retries | Replacements | Goodput (jobs/s) | Wall-Clock (s) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Exp 1** | TB-B-001 | R0 | 100.0% | 10 / 10 | 1 | 1 | 70.17 | 0.1425 |
| **Exp 2** | TB-B-001 | R1 | 100.0% | 10 / 10 | 0 | 0 | 118.29 | 0.0845 |
| **Exp 3** | TB-C-001 | R0 | 100.0% | 8 / 8 | 1 | 1 | 63.11 | 0.1268 |
| **Exp 4** | TB-C-001 | R1 | 100.0% | 8 / 8 | 1 | 0 | 80.41 | 0.0995 |
| **Exp 5** | TB-E-001 | R0 | 100.0% | 6 / 6 | 1 | 1 | 55.13 | 0.1088 |
| **Exp 6** | TB-E-001 | R2 | 0.0% | 5 / 6 | 0 | 1 | 42.50 | 0.1176 |

---

### 6. Side-by-Side Policy Comparisons

#### Comparison A: In-Flight Failure under Baseline vs. Degraded Capacity (TB-C-001: R0 vs. R1)
Command: `python src/titan/cli.py experiment compare TB-C-001 --policies R0,R1`

| Metric | R0 (Baseline Recovery) | R1 (No Worker Replacement) |
|:---|:---|:---|
| **Recovery Rate (%)** | 100.0% | 100.0% |
| **Completed Jobs** | 8.0 | 8.0 |
| **Failed Jobs** | 0.0 | 0.0 |
| **Total Attempts** | 9.0 | 9.0 |
| **Retries** | 1.0 | 1.0 |
| **Duplicate Work** | 1.0 | 1.0 |
| **Lost Work** | 1.0 | 1.0 |
| **Worker Replacements** | 1.0 | 0.0 |
| **Recovery Duration** | 0.0121 s | 0.0005 s |
| **Goodput** | 68.53 jobs/s | 84.18 jobs/s |
| **Wall-Clock Time** | 0.1167 s | 0.0950 s |

**Observed Empirical Findings**:
- Both policies achieved 100% recovery of the interrupted in-flight job.
- Policy R0 spawned a replacement worker (1 replacement), incurring subprocess creation overhead.
- Policy R1 did not spawn a replacement (0 replacements); the surviving worker processed the retried job and remaining workload. For small workloads, avoiding subprocess respawn overhead yielded lower wall-clock duration.

#### Comparison B: Retry Budget Impact on Retry Pressure (TB-E-001: R0 vs. R2)
Command: `python src/titan/cli.py experiment compare TB-E-001 --policies R0,R2`

| Metric | R0 (Baseline Recovery) | R2 (Limited Retry Budget) |
|:---|:---|:---|
| **Recovery Rate (%)** | 100.0% | 0.0% |
| **Completed Jobs** | 6.0 | 5.0 |
| **Failed Jobs** | 0.0 | 1.0 |
| **Total Attempts** | 7.0 | 6.0 |
| **Retries** | 1.0 | 0.0 |
| **Duplicate Work** | 1.0 | 1.0 |
| **Lost Work** | 1.0 | 1.0 |
| **Worker Replacements** | 1.0 | 1.0 |
| **Recovery Duration** | 0.0105 s | 0.0629 s |
| **Goodput** | 54.79 jobs/s | 38.21 jobs/s |
| **Wall-Clock Time** | 0.1095 s | 0.1309 s |

**Observed Empirical Findings**:
- Policy R0 granted retry budget (`max_retries=3`), successfully retrying the aborted attempt and achieving 100% recovery.
- Policy R2 enforced `max_retries=1`, exhausting retries immediately upon the single worker crash. The in-flight job permanently failed, yielding 0% recovery rate and reduced goodput.

---

### 7. CLI Usage

```bash
# List all registered recovery policies
python src/titan/cli.py experiment list-policies [--json]

# Run a specific scenario under a recovery policy
python src/titan/cli.py experiment run TB-B-001 R0 [--trials N] [--json]

# Compare multiple recovery policies side-by-side
python src/titan/cli.py experiment compare TB-B-001 --policies R0,R1 [--trials N] [--json]

# Run an experiment defined in a JSON config file
python src/titan/cli.py experiment run-config experiments/configs/exp-001.json
```

