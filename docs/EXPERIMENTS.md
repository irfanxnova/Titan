# Titan Experiment Framework

This document outlines the standard protocol for conducting and documenting experiments in Titan.

All empirical evaluations comparing static and adaptive execution policies must be specified using the template below before execution.

---

## Experiment Specification Template

Each experiment must be documented in `/experiments/<experiment_id>.md` using this exact structure:

```markdown
# Experiment: [Descriptive Title]

- **Experiment ID**: EXP-[###]
- **Date**: YYYY-MM-DD
- **Author**: [Name/Team]
- **Status**: [Planned | In Progress | Completed | Abandoned]

### 1. Hypothesis
State the precise, falsifiable claim being evaluated.
Example: Under an unanticipated 50% loss of downstream worker capacity, an adaptive queue-length backpressure policy will maintain p99 latency below 200ms, whereas a static round-robin policy will experience unbounded queue growth and tail latency exceeding 2000ms.

### 2. Baseline
Identify the baseline policy against which the candidate policy is compared (e.g., static round-robin dispatch with fixed 500ms timeout).

### 3. Independent Variables
List the variables manipulated during the trials:
- Variable A: [e.g., Execution Policy: Static vs. Adaptive]
- Variable B: [e.g., Worker failure rate: 0%, 25%, 50%]
- Variable C: [e.g., Request arrival rate: 100 req/s to 1,000 req/s]

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
- Trial duration: [e.g., 180 seconds with 30s warm-up]

### 6. Failure Scenario
Describe the precise fault injected during the run:
- Fault type: [e.g., Process Crash-Stop | Latency Injection | Network Partition]
- Injection timing: [e.g., Injected at t=60s, resolved at t=120s]
- Targeted components: [e.g., Worker Node 2 and Node 3]

### 7. Measurement Method & Telemetry
Detail the instrumentation used to record observations:
- Clock synchronization and timestamping mechanism
- Telemetry collection path (in-memory circular buffer, log file)
- Sampling rate and aggregation window

### 8. Expected Result
State the expected outcome predicted by the theoretical model or hypothesis prior to running the trial.

### 9. Actual Result
Document raw data and summary statistics from the completed run.
*(Must be left blank or marked "Pending execution" until the experiment is physically executed. Do not invent results.)*

### 10. Conclusion
Interpret the findings:
- Did the data support or reject the hypothesis?
- What are the observed trade-offs?
- What follow-up experiment or policy refinement is indicated?
```

---

## Experiment Registry

| Experiment ID | Title | Baseline Policy | Candidate Policy | Status |
|:---|:---|:---|:---|:---|
| *(None)* | *(No experiments executed in Milestone 1)* | — | — | Planned |

> **Note**: No experiments have been conducted yet. Milestone 1 establishes only the repository foundation and source-of-truth documentation.
