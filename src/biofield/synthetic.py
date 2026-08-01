from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .allocator import (
    AllocationObservation,
    EqualAllocator,
    FieldAllocator,
    FieldConfig,
    UCBAllocator,
)
from .artifacts import RunArtifactStore

FloatArray = NDArray[np.float64]

C1_EXPERIMENT_ID = "c1-pilot-v2"
C1_FIXTURE_VERSION = "s1.v1"
C1_IMPLEMENTATION_VERSION = "2"
C1_UCB_EXPLORATION_WEIGHT = 1.0


def _matrix(values: tuple[tuple[float, ...], ...], name: str) -> FloatArray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or not matrix.size:
        raise ValueError(f"{name} must be a non-empty matrix")
    if not np.isfinite(matrix).all() or (matrix < 0).any() or (matrix > 1).any():
        raise ValueError(f"{name} values must be finite and between zero and one")
    return matrix


@dataclass(frozen=True)
class SyntheticTaskConfig:
    quality_initial: tuple[tuple[float, ...], ...]
    residual_initial: tuple[float, ...]
    progress_scale: float = 0.08
    observation_noise: float = 0.05
    seed: int = 0
    shift_cycle: int | None = None
    quality_after_shift: tuple[tuple[float, ...], ...] | None = None

    def __post_init__(self) -> None:
        quality = _matrix(self.quality_initial, "quality_initial")
        residual = np.asarray(self.residual_initial, dtype=np.float64)
        if residual.ndim != 1 or residual.size != quality.shape[1]:
            raise ValueError("residual_initial must match the requirement count")
        if not np.isfinite(residual).all() or (residual <= 0).any():
            raise ValueError("residual_initial must contain finite positive values")
        if not np.isfinite(self.observation_noise) or self.observation_noise < 0:
            raise ValueError("observation_noise must be finite and non-negative")
        if not np.isfinite(self.progress_scale) or self.progress_scale <= 0:
            raise ValueError("progress_scale must be finite and positive")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if (self.shift_cycle is None) != (self.quality_after_shift is None):
            raise ValueError("shift_cycle and quality_after_shift must be set together")
        if self.shift_cycle is not None:
            if (
                isinstance(self.shift_cycle, bool)
                or not isinstance(self.shift_cycle, int)
                or self.shift_cycle < 1
            ):
                raise ValueError("shift_cycle must be a positive integer")
            after = _matrix(self.quality_after_shift or (), "quality_after_shift")
            if after.shape != quality.shape:
                raise ValueError("quality_after_shift must preserve task dimensions")


@dataclass(frozen=True)
class SyntheticStep:
    cycle: int
    environment_changed: bool
    true_progress: FloatArray
    observed_quality: FloatArray
    cost: float


class SyntheticTask:
    """Small deterministic environment with noisy capability observations."""

    def __init__(self, config: SyntheticTaskConfig) -> None:
        self._config = config
        self._quality_initial = _matrix(config.quality_initial, "quality_initial")
        self._quality_after = (
            _matrix(config.quality_after_shift, "quality_after_shift")
            if config.quality_after_shift is not None
            else None
        )
        self._residual = np.asarray(config.residual_initial, dtype=np.float64).copy()
        self._rng = np.random.default_rng(config.seed)
        self._cycle = 0

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def environment_changed(self) -> bool:
        return self._config.shift_cycle is not None and self._cycle == self._config.shift_cycle

    @property
    def current_quality(self) -> FloatArray:
        if (
            self._quality_after is not None
            and self._config.shift_cycle is not None
            and self._cycle >= self._config.shift_cycle
        ):
            return self._quality_after.copy()
        return self._quality_initial.copy()

    @property
    def residual(self) -> FloatArray:
        return self._residual.copy()

    def step(self, allocation: FloatArray) -> SyntheticStep:
        assigned = np.asarray(allocation, dtype=np.float64)
        quality = self.current_quality
        if assigned.shape != quality.shape:
            raise ValueError(f"allocation must have shape {quality.shape}")
        if not np.isfinite(assigned).all() or (assigned < 0).any():
            raise ValueError("allocation must contain finite non-negative values")
        if not np.allclose(assigned.sum(axis=1), np.ones(assigned.shape[0]), atol=1e-8):
            raise ValueError("each synthetic agent has unit capacity")

        potential = self._config.progress_scale * (assigned * quality).sum(axis=0)
        progress = np.minimum(self._residual, potential)
        self._residual = np.maximum(0.0, self._residual - progress)

        observed = np.full_like(quality, np.nan)
        selected = np.argmax(assigned, axis=1)
        for agent, requirement in enumerate(selected):
            noise = self._rng.normal(0.0, self._config.observation_noise)
            observed[agent, requirement] = np.clip(
                quality[agent, requirement] + noise,
                0.0,
                1.0,
            )

        result = SyntheticStep(
            cycle=self._cycle,
            environment_changed=self.environment_changed,
            true_progress=progress.copy(),
            observed_quality=observed,
            cost=float(assigned.sum()),
        )
        self._cycle += 1
        return result


