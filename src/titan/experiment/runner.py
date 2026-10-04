"""Focused experiment runner for Titan recovery-policy evaluation.

Orchestrates the canonical experimental flow:
    TitanBench Scenario + Recovery Policy
                    ↓
                Titan Run
                    ↓
                  Trace
                    ↓
             Replay + Analysis
                    ↓
             Metric Extraction
                    ↓
             Experiment Result
                    ↓
             Policy Comparison
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

from titan.analysis import FailureAnalyzer
from titan.bench.corpus import BenchmarkScenario, CorpusRegistry
from titan.experiment.metrics import extract_experiment_metrics
from titan.experiment.policy import PolicyRegistry, RecoveryPolicy
from titan.experiment.trial import (
    ExperimentResult,
    ExperimentTrial,
    PolicyComparison,
)
from titan.replay import ReplayEngine
from titan.scenario import run_scenario


class ExperimentRunner:
    """Orchestrator for fair, reproducible recovery-policy experiments in Titan."""

    def __init__(self, output_base_dir: str | Path = "experiments/results") -> None:
        self.output_base_dir = Path(output_base_dir)

    def run_trial(
        self,
        benchmark_scenario: BenchmarkScenario,
        policy: RecoveryPolicy,
        repetition: int = 1,
        experiment_id: str | None = None,
        save_artifacts: bool = True,
        trial_dir: Path | None = None,
    ) -> ExperimentTrial:
        """Execute a single experimental trial combining a scenario and recovery policy.

        Ensures fair comparison by preserving identical non-policy variables
        (workload, job count, worker count, work units, patterns, seed, and fault injection).
        """
        exp_id = experiment_id or f"EXP_{benchmark_scenario.scenario_id}_{policy.policy_id}"
        benchmark_scenario.validate()
        policy.validate()

        effective_scenario = policy.apply_to_scenario(benchmark_scenario.scenario)
        start_time = time.perf_counter()

        execution_status = "COMPLETED"
        validation_errors: list[str] = []

        # 1. Execute workload
        try:
            scenario_res = run_scenario(effective_scenario)
            metrics = scenario_res.metrics
            trace = scenario_res.trace
        except Exception as exc:
            execution_duration = time.perf_counter() - start_time
            tb_str = traceback.format_exc()
            validation_errors.append(f"Execution error: {exc}\n{tb_str}")
            return ExperimentTrial(
                experiment_id=exp_id,
                scenario_id=benchmark_scenario.scenario_id,
                scenario_class=str(benchmark_scenario.scenario_class),
                policy_id=policy.policy_id,
                policy_config=policy.to_dict(),
                repetition=repetition,
                execution_status="CRASHED",
                replay_valid=False,
                analysis_status="CRASHED",
                metrics=extract_experiment_metrics(None, None, None, None),  # type: ignore
                artifacts={},
                validation_errors=validation_errors,
            )

        # 2. Replay trace
        if trace is None:
            validation_errors.append("Execution produced no trace artifact")
            replay_res = None
            analysis_rep = None
            replay_valid = False
            analysis_status = "NO_TRACE"
        else:
            replay_res = ReplayEngine.replay(trace)
            replay_valid = replay_res.valid
            if not replay_valid:
                validation_errors.extend(replay_res.validation_errors)

            # 3. Failure classification and root cause analysis
            analysis_rep = FailureAnalyzer.analyze(trace)
            analysis_status = analysis_rep.overall_status

        # 4. Extract metrics
        trial_metrics = extract_experiment_metrics(
            trace=trace,
            metrics=metrics,
            replay=replay_res,  # type: ignore
            analysis=analysis_rep,  # type: ignore
        )

        # 5. Persist trial artifacts if requested
        artifact_paths: dict[str, str] = {}
        if save_artifacts and trial_dir:
            try:
                trial_dir.mkdir(parents=True, exist_ok=True)
                trial_file = trial_dir / f"trial-{repetition:03d}.json"
                trace_file = trial_dir / f"trace-{repetition:03d}.json"

                with open(trace_file, "w", encoding="utf-8") as f:
                    json.dump(trace.to_list() if trace else [], f, indent=2)
                artifact_paths["trace"] = str(trace_file)

                trial_obj = ExperimentTrial(
                    experiment_id=exp_id,
                    scenario_id=benchmark_scenario.scenario_id,
                    scenario_class=(
                        benchmark_scenario.scenario_class.value
                        if hasattr(benchmark_scenario.scenario_class, "value")
                        else str(benchmark_scenario.scenario_class)
                    ),
                    policy_id=policy.policy_id,
                    policy_config=policy.to_dict(),
                    repetition=repetition,
                    execution_status=execution_status,
                    replay_valid=replay_valid,
                    analysis_status=analysis_status,
                    metrics=trial_metrics,
                    artifacts=artifact_paths,
                    validation_errors=validation_errors,
                )

                with open(trial_file, "w", encoding="utf-8") as f:
                    json.dump(trial_obj.to_dict(), f, indent=2)
                artifact_paths["trial"] = str(trial_file)

                return trial_obj
            except OSError as err:
                validation_errors.append(f"Trial artifact write error: {err}")

        return ExperimentTrial(
            experiment_id=exp_id,
            scenario_id=benchmark_scenario.scenario_id,
            scenario_class=(
                benchmark_scenario.scenario_class.value
                if hasattr(benchmark_scenario.scenario_class, "value")
                else str(benchmark_scenario.scenario_class)
            ),
            policy_id=policy.policy_id,
            policy_config=policy.to_dict(),
            repetition=repetition,
            execution_status=execution_status,
            replay_valid=replay_valid,
            analysis_status=analysis_status,
            metrics=trial_metrics,
            artifacts=artifact_paths,
            validation_errors=validation_errors,
        )

    def run_experiment(
        self,
        scenario_id: str,
        policy_id: str,
        repetitions: int = 1,
        experiment_id: str | None = None,
        output_dir: str | Path | None = None,
    ) -> ExperimentResult:
        """Execute repeated experimental trials for a (Scenario × Policy) configuration."""
        if repetitions < 1:
            raise ValueError(f"Repetitions must be at least 1, got {repetitions}")

        scenario = CorpusRegistry.get(scenario_id)
        policy = PolicyRegistry.get(policy_id)

        exp_id = experiment_id or f"EXP_{scenario_id}_{policy_id}"
        target_dir = Path(output_dir) if output_dir else self.output_base_dir / exp_id
        trials_dir = target_dir / "trials"

        trials: list[ExperimentTrial] = []
        for rep in range(1, repetitions + 1):
            trial = self.run_trial(
                benchmark_scenario=scenario,
                policy=policy,
                repetition=rep,
                experiment_id=exp_id,
                save_artifacts=True,
                trial_dir=trials_dir,
            )
            trials.append(trial)

        effective_scen = policy.apply_to_scenario(scenario.scenario)

        result = ExperimentResult.aggregate(
            experiment_id=exp_id,
            scenario_id=scenario_id,
            scenario_class=(
                scenario.scenario_class.value
                if hasattr(scenario.scenario_class, "value")
                else str(scenario.scenario_class)
            ),
            policy_id=policy_id,
            policy_config=policy.to_dict(),
            trials=trials,
            base_scenario_config=scenario.scenario.to_dict()["scenario"] if hasattr(scenario.scenario, "to_dict") else {},
            effective_scenario_config={
                "name": effective_scen.name,
                "workers": effective_scen.num_workers,
                "jobs": effective_scen.num_jobs,
                "work_units": effective_scen.work_units,
                "pattern": effective_scen.pattern,
                "seed": effective_scen.seed,
                "max_retries": effective_scen.max_retries,
                "replace_failed_workers": effective_scen.replace_failed_workers,
            },
        )

        # Write experiment.json and summary.json
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            experiment_meta = {
                "experiment_id": exp_id,
                "scenario_id": scenario_id,
                "scenario_class": result.scenario_class,
                "policy_id": policy_id,
                "policy_config": policy.to_dict(),
                "repetitions": repetitions,
                "base_scenario": scenario.to_dict(),
                "effective_scenario": result.effective_scenario_config,
            }
            with open(target_dir / "experiment.json", "w", encoding="utf-8") as f:
                json.dump(experiment_meta, f, indent=2)

            with open(target_dir / "summary.json", "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2)
        except OSError:
            pass

        return result

    def compare_policies(
        self,
        scenario_id: str,
        policy_ids: Sequence[str],
        repetitions: int = 1,
        output_dir: str | Path | None = None,
    ) -> PolicyComparison:
        """Compare multiple recovery policies on the same scenario with identical workload parameters."""
        if not policy_ids:
            raise ValueError("At least one policy ID must be specified for comparison")

        scenario = CorpusRegistry.get(scenario_id)
        results: dict[str, ExperimentResult] = {}

        comparison_base = (
            Path(output_dir)
            if output_dir
            else self.output_base_dir / "comparisons" / scenario_id
        )

        for pid in policy_ids:
            policy_exp_dir = comparison_base / pid
            exp_res = self.run_experiment(
                scenario_id=scenario_id,
                policy_id=pid,
                repetitions=repetitions,
                experiment_id=f"COMP_{scenario_id}_{pid}",
                output_dir=policy_exp_dir,
            )
            results[pid] = exp_res

        scen_class = (
            scenario.scenario_class.value
            if hasattr(scenario.scenario_class, "value")
            else str(scenario.scenario_class)
        )
        comparison = PolicyComparison.create(
            scenario_id=scenario_id,
            scenario_class=scen_class,
            results=results,
        )

        # Persist comparison.json
        try:
            comparison_base.mkdir(parents=True, exist_ok=True)
            comp_path = comparison_base / "comparison.json"
            with open(comp_path, "w", encoding="utf-8") as f:
                json.dump(comparison.to_dict(), f, indent=2)
        except OSError:
            pass

        return comparison

    def run_config(
        self,
        config_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> PolicyComparison | ExperimentResult:
        """Execute an experiment or policy comparison defined by a JSON configuration file."""
        cpath = Path(config_path)
        if not cpath.exists():
            raise FileNotFoundError(f"Experiment config file not found: {cpath}")

        with open(cpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        scenario_id = data.get("scenario_id")
        if not scenario_id:
            raise ValueError("Config missing required 'scenario_id'")

        repetitions = int(data.get("repetitions", 1))

        if "policies" in data:
            policies = [str(p) for p in data["policies"]]
            return self.compare_policies(
                scenario_id=scenario_id,
                policy_ids=policies,
                repetitions=repetitions,
                output_dir=output_dir,
            )
        elif "policy_id" in data:
            policy_id = str(data["policy_id"])
            return self.run_experiment(
                scenario_id=scenario_id,
                policy_id=policy_id,
                repetitions=repetitions,
                output_dir=output_dir,
            )
        else:
            raise ValueError("Config must specify either 'policy_id' or 'policies'")
