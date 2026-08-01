from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class DynamicsConfig:
    """Controls one deterministic, offline differentiation simulation."""

    agent_count: int
    cycles: int = 20
    seed: int = 0
    step_size: float = 0.15
    task_strength: float = 1.0
    attraction: float = 0.15
    inhibition: float = 0.6
    temperature: float = 0.2
    initial_noise: float = 0.03

    def __post_init__(self) -> None:
        if (
            isinstance(self.agent_count, bool)
            or not isinstance(self.agent_count, int)
            or self.agent_count < 1
        ):
            raise ValueError("agent_count must be a positive integer")
        if (
            isinstance(self.cycles, bool)
            or not isinstance(self.cycles, int)
            or self.cycles < 0
        ):
            raise ValueError("cycles must be a non-negative integer")
        numeric = (
            self.step_size,
            self.task_strength,
            self.attraction,
            self.inhibition,
            self.temperature,
            self.initial_noise,
        )
        if not all(np.isfinite(value) for value in numeric):
            raise ValueError("dynamics parameters must be finite")
        if self.step_size <= 0:
            raise ValueError("step_size must be positive")
        if self.temperature <= 0:
            raise ValueError("temperature must be positive")
        if min(self.task_strength, self.attraction, self.inhibition, self.initial_noise) < 0:
            raise ValueError("force strengths and noise cannot be negative")


@dataclass(frozen=True)
class EvolutionResult:
    capabilities: FloatArray
    history: FloatArray
    mean_update: FloatArray


def _normalize_rows(values: FloatArray) -> FloatArray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-12)


def _validate_demand(demand: FloatArray) -> FloatArray:
    values = np.asarray(demand, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("demand must be a non-empty one-dimensional vector")
    if not np.isfinite(values).all() or (values < 0).any() or np.linalg.norm(values) == 0:
        raise ValueError("demand must contain finite, non-negative, non-zero values")
    return values / np.linalg.norm(values)


def evolve(demand: FloatArray, config: DynamicsConfig) -> EvolutionResult:
    """Evolve capability vectors without invoking an LLM or external service.

    The task field attracts every agent toward demanded dimensions. Mean-field
    attraction keeps the population coherent, while pairwise inhibition pushes
    highly similar agents apart. Row normalization makes vector magnitude an
    explicit invariant rather than an accidental source of instability.
    """

    task = _validate_demand(demand)
    rng = np.random.default_rng(config.seed)
    capabilities = np.tile(task, (config.agent_count, 1))
    capabilities += rng.normal(0.0, config.initial_noise, capabilities.shape)
    capabilities = _normalize_rows(capabilities)

    snapshots = [capabilities.copy()]
    update_sizes: list[float] = []

    for _ in range(config.cycles):
        field = capabilities.mean(axis=0, keepdims=True)
        similarities = capabilities @ capabilities.T
        competition = np.exp((similarities - 1.0) / config.temperature)
        np.fill_diagonal(competition, 0.0)

        # Directional separation is bounded by normalization after every step.
        pairwise_delta = capabilities[:, None, :] - capabilities[None, :, :]
        repulsion = (competition[:, :, None] * pairwise_delta).sum(axis=1)
        if config.agent_count > 1:
            repulsion /= config.agent_count - 1

        task_force = config.task_strength * (task[None, :] - capabilities)
        field_force = config.attraction * (field - capabilities)
        delta = config.step_size * (
            task_force + field_force + config.inhibition * repulsion
        )
        next_capabilities = _normalize_rows(capabilities + delta)
        update_sizes.append(float(np.linalg.norm(next_capabilities - capabilities, axis=1).mean()))
        capabilities = next_capabilities
        snapshots.append(capabilities.copy())

    return EvolutionResult(
        capabilities=capabilities,
        history=np.stack(snapshots),
        mean_update=np.asarray(update_sizes, dtype=np.float64),
    )