def oracle_allocation(
    quality: FloatArray,
    residual: FloatArray,
    capacity: FloatArray,
    *,
    progress_scale: float = 1.0,
) -> FloatArray:
    """Brute-force the best immediate one-requirement assignment per agent."""

    quality_matrix = np.asarray(quality, dtype=np.float64)
    remaining = np.asarray(residual, dtype=np.float64)
    capacities = np.asarray(capacity, dtype=np.float64)
    if quality_matrix.ndim != 2:
        raise ValueError("quality must be a matrix")
    if remaining.shape != (quality_matrix.shape[1],):
        raise ValueError("residual must match quality requirements")
    if capacities.shape != (quality_matrix.shape[0],) or (capacities <= 0).any():
        raise ValueError("capacity must match agents and be positive")
    if not np.isfinite(progress_scale) or progress_scale <= 0:
        raise ValueError("progress_scale must be finite and positive")

    best_score = -np.inf
    best = np.zeros_like(quality_matrix)
    for choices in itertools.product(
        range(quality_matrix.shape[1]),
        repeat=quality_matrix.shape[0],
    ):
        candidate = np.zeros_like(quality_matrix)
        for agent, requirement in enumerate(choices):
            candidate[agent, requirement] = capacities[agent]
        progress = np.minimum(
            remaining,
            progress_scale * (candidate * quality_matrix).sum(axis=0),
        )
        score = float(progress.sum())
        if score > best_score:
            best_score = score
            best = candidate
    return best


@dataclass(frozen=True)
class C1PilotConfig:
    cycles: int = 30
    seeds: tuple[int, ...] = tuple(range(10))
    shift_cycle: int | None = 15
    observation_noise: float = 0.02
    task_structures: tuple[str, ...] = (
        "complementary",
        "homogeneous",
        "switch",
    )

    def __post_init__(self) -> None:
        if isinstance(self.cycles, bool) or not isinstance(self.cycles, int) or self.cycles < 1:
            raise ValueError("cycles must be a positive integer")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in self.seeds):
            raise ValueError("seeds must be non-negative integers")
        if self.shift_cycle is not None and not 1 <= self.shift_cycle < self.cycles:
            raise ValueError("shift_cycle must occur inside the pilot horizon")
        if not np.isfinite(self.observation_noise) or self.observation_noise < 0:
            raise ValueError("observation_noise must be finite and non-negative")
        allowed = {"complementary", "homogeneous", "switch"}
        if not self.task_structures or len(set(self.task_structures)) != len(
            self.task_structures
        ):
            raise ValueError("task_structures must be non-empty and unique")
        if any(structure not in allowed for structure in self.task_structures):
            raise ValueError("task_structures contain an unsupported fixture")
        if "switch" in self.task_structures and self.shift_cycle is None:
            raise ValueError("switch fixture requires shift_cycle")


@dataclass(frozen=True)
class C1PilotResult:
    strategy: str
    task_structure: str
    seed: int
    final_residual: float
    residual_auc: float
    total_progress: float
    total_cost: float
    cycles_run: int

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


def _default_task(
    config: C1PilotConfig,
    seed: int,
    task_structure: str,
) -> SyntheticTaskConfig:
    initial = (
        (0.85, 0.25, 0.25, 0.60),
        (0.25, 0.85, 0.25, 0.60),
        (0.25, 0.25, 0.85, 0.60),
    )
    shifted = (
        initial[2],
        initial[1],
        initial[0],
    )
    if task_structure == "homogeneous":
        rng = np.random.default_rng(seed)
        quality = tuple(
            tuple(float(value) for value in row)
            for row in np.clip(rng.normal(0.55, 0.02, size=(3, 4)), 0.52, 0.58)
        )
    else:
        quality = initial
    is_switch = task_structure == "switch"
    return SyntheticTaskConfig(
        quality_initial=quality,
        residual_initial=(1.0, 1.0, 1.0, 1.0),
        progress_scale=0.08,
        observation_noise=config.observation_noise,
        seed=seed,
        shift_cycle=config.shift_cycle if is_switch else None,
        quality_after_shift=shifted if is_switch else None,
    )


