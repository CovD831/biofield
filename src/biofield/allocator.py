from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class AllocationPhase(str, Enum):
    COLD = "cold"
    WARMING = "warming"
    MATURE = "mature"
    RECOVERY = "recovery"


def _float_array(value: FloatArray, name: str) -> FloatArray:
    array = np.array(value, dtype=np.float64, copy=True)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite values")
    array.setflags(write=False)
    return array


def _int_array(value: IntArray, name: str) -> IntArray:
    raw = np.asarray(value)
    if not np.issubdtype(raw.dtype, np.integer):
        raise ValueError(f"{name} must contain integers")
    array = np.array(raw, dtype=np.int64, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class AllocationObservation:
    cycle: int
    residual: FloatArray
    quality_mean: FloatArray
    quality_sigma: FloatArray
    observation_count: IntArray
    previous_allocation: FloatArray
    cost: FloatArray
    risk: FloatArray
    capacity: FloatArray
    environment_changed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.cycle, bool) or not isinstance(self.cycle, int) or self.cycle < 0:
            raise ValueError("cycle must be a non-negative integer")
        if not isinstance(self.environment_changed, bool):
            raise ValueError("environment_changed must be a boolean")

        for name in (
            "residual",
            "quality_mean",
            "quality_sigma",
            "previous_allocation",
            "cost",
            "risk",
            "capacity",
        ):
            object.__setattr__(self, name, _float_array(getattr(self, name), name))
        object.__setattr__(
            self,
            "observation_count",
            _int_array(self.observation_count, "observation_count"),
        )

        if self.residual.ndim != 1 or self.residual.size == 0:
            raise ValueError("residual must be a non-empty vector")
        if self.capacity.ndim != 1 or self.capacity.size == 0:
            raise ValueError("capacity must be a non-empty vector")
        shape = (self.capacity.size, self.residual.size)
        for name in (
            "quality_mean",
            "quality_sigma",
            "observation_count",
            "previous_allocation",
            "cost",
            "risk",
        ):
            if getattr(self, name).shape != shape:
                raise ValueError(f"{name} must have shape {shape}")
        if (self.residual < 0).any():
            raise ValueError("residual cannot be negative")
        if (self.quality_mean < 0).any() or (self.quality_sigma < 0).any():
            raise ValueError("quality estimates cannot be negative")
        if (self.observation_count < 0).any():
            raise ValueError("observation_count cannot be negative")
        if (self.previous_allocation < 0).any():
            raise ValueError("previous_allocation cannot be negative")
        if (self.cost < 0).any() or (self.risk < 0).any():
            raise ValueError("cost and risk cannot be negative")
        if (self.capacity <= 0).any():
            raise ValueError("capacity must be positive")
        if not np.allclose(
            self.previous_allocation.sum(axis=1), self.capacity, atol=1e-8
        ):
            raise ValueError("previous_allocation rows must sum to capacity")


@dataclass(frozen=True)
class AllocationDecision:
    allocation: FloatArray
    phase: AllocationPhase

    def __post_init__(self) -> None:
        allocation = _float_array(self.allocation, "allocation")
        if allocation.ndim != 2 or (allocation < 0).any():
            raise ValueError("allocation must be a non-negative matrix")
        if not isinstance(self.phase, AllocationPhase):
            raise ValueError("phase must be an AllocationPhase")
        object.__setattr__(self, "allocation", allocation)


