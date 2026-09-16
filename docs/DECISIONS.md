# Architecture Decision Records (ADR)

This document records the architectural decisions made for the Titan project. Each record details the context, the decision taken, and the consequences.

---

## ADR-001: Minimal Repository Foundation and Runtime Selection

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Milestone 1 requires establishing a reproducible, minimal engineering foundation without introducing unnecessary technologies or dependencies. The host environment contains Python 3.10.11, Node.js v24, Java 22, Git, and pytest. Docker, Go, and Rust are not installed.
- **Decision**: 
  1. Select Python 3.10 as the primary language for Titan.
  2. Implement Milestone 1 using exclusively standard library modules (`argparse`, `dataclasses`, `os`, `sys`, `unittest`).
  3. Ensure compatibility with both standard `unittest` and `pytest` runners without requiring additional build tools.
- **Consequences**:
  - *Positive*: Zero installation overhead, instant onboarding, highly auditable code, portable across developer environments.
  - *Negative*: Performance is lower than compiled languages (C++/Rust/Go); compute-heavy synthetic jobs must account for Python interpreter characteristics.

---

## ADR-002: Rejection of Premature Infrastructure

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Common distributed systems projects frequently incorporate heavy third-party infrastructure (Kafka, Kubernetes, Redis, Docker, cloud services) before defining their primary research problems.
- **Decision**: 
  1. Explicitly ban Kafka, Kubernetes, Redis, Docker, and external message brokers from the initial architecture.
  2. Forbid cloud-only deployments and third-party database engines at this stage.
  3. Defer AI/ML models until baseline statistical/heuristic policies are established and empirical need is demonstrated.
- **Consequences**:
  - *Positive*: Keeps the codebase lean, understandable, directly debuggable, and tightly focused on the research question. Avoids operational complexity and hidden failure modes of third-party platforms.
  - *Negative*: We cannot rely on off-the-shelf distributed state management or orchestration; we must build only the minimal primitives strictly required by our experiments.

---

## ADR-003: Intentional Minimality of Initial Implementation

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: There is a common temptation in systems engineering to write speculative "placeholder" interfaces, mock distributed nodes, or stub schedulers before experimental requirements are formalized.
- **Decision**: 
  1. Milestone 1 includes strictly an application entry point (`titan.cli`), an immutable configuration dataclass (`titan.config`), and test verification.
  2. No distributed abstractions, workers, schedulers, or storage engines will be mocked or pre-coded.
- **Consequences**:
  - *Positive*: Eliminates phantom abstractions that would otherwise need refactoring once real workload requirements emerge. Ensures every added line of code serves an active purpose.
  - *Negative*: The repository contains only foundational plumbing at this stage and cannot yet execute distributed experiments.

---

## ADR-004: Strict Separation of Confirmed vs. Speculative Architecture

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Architectural documentation often drifts into aspirational descriptions of components that do not actually exist, misleading researchers and contributors.
- **Decision**: 
  1. Maintain explicit boundaries in `ARCHITECTURE.md` between Confirmed Architecture, Planned Architecture, and Unresolved Decisions.
  2. No component may be documented as confirmed until its code and tests are merged into the repository.
- **Consequences**:
  - *Positive*: High document integrity and trustworthiness. Readers know exactly what the system is currently capable of executing.
  - *Negative*: Requires continuous document updates as milestones are completed.

---

## ADR-005: Multi-Process Baseline Runtime Architecture

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Milestone 2 requires implementing the first minimal working distributed runtime for Titan to establish a static baseline. Workers could theoretically be implemented as threads, async coroutines, or separate OS processes.
- **Decision**:
  1. Implement workers as separate OS processes using Python's standard library `multiprocessing` with the `spawn` context.
  2. Use standard library `multiprocessing.Queue` for inter-process communication (`job_queue` and `result_queue`).
  3. Prohibit threading for worker execution to avoid Global Interpreter Lock (GIL) concurrency bottlenecks and to guarantee genuine memory isolation between workers.
- **Consequences**:
  - *Positive*: True CPU parallelism across multiple hardware cores; crash isolation between worker processes; no third-party daemons required.
  - *Negative*: IPC serialization overhead via pickle on queues; process creation overhead during initial startup.

---

## ADR-006: At-Most-Once Delivery and Absence of Premature Recovery in Milestone 2

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: In distributed systems, worker crash recovery, message acknowledgment, and redelivery mechanisms add considerable architectural complexity. Implementing complex recovery before establishing a clean static baseline risks coupling failure semantics with baseline measurements.
- **Decision**:
  1. Milestone 2 implements strict at-most-once delivery semantics.
  2. If a worker process terminates mid-execution, its active job is lost and not automatically recovered or redelivered.
  3. The coordinator remains resilient to worker termination: it does not crash, drains surviving worker results, and accounts for missing jobs as uncompleted/failed in the metrics report.
  4. Explicitly document this absence of automatic recovery as a known system limitation.
- **Consequences**:
  - *Positive*: The baseline remains simple, verifiable, and transparent. We avoid premature speculative recovery protocols.
  - *Negative*: The runtime is not yet fault-tolerant against crash-stop failures; fault tolerance remains a planned topic for Milestone 4.

---

## ADR-007: Continued Rejection of External Message Brokers (Kafka, Redis) and Databases

- **Status**: Accepted
- **Date**: 2026-09-16
- **Context**: Standard distributed systems implementations often adopt external brokers (e.g., Apache Kafka, RabbitMQ, Redis) for task distribution.
- **Decision**:
  1. Continue using standard library IPC (`multiprocessing.Queue`) exclusively.
  2. Continue banning Kafka, Redis, and external databases.
- **Consequences**:
  - *Positive*: Zero operational dependencies; experiments run locally in milliseconds with deterministic process control. We observe the execution policy rather than third-party broker queuing algorithms.
  - *Negative*: Task queues cannot scale across physically separate servers without networking extensions.