def _update_posterior(
    mean: FloatArray,
    counts: NDArray[np.int64],
    observed: FloatArray,
) -> None:
    for agent, requirement in zip(*np.where(np.isfinite(observed)), strict=True):
        counts[agent, requirement] += 1
        count = counts[agent, requirement]
        mean[agent, requirement] += (
            observed[agent, requirement] - mean[agent, requirement]
        ) / count


def _run_strategy(
    strategy: str,
    task_structure: str,
    task_config: SyntheticTaskConfig,
    cycles: int,
) -> C1PilotResult:
    task = SyntheticTask(task_config)
    quality_shape = np.asarray(task_config.quality_initial).shape
    agent_count, requirement_count = quality_shape
    capacity = np.ones(agent_count)
    previous = np.full(quality_shape, 1.0 / requirement_count)
    quality_mean = np.full(quality_shape, 0.5)
    quality_sigma = np.full(quality_shape, 0.5)
    counts = np.zeros(quality_shape, dtype=np.int64)
    initial_residual = float(task.residual.sum())
    residual_trace = [initial_residual]
    total_cost = 0.0

    controller = {
        "equal": EqualAllocator(),
        "ucb": UCBAllocator(C1_UCB_EXPLORATION_WEIGHT),
        "field": FieldAllocator(FieldConfig()),
    }.get(strategy)
    if strategy != "oracle" and controller is None:
        raise ValueError(f"unknown strategy: {strategy}")

    for cycle in range(cycles):
        if task.environment_changed:
            counts //= 2
            quality_sigma = np.maximum(quality_sigma, 0.35)
        if strategy == "oracle":
            allocation = oracle_allocation(
                task.current_quality,
                task.residual,
                capacity,
                progress_scale=task_config.progress_scale,
            )
        else:
            observation = AllocationObservation(
                cycle=cycle,
                residual=task.residual,
                quality_mean=quality_mean,
                quality_sigma=quality_sigma,
                observation_count=counts,
                previous_allocation=previous,
                cost=np.zeros(quality_shape),
                risk=np.zeros(quality_shape),
                capacity=capacity,
                environment_changed=task.environment_changed,
            )
            allocation = controller.allocate(observation).allocation

        step = task.step(allocation)
        total_cost += step.cost
        previous = np.array(allocation, copy=True)
        _update_posterior(quality_mean, counts, step.observed_quality)
        quality_sigma = 0.5 / np.sqrt(counts + 1.0)
        residual_trace.append(float(task.residual.sum()))
        if not task.residual.any():
            break

    final_residual = residual_trace[-1]
    return C1PilotResult(
        strategy=strategy,
        task_structure=task_structure,
        seed=task_config.seed,
        final_residual=final_residual,
        residual_auc=float(np.sum(residual_trace)),
        total_progress=initial_residual - final_residual,
        total_cost=total_cost,
        cycles_run=len(residual_trace) - 1,
    )


def run_c1_pilot(config: C1PilotConfig | None = None) -> tuple[C1PilotResult, ...]:
    pilot = config or C1PilotConfig()
    results: list[C1PilotResult] = []
    for seed in pilot.seeds:
        for task_structure in pilot.task_structures:
            task_config = _default_task(pilot, seed, task_structure)
            for strategy in ("equal", "ucb", "field", "oracle"):
                results.append(
                    _run_strategy(
                        strategy,
                        task_structure,
                        task_config,
                        pilot.cycles,
                    )
                )
    return tuple(results)


def _source_sha256(filename: str) -> str:
    path = Path(__file__).with_name(filename)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def c1_reproducibility_config(config: C1PilotConfig) -> dict[str, Any]:
    """Return every input needed to identify the canonical C1 implementation."""

    return {
        "experiment_id": C1_EXPERIMENT_ID,
        "fixture_version": C1_FIXTURE_VERSION,
        "implementation_version": C1_IMPLEMENTATION_VERSION,
        **asdict(config),
        "scope": "within_agent_requirement_routing_fixed_unit_capacity",
        "cross_agent_budget_share": False,
        "field_config": asdict(FieldConfig()),
        "ucb_config": {"exploration_weight": C1_UCB_EXPLORATION_WEIGHT},
        "action_spaces": {
            "equal": "continuous_requirement_share",
            "ucb": "continuous_requirement_share",
            "field": "continuous_requirement_share",
            "oracle": "privileged_discrete_one_step_reference",
        },
        "code_sha256": {
            "allocator.py": _source_sha256("allocator.py"),
            "synthetic.py": _source_sha256("synthetic.py"),
        },
    }


