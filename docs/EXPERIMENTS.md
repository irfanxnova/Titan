# Titan Experiment Framework

This document outlines the standard protocol for conducting and documenting experiments in Titan.

All empirical evaluations comparing static and adaptive execution policies must be specified using the template below before execution.

---

## Experiment Specification Template

Each experiment must be documented using this exact structure:

```markdown
# Experiment: [Descriptive Title]

- **Experiment ID**: EXP-[###]
- **Date**: YYYY-MM-DD
- **Author**: [Name/Team]
- **Status**: [Planned | In Progress | Completed | Abandoned]

### 1. Hypothesis
State the precise, falsifiable claim being evaluated.

### 2. Baseline
Identify the baseline policy against which the candidate policy is compared.

### 3. Independent Variables
List the variables manipulated during the trials.

### 4. Dependent Variables (Metrics)
List the observable metrics measured:
- Latency distribution: p50, p95, p99 (milliseconds)
- Throughput: successful requests per second (req/s)
- Error rate: fraction of requests timed out or dropped (percentage)
- Policy adaptation time: duration from failure onset to stabilization (seconds)

### 5. Workload Profile
Specify the synthetic workload characteristics:
- Arrival distribution: [Poisson | Constant Rate | Bursty Step Function]
- Job service time distribution: [Deterministic | Exponential | Bimodal / Heavy-tailed]
- Work units / payload size
- Total job count

### 6. Failure Scenario
Describe the precise fault injected during the run:
- Fault type: [None | Process Crash-Stop | Latency Injection | Network Partition]
- Injection timing
- Targeted components

### 7. Measurement Method & Telemetry
Detail the instrumentation used to record observations:
- Monotonic timestamping mechanism (`time.perf_counter()`)
- Telemetry collection path (`result_queue` -> `RunMetrics`)

### 8. Expected Result
State the expected outcome predicted by the theoretical model or hypothesis prior to running the trial.

### 9. Actual Result
Document raw data and summary statistics from the completed run.
*(Must be left blank or marked "Pending execution" until the experiment is physically executed. Do not invent results.)*

### 10. Conclusion
Interpret the findings:
- Did the data support or reject the hypothesis?
- What are the observed trade-offs?
```

---

## Experiment Registry

| Experiment ID | Title | Baseline Policy | Candidate Policy / Variables | Status |
|:---|:---|:---|:---|:---|
| **EXP-001** | Static Baseline Worker Scaling (1, 2, 4, 8 workers) | Static 1-Worker Runtime | Static N-Workers (1, 2, 4, 8) | Planned |

---

## Specification: EXP-001

# Experiment EXP-001: Static Baseline Worker Scaling Under Uniform Workload

- **Experiment ID**: EXP-001
- **Date**: 2026-09-16
- **Status**: Planned (Baseline Specification Established in Milestone 2)

### 1. Hypothesis
Under a uniform batch workload of compute-bound jobs, increasing the static worker process count from 1 to 2, 4, and 8 will increase system throughput and reduce median latency proportionally to available CPU hardware cores, until core saturation or IPC queue lock contention dominates.

### 2. Baseline
Single worker process (`--workers 1`) static baseline runtime.

### 3. Independent Variables
- Number of worker OS processes: $N \in \{1, 2, 4, 8\}$.

### 4. Dependent Variables (Metrics)
- Wall-clock execution time (seconds)
- Throughput (completed jobs per second)
- Average latency (milliseconds)
- p50 latency (milliseconds)
- p95 latency (milliseconds)
- Average worker compute duration (milliseconds)

### 5. Workload Profile
- Total jobs: 1,000 jobs
- Computation units per job: 2,000 units
- Arrival distribution: Batch submission (all jobs queued at $t=0$)
- Job service time: Deterministic modular arithmetic

### 6. Failure Scenario
- None (pure static baseline concurrency scaling evaluation; failure injection is scheduled for Milestone 4).

### 7. Measurement Method & Telemetry
- Submissions timestamped with `time.perf_counter()` on the coordinator.
- Worker acquisition, completion, and processing durations recorded in each `JobResult`.
- Aggregated by `RunMetrics.calculate()`.

### 8. Expected Result
- Throughput will increase significantly moving from 1 to 2 and 4 workers on multi-core hardware.
- Scaling will taper as worker process count approaches the physical CPU core limit.
- Per-job tail latencies (p95) will decrease as concurrency drains the batch queue faster.

### 9. Actual Result
*Pending formal execution sweep. (Do not fabricate measurements.)*

### 10. Conclusion
*Pending trial completion.*
