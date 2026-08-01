from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class AssignmentMetrics:
    coverage: float
    redundancy: float


@dataclass(frozen=True)
class TrajectoryMetrics:
    coverage: float
    redundancy: float
    coverage_gap: float
    final_update: float
    oscillation: float
    simulated_energy: float


def evaluate_assignment(capabilities: FloatArray, demand: FloatArray) -> AssignmentMetrics:
    """Measure demanded-dimension coverage and positive cosine overlap."""

    vectors = np.asarray(capabilities, dtype=np.float64)
    required = np.asarray(demand, dtype=np.float64)
    if vectors.ndim != 2 or required.ndim != 1 or vectors.shape[1] != required.size:
        raise ValueError("capabilities and demand dimensions must match")
    demanded = required > 0
    if not demanded.any():
        raise ValueError("demand must contain at least one positive dimension")

    # A dimension is covered relative to the strength of the strongest demanded
    # dimension. This metric is intentionally simple and inspectable in phase 0.
    maxima = np.maximum(vectors, 0.0).max(axis=0)
    threshold = 0.6 / np.sqrt(int(demanded.sum()))
    coverage = float((maxima[demanded] >= threshold).mean())

    normalized = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    similarity = normalized @ normalized.T
    upper = similarity[np.triu_indices(vectors.shape[0], k=1)]
    redundancy = (
        float(np.clip(np.maximum(upper, 0.0).mean(), 0.0, 1.0))
        if upper.size
        else 0.0
    )
    return AssignmentMetrics(coverage=coverage, redundancy=redundancy)


def evaluate_trajectory(history: FloatArray, demand: FloatArray) -> TrajectoryMetrics:
    """Measure convergence and directional reversals in a C-pre0 trajectory.

    ``simulated_energy`` is only the summed vector movement used for relative
    comparison. It is not treated as a physical or fungible resource.
    """

    snapshots = np.asarray(history, dtype=np.float64)
    if snapshots.ndim != 3 or snapshots.shape[0] < 1:
        raise ValueError("history must have shape (cycles, agents, dimensions)")
    if not np.isfinite(snapshots).all():
        raise ValueError("history must contain only finite values")

    final = evaluate_assignment(snapshots[-1], demand)
    deltas = np.diff(snapshots, axis=0)
    if deltas.size == 0:
        return TrajectoryMetrics(
            coverage=final.coverage,
            redundancy=final.redundancy,
            coverage_gap=1.0 - final.coverage,
            final_update=0.0,
            oscillation=0.0,
            simulated_energy=0.0,
        )

    step_norms = np.linalg.norm(deltas, axis=2)
    simulated_energy = float(step_norms.sum())
    final_update = float(step_norms[-1].mean())

    oscillation_values: list[float] = []
    for previous, current in zip(deltas[:-1], deltas[1:], strict=True):
        numerator = np.sum(previous * current, axis=1)
        denominator = np.linalg.norm(previous, axis=1) * np.linalg.norm(current, axis=1)
        valid = denominator > 1e-12
        if valid.any():
            cosine = numerator[valid] / denominator[valid]
            oscillation_values.extend(np.maximum(-cosine, 0.0).tolist())

    oscillation = float(np.mean(oscillation_values)) if oscillation_values else 0.0
    return TrajectoryMetrics(
        coverage=final.coverage,
        redundancy=final.redundancy,
        coverage_gap=1.0 - final.coverage,
        final_update=final_update,
        oscillation=oscillation,
        simulated_energy=simulated_energy,
    )