def c1_config_sha256(config: Mapping[str, Any]) -> str:
    """Hash a JSON configuration independently of mapping insertion order."""

    if not isinstance(config, Mapping) or not config:
        raise ValueError("config must be a non-empty mapping")
    try:
        canonical = json.dumps(
            dict(config),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("config must contain finite JSON values") from error
    return hashlib.sha256(canonical).hexdigest()


def c1_result_event(
    result: C1PilotResult,
    *,
    logical_cycle: int,
    config_sha256: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Wrap a result in the deterministic event envelope used by C1 v2."""

    if (
        isinstance(logical_cycle, bool)
        or not isinstance(logical_cycle, int)
        or logical_cycle < 0
    ):
        raise ValueError("logical_cycle must be a non-negative integer")
    if (
        not isinstance(config_sha256, str)
        or len(config_sha256) != 64
        or any(character not in "0123456789abcdef" for character in config_sha256)
    ):
        raise ValueError("config_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(recorded_at, str) or not recorded_at:
        raise ValueError("recorded_at must be a timezone-aware ISO timestamp")
    try:
        parsed_time = datetime.fromisoformat(recorded_at)
    except ValueError as error:
        raise ValueError("recorded_at must be a timezone-aware ISO timestamp") from error
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValueError("recorded_at must be a timezone-aware ISO timestamp")
    envelope: dict[str, Any] = {
        "event_type": "strategy_result",
        "logical_cycle": logical_cycle,
        "recorded_at": recorded_at,
        "config_sha256": config_sha256,
        "payload_version": "c1.strategy_result.v1",
        "causal_parent_ids": [],
        "payload": result.to_dict(),
    }
    canonical = json.dumps(
        envelope,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {"event_id": hashlib.sha256(canonical).hexdigest(), **envelope}


def aggregate_c1(
    results: tuple[C1PilotResult, ...],
) -> dict[str, dict[str, dict[str, float | int]]]:
    if not results:
        raise ValueError("results cannot be empty")
    metrics = (
        "final_residual",
        "residual_auc",
        "total_progress",
        "total_cost",
        "cycles_run",
    )
    summary: dict[str, dict[str, dict[str, float | int]]] = {}
    for structure in sorted({result.task_structure for result in results}):
        summary[structure] = {}
        for strategy in sorted({result.strategy for result in results}):
            selected = [
                result
                for result in results
                if result.task_structure == structure and result.strategy == strategy
            ]
            if not selected:
                continue
            summary[structure][strategy] = {
                "runs": len(selected),
                **{
                    metric: float(
                        np.mean([getattr(result, metric) for result in selected])
                    )
                    for metric in metrics
                },
            }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline C1 allocator pilot")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--run-id", default="paired-seeds-0-9")
    args = parser.parse_args()

    config = C1PilotConfig()
    results = run_c1_pilot(config)
    summary = aggregate_c1(results)
    started_at = datetime.now(timezone.utc).isoformat()
    base_config = {
        **c1_reproducibility_config(config),
        "run_id": args.run_id,
        "started_at": started_at,
    }
    config_sha256 = c1_config_sha256(base_config)
    store = RunArtifactStore.create(
        args.output_directory,
        C1_EXPERIMENT_ID,
        args.run_id,
    )
    store.write_config({**base_config, "config_sha256": config_sha256})
    for logical_cycle, result in enumerate(results):
        store.append_event(
            c1_result_event(
                result,
                logical_cycle=logical_cycle,
                config_sha256=config_sha256,
                recorded_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    store.write_metrics(
        {
            "evidence_level": "exploratory",
            "summary": summary,
            "raw_results": [result.to_dict() for result in results],
        }
    )
    store.write_summary(
        "# C1 Pilot v2\n\n"
        "This is an exploratory fixed-capacity requirement-routing comparison. "
        "It does not test cross-agent energy-budget shares. "
        "The oracle is a privileged one-step discrete reference and is not deployable.\n\n"
        f"```json\n{json.dumps(summary, indent=2, sort_keys=True)}\n```\n"
    )


if __name__ == "__main__":
    main()
