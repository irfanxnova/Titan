# Titan Architecture

This document serves as the architectural source of truth for Titan. It explicitly distinguishes between what is already implemented, what is planned, and what remains undecided.

---

## 1. Confirmed Architecture

As of Milestone 1, the confirmed architecture consists solely of the project's foundational harness:

```
+-------------------------------------------------------------+
|                        Titan CLI                            |
|                     (src/titan/cli.py)                      |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                    Configuration Layer                      |
|                   (src/titan/config.py)                     |
+-------------------------------------------------------------+
```

### 1.1 CLI Entry Point (`titan.cli`)
- Provides command-line access for interacting with the platform.
- Exposes version reporting and system status checks.
- Uses standard library `argparse` to eliminate external dependencies.

### 1.2 Configuration Module (`titan.config`)
- Encapsulates configuration values within an immutable dataclass (`TitanConfig`).
- Supports deterministic defaults with optional environment variable overrides (`TITAN_ENV`, `TITAN_LOG_LEVEL`).
- Enforces immutability (`frozen=True`) to prevent configuration drift during execution.

### 1.3 Verification & Test Harness (`tests/`)
- Tests executable via Python's standard library `unittest` runner as well as `pytest`.
- Validates CLI argument parsing, configuration invariants, and package import integrity.

---

## 2. Planned Architecture

The following components are planned to support the experimental evaluation of execution policies, but are **NOT YET IMPLEMENTED**:

```
+--------------------------------------------------------------------------+
|                       Experiment Orchestrator                            |
|  - Configures trial parameters, runs baselines, collects telemetry       |
+---------------------+------------------------------+---------------------+
                      |                              |
                      v                              v
      +-------------------------------+  +-------------------------------+
      |       Workload Generator      |  |       Failure Injector        |
      |   (Synthesizes job arrivals,  |  |    (Injects delays, drops,    |
      |    payload distributions)     |  |     crashes, and stalls)      |
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
        |  - Fixed round-robin        |     |  - Dynamic backpressure     |
        |  - Static timeout / retry   |     |  - Load-aware dispatch      |
        +-----------------------------+     +-----------------------------+
```

### 2.1 Workload Generator
- Will produce synthetic workloads with configurable request arrival rates (Poisson, uniform, bursty) and computational weights.

### 2.2 Execution Engine & Policies
- Will define a unified `ExecutionPolicy` interface to govern task scheduling, routing, and concurrency limits.
- Will allow side-by-side comparison between static policies (inflexible rules) and adaptive policies (feedback-driven adjustment).

### 2.3 Failure Injector
- Will deterministically introduce network partitions, latency spikes, and worker failures to observe policy robustness.

### 2.4 Metrics & Telemetry
- Will capture raw timing data to compute tail latencies (p50, p95, p99), throughput, and recovery times without skewing benchmark execution.

---

## 3. Unresolved Decisions

The following architectural questions remain intentionally open and will be decided based on experimental requirements:

1. **Process Boundary Model**:
   - *Option A*: Multi-process nodes running locally via standard OS processes and inter-process communication (IPC / loopback sockets).
   - *Option B*: Asynchronous in-process task simulation using `asyncio`.
   - *Consideration*: Multi-process offers realistic OS-level failure modes and memory isolation; in-process event simulation offers higher execution speed and determinism. A hybrid or staged approach will be evaluated in subsequent milestones.

2. **Inter-Node Communication Protocol**:
   - *Option A*: Raw TCP with length-prefixed framing.
   - *Option B*: Lightweight HTTP/1.1 or WebSocket communication.
   - *Consideration*: Protocol simplicity and overhead must not obscure policy performance differences.

3. **Telemetry Storage**:
   - *Option A*: Streaming JSON Lines (`.jsonl`) logs written directly to disk.
   - *Option B*: In-memory structured arrays dumped to CSV/Parquet at experiment completion.
   - *Consideration*: Disk I/O overhead must be isolated from the hot execution path during benchmark runs.
