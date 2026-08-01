from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _validated_inputs(demand: FloatArray, agent_count: int) -> FloatArray:
    values = np.asarray(demand, dtype=np.float64)
    if agent_count < 1:
        raise ValueError("agent_count must be positive")
    if values.ndim != 1 or values.size == 0:
        raise ValueError("demand must be a non-empty one-dimensional vector")
    if not np.isfinite(values).all() or (values < 0).any() or not (values > 0).any():
        raise ValueError("demand must contain finite, non-negative, non-zero values")
    return values


def _normalize_rows(values: FloatArray) -> FloatArray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-12)


def equal_assignment(demand: FloatArray, agent_count: int) -> FloatArray:
    """Give every agent the same normalized demand vector."""

    values = _validated_inputs(demand, agent_count)
    normalized = values / np.linalg.norm(values)
    return np.tile(normalized, (agent_count, 1))


def fixed_role_assignment(demand: FloatArray, agent_count: int) -> FloatArray:
    """Assign demanded dimensions to stable round-robin roles."""

    values = _validated_inputs(demand, agent_count)
    demanded = np.flatnonzero(values > 0)
    order = demanded[np.argsort(-values[demanded], kind="stable")]
    assignment = np.zeros((agent_count, values.size), dtype=np.float64)
    for position, dimension in enumerate(order):
        assignment[position % agent_count, dimension] = values[dimension]

    # When agents outnumber demanded dimensions, give otherwise-empty agents a
    # duplicate of the strongest role. The overlap is explicit and measurable.
    strongest = int(order[0])
    empty = np.linalg.norm(assignment, axis=1) == 0
    assignment[empty, strongest] = values[strongest]
    return _normalize_rows(assignment)


def greedy_cover_assignment(demand: FloatArray, agent_count: int) -> FloatArray:
    """Greedily balance demanded dimensions by current assigned demand mass."""

    values = _validated_inputs(demand, agent_count)
    demanded = np.flatnonzero(values > 0)
    order = demanded[np.argsort(-values[demanded], kind="stable")]
    assignment = np.zeros((agent_count, values.size), dtype=np.float64)
    load = np.zeros(agent_count, dtype=np.float64)
    for dimension in order:
        agent = int(np.argmin(load))
        assignment[agent, dimension] = values[dimension]
        load[agent] += values[dimension]

    strongest = int(order[0])
    empty = np.linalg.norm(assignment, axis=1) == 0
    assignment[empty, strongest] = values[strongest]
    return _normalize_rows(assignment)


def random_assignment(demand: FloatArray, agent_count: int, seed: int) -> FloatArray:
    """Create a seeded positive random baseline limited to demanded dimensions."""

    values = _validated_inputs(demand, agent_count)
    rng = np.random.default_rng(seed)
    assignment = rng.gamma(shape=1.0, scale=1.0, size=(agent_count, values.size))
    assignment *= values[None, :]
    return _normalize_rows(assignment)

