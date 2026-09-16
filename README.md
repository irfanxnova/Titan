# Titan

Titan is an experimental distributed-systems research platform designed to investigate adaptive execution strategies under dynamic workloads and fault conditions.

---

## Research Question

The core research question guiding this project is:

> **Can adaptive execution policies outperform static execution policies when workload characteristics and system failures change, while maintaining measurable reliability and performance?**

Titan aims to answer this question through empirical measurement, reproducible trial runs, and comparative analysis between static baseline policies and adaptive execution policies.

---

## Current Status (Milestone 1)

Titan is in its earliest stage of development. 

### What Currently Exists
- **Authoritative Documentation**:
  - [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md): Non-negotiable principles, research scope, and non-goals.
  - [ARCHITECTURE.md](docs/ARCHITECTURE.md): Strict separation between confirmed architecture, planned subsystems, and open decisions.
  - [DECISIONS.md](docs/DECISIONS.md): Architecture Decision Records (ADRs) detailing design trade-offs.
  - [EXPERIMENTS.md](docs/EXPERIMENTS.md): Formal protocol template for all empirical trials.
- **Foundational Skeleton**:
  - `src/titan/cli.py`: Minimal CLI entry point.
  - `src/titan/config.py`: Minimal immutable configuration dataclass.
  - `tests/test_skeleton.py`: Automated test suite verifying CLI behavior and configuration integrity.

### What Does NOT Exist Yet
To prevent premature complexity, the following components **have not been built**:
- No distributed worker nodes or cluster processes
- No message brokers or queueing middleware
- No schedulers or execution engines
- No databases or persistent storage layers
- No web dashboards or visual monitoring GUIs
- No third-party infrastructure dependencies (no Kafka, Redis, Kubernetes, or cloud services)
- No AI or machine learning models

---

## Evolution Roadmap

The project is structured to evolve in disciplined, verifiable milestones:

1. **Milestone 1 (Current)**: Foundation, documentation, and minimal verifiable skeleton.
2. **Milestone 2**: In-process execution model with static baseline policy (fixed routing/concurrency).
3. **Milestone 3**: Synthetic workload generation and metrics instrumentation (tail latency, throughput, error rates).
4. **Milestone 4**: Fault injection harness (latency spikes, node stalls, crash-stop failures).
5. **Milestone 5**: Adaptive execution policies and comparative experimental evaluations.

---

## Experiment Reproducibility

When experimental capabilities are added, all experiments will be:
- Defined via standardized specification files adhering to [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).
- Driven by deterministic configurations with explicit random seeds.
- Runnable locally with clear execution commands, producing raw telemetry for independent verification.

---

## Quickstart

### Prerequisites
- Python 3.10 or later
- Standard library modules (no external package installations required)

### Running the Skeleton
Invoke the CLI directly:
```powershell
python src/titan/cli.py status
```

Check the version:
```powershell
python src/titan/cli.py --version
```

Inspect status as JSON:
```powershell
python src/titan/cli.py status --json
```

### Running Tests
Execute tests using the standard library `unittest` runner:
```powershell
python -m unittest discover -s tests
```

Or using `pytest`:
```powershell
pytest tests/
```