@dataclass(frozen=True)
class FieldConfig:
    n_min: int = 2
    kappa: float = 0.5
    demand_weight: float = 1.0
    uncertainty_weight: float = 0.25
    congestion_weight: float = 1.0
    cost_weight: float = 0.1
    risk_weight: float = 1.0
    learning_rate: float = 0.15
    target_coverage: float = 0.5
    congestion_temperature: float = 0.2
    exploration_initial: float = 0.30
    exploration_cycles: int = 20
    recovery_exploration: float = 0.50

    def __post_init__(self) -> None:
        if isinstance(self.n_min, bool) or not isinstance(self.n_min, int) or self.n_min < 1:
            raise ValueError("n_min must be a positive integer")
        if (
            isinstance(self.exploration_cycles, bool)
            or not isinstance(self.exploration_cycles, int)
            or self.exploration_cycles < 1
        ):
            raise ValueError("exploration_cycles must be a positive integer")
        nonnegative = (
            self.kappa,
            self.demand_weight,
            self.uncertainty_weight,
            self.congestion_weight,
            self.cost_weight,
            self.risk_weight,
            self.learning_rate,
            self.target_coverage,
        )
        if any(not np.isfinite(value) or value < 0 for value in nonnegative):
            raise ValueError("field weights must be finite and non-negative")
        if not np.isfinite(self.congestion_temperature) or self.congestion_temperature <= 0:
            raise ValueError("congestion_temperature must be positive")
        for name in ("exploration_initial", "recovery_exploration"):
            value = getattr(self, name)
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")


def reliable_quality(
    quality_mean: FloatArray,
    quality_sigma: FloatArray,
    observation_count: IntArray,
    *,
    n_min: int,
    kappa: float,
) -> tuple[FloatArray, NDArray[np.bool_]]:
    mean = np.asarray(quality_mean, dtype=np.float64)
    sigma = np.asarray(quality_sigma, dtype=np.float64)
    counts = np.asarray(observation_count)
    if mean.shape != sigma.shape or mean.shape != counts.shape or mean.ndim != 2:
        raise ValueError("quality arrays must be equally shaped matrices")
    if not np.isfinite(mean).all() or not np.isfinite(sigma).all():
        raise ValueError("quality arrays must contain finite values")
    if (mean < 0).any() or (sigma < 0).any() or (counts < 0).any():
        raise ValueError("quality arrays cannot contain negative values")
    if n_min < 1 or kappa < 0:
        raise ValueError("n_min must be positive and kappa non-negative")
    eligible = counts >= n_min
    reliable = np.where(eligible, np.maximum(0.0, mean - kappa * sigma), 0.0)
    return reliable.astype(np.float64), eligible.astype(np.bool_)


def _normalize_rows(scores: FloatArray, capacity: FloatArray) -> FloatArray:
    positive = np.maximum(np.asarray(scores, dtype=np.float64), 0.0)
    totals = positive.sum(axis=1, keepdims=True)
    fallback = np.ones_like(positive)
    normalized = np.divide(
        positive,
        totals,
        out=fallback / fallback.shape[1],
        where=totals > 1e-12,
    )
    return normalized * capacity[:, None]


class EqualAllocator:
    def allocate(self, observation: AllocationObservation) -> AllocationDecision:
        requirements = observation.residual.size
        allocation = np.tile(1.0 / requirements, (observation.capacity.size, requirements))
        allocation *= observation.capacity[:, None]
        return AllocationDecision(allocation, AllocationPhase.MATURE)


class UCBAllocator:
    def __init__(self, exploration_weight: float = 1.0) -> None:
        if not np.isfinite(exploration_weight) or exploration_weight < 0:
            raise ValueError("exploration_weight must be finite and non-negative")
        self._exploration_weight = exploration_weight

    def allocate(self, observation: AllocationObservation) -> AllocationDecision:
        scores = observation.residual[None, :] * (
            observation.quality_mean
            + self._exploration_weight * observation.quality_sigma
        )
        return AllocationDecision(
            _normalize_rows(scores, observation.capacity),
            AllocationPhase.MATURE,
        )


