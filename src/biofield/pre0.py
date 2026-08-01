from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .baselines import (
    equal_assignment,
    fixed_role_assignment,
    greedy_cover_assignment,
    random_assignment,
)
from .artifacts import RunArtifactStore
from .dynamics import DynamicsConfig, evolve
from .metrics import evaluate_trajectory


@dataclass(frozen=True)
class Pre0Config:
    demand: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0)
    agent_count: int = 5
    cycles: int = 30
    seeds: tuple[int, ...] = tuple(range(10))
    step_size: float = 0.15
    attraction: float = 0.15
    inhibition: float = 0.8
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique")
        # DynamicsConfig owns the remaining numerical validation contract.
        DynamicsConfig(
            agent_count=self.agent_count,
            cycles=self.cycles,
            step_size=self.step_size,
            attraction=self.attraction,
            inhibition=self.inhibition,
            temperature=self.temperature,
        )


@dataclass(frozen=True)
class Pre0Result:
    strategy: str
    seed: int
    coverage: float
    redundancy: float
    coverage_gap: float
    final_update: float
    oscillation: float
    simulated_energy: float

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


def _static_history(assignment: np.ndarray) -> np.ndarray:
    return np.stack((assignment, assignment))


def run_pre0(config: Pre0Config) -> tuple[Pre0Result, ...]:
    """Run the C-pre0 mechanism against simple inspectable baselines."""

    demand = np.asarray(config.demand, dtype=np.float64)
    static_builders: tuple[tuple[str, Callable[[], np.ndarray]], ...] = (
        ("equal", lambda: equal_assignment(demand, config.agent_count)),
        ("fixed_role", lambda: fixed_role_assignment(demand, config.agent_count)),
        ("greedy_cover", lambda: greedy_cover_assignment(demand, config.agent_count)),
    )
    results: list[Pre0Result] = []

    for seed in config.seeds:
        trajectories: list[tuple[str, np.ndarray]] = [
            (name, _static_history(builder())) for name, builder in static_builders
        ]
        trajectories.append(
            (
                "random",
                _static_history(random_assignment(demand, config.agent_count, seed)),
            )
        )
        no_inhibition = evolve(
            demand,
            DynamicsConfig(
                agent_count=config.agent_count,
                cycles=config.cycles,
                seed=seed,
                step_size=config.step_size,
                attraction=config.attraction,
                inhibition=0.0,
                temperature=config.temperature,
            ),
        )
        trajectories.append(("no_inhibition", no_inhibition.history))
        field = evolve(
            demand,
            DynamicsConfig(
                agent_count=config.agent_count,
                cycles=config.cycles,
                seed=seed,
                step_size=config.step_size,
                attraction=config.attraction,
                inhibition=config.inhibition,
                temperature=config.temperature,
            ),
        )
        trajectories.append(("field", field.history))

        for strategy, history in trajectories:
            metrics = evaluate_trajectory(history, demand)
            results.append(
                Pre0Result(
                    strategy=strategy,
                    seed=seed,
                    coverage=metrics.coverage,
                    redundancy=metrics.redundancy,
                    coverage_gap=metrics.coverage_gap,
                    final_update=metrics.final_update,
                    oscillation=metrics.oscillation,
                    simulated_energy=metrics.simulated_energy,
                )
            )

    return tuple(results)


def aggregate_pre0(results: tuple[Pre0Result, ...]) -> dict[str, dict[str, float | int]]:
    if not results:
        raise ValueError("results cannot be empty")
    summary: dict[str, dict[str, float | int]] = {}
    metric_names = (
        "coverage",
        "redundancy",
        "coverage_gap",
        "final_update",
        "oscillation",
        "simulated_energy",
    )
    for strategy in sorted({result.strategy for result in results}):
        selected = [result for result in results if result.strategy == strategy]
        summary[strategy] = {
            "runs": len(selected),
            **{
                name: float(np.mean([getattr(result, name) for result in selected]))
                for name in metric_names
            },
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline C-pre0 pilot")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--run-id", default="paired-seeds-0-9")
    args = parser.parse_args()

    config = Pre0Config()
    results = run_pre0(config)
    summary = aggregate_pre0(results)
    store = RunArtifactStore.create(
        args.output_directory,
        "c-pre0-pilot-v1",
        args.run_id,
    )
    store.write_config({"experiment_id": "c-pre0-pilot-v1", **asdict(config)})
    for result in results:
        store.append_event({"event_type": "strategy_result", **result.to_dict()})
    store.write_metrics(
        {
            "evidence_level": "exploratory",
            "summary": summary,
            "raw_results": [result.to_dict() for result in results],
        }
    )
    store.write_summary(
        "# C-pre0 Pilot v1\n\n"
        "This is a vector-dynamics sanity check, not the final allocator. "
        "Simulated energy is vector movement and not a real resource unit.\n\n"
        f"```json\n{json.dumps(summary, indent=2, sort_keys=True)}\n```\n"
    )


if __name__ == "__main__":
    main()