class FieldAllocator:
    def __init__(self, config: FieldConfig | None = None) -> None:
        self._config = config or FieldConfig()

    def _phase(self, observation: AllocationObservation) -> AllocationPhase:
        if observation.environment_changed:
            return AllocationPhase.RECOVERY
        if not observation.observation_count.any():
            return AllocationPhase.COLD
        if (observation.observation_count < self._config.n_min).any():
            return AllocationPhase.WARMING
        return AllocationPhase.MATURE

    def _cold_allocation(self, observation: AllocationObservation) -> FloatArray:
        agent_count = observation.capacity.size
        requirement_count = observation.residual.size
        # Stable sorting plus cycle rotation makes the symmetry-breaking seed
        # explicit and reproducible.
        order = np.argsort(-observation.residual, kind="stable")
        allocation = np.zeros((agent_count, requirement_count), dtype=np.float64)
        for agent in range(agent_count):
            position = (agent + observation.cycle) % requirement_count
            allocation[agent, order[position]] = observation.capacity[agent]
        return allocation

    def _warming_exploration(self, observation: AllocationObservation) -> FloatArray:
        """Give dominant attempts to the globally least-observed unknown pairs."""

        agent_count = observation.capacity.size
        requirement_count = observation.residual.size
        allocation = np.zeros((agent_count, requirement_count), dtype=np.float64)
        global_counts = observation.observation_count.sum(axis=0).astype(np.float64)
        claimed = np.zeros(requirement_count, dtype=np.float64)
        claim_penalty = float(self._config.n_min * agent_count + 1)

        for offset in range(agent_count):
            agent = (offset + observation.cycle) % agent_count
            unknown = observation.observation_count[agent] < self._config.n_min
            candidates = np.flatnonzero(unknown)
            if candidates.size == 0:
                candidates = np.arange(requirement_count)
            # Prefer low global coverage, then avoid duplicate attempts in this
            # cycle, then use residual as a stable tie breaker.
            scores = (
                global_counts[candidates]
                + claim_penalty * claimed[candidates]
                - 1e-6 * observation.residual[candidates]
            )
            requirement = int(candidates[int(np.argmin(scores))])
            allocation[agent, requirement] = observation.capacity[agent]
            claimed[requirement] += 1.0
        return allocation

    def _exploration_rate(
        self,
        observation: AllocationObservation,
        phase: AllocationPhase,
    ) -> float:
        if phase is AllocationPhase.RECOVERY:
            return max(self._config.exploration_initial, self._config.recovery_exploration)
        scheduled = self._config.exploration_initial * max(
            0.0,
            1.0 - observation.cycle / self._config.exploration_cycles,
        )
        if phase is AllocationPhase.WARMING:
            return max(scheduled, 0.6)
        return scheduled

    def allocate(self, observation: AllocationObservation) -> AllocationDecision:
        phase = self._phase(observation)
        if phase is AllocationPhase.COLD:
            return AllocationDecision(self._cold_allocation(observation), phase)

        reliable, _ = reliable_quality(
            observation.quality_mean,
            observation.quality_sigma,
            observation.observation_count,
            n_min=self._config.n_min,
            kappa=self._config.kappa,
        )
        weighted_reliable = observation.previous_allocation * reliable
        total_coverage = weighted_reliable.sum(axis=0)
        coverage_without_self = total_coverage[None, :] - weighted_reliable
        congestion_input = (
            coverage_without_self - self._config.target_coverage
        ) / self._config.congestion_temperature
        congestion = 1.0 / (1.0 + np.exp(-np.clip(congestion_input, -60.0, 60.0)))

        force = (
            self._config.demand_weight
            * observation.residual[None, :]
            * observation.quality_mean
            + self._config.uncertainty_weight * observation.quality_sigma
            - self._config.congestion_weight * congestion
            - self._config.cost_weight * observation.cost
            - self._config.risk_weight * observation.risk
        )
        previous = np.maximum(observation.previous_allocation, 1e-12)
        unnormalized = previous * np.exp(
            np.clip(self._config.learning_rate * force, -60.0, 60.0)
        )
        policy = _normalize_rows(unnormalized, observation.capacity)

        if phase is AllocationPhase.WARMING:
            exploration = self._warming_exploration(observation)
        else:
            uncertainty = observation.quality_sigma + 1.0 / np.sqrt(
                observation.observation_count + 1.0
            )
            exploration_scores = observation.residual[None, :] * uncertainty
            exploration = _normalize_rows(exploration_scores, observation.capacity)
        rate = self._exploration_rate(observation, phase)
        allocation = (1.0 - rate) * policy + rate * exploration
        allocation = _normalize_rows(allocation, observation.capacity)
        return AllocationDecision(allocation, phase)
