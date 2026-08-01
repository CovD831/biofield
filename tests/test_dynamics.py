from __future__ import annotations

import numpy as np

from biofield.dynamics import DynamicsConfig, evolve
from biofield.metrics import evaluate_assignment


def test_evolution_is_deterministic_for_a_fixed_seed() -> None:
    demand = np.array([1.0, 0.9, 0.8, 0.7])
    config = DynamicsConfig(agent_count=4, cycles=12, seed=7)

    first = evolve(demand, config)
    second = evolve(demand, config)

    np.testing.assert_allclose(first.capabilities, second.capabilities)
    np.testing.assert_allclose(first.history, second.history)


def test_evolution_keeps_capabilities_finite_and_normalized() -> None:
    result = evolve(
        np.ones(6),
        DynamicsConfig(agent_count=5, cycles=20, seed=11),
    )

    assert np.isfinite(result.capabilities).all()
    np.testing.assert_allclose(
        np.linalg.norm(result.capabilities, axis=1),
        np.ones(5),
        atol=1e-7,
    )


def test_lateral_inhibition_reduces_redundancy_without_losing_coverage() -> None:
    demand = np.ones(5)
    common = dict(agent_count=5, cycles=30, seed=3, attraction=0.15)

    without_inhibition = evolve(
        demand,
        DynamicsConfig(**common, inhibition=0.0),
    )
    with_inhibition = evolve(
        demand,
        DynamicsConfig(**common, inhibition=0.8),
    )

    collapsed = evaluate_assignment(without_inhibition.capabilities, demand)
    differentiated = evaluate_assignment(with_inhibition.capabilities, demand)

    assert differentiated.redundancy < collapsed.redundancy
    assert differentiated.coverage >= collapsed.coverage - 0.05


def test_zero_demand_is_rejected() -> None:
    with np.testing.assert_raises_regex(ValueError, "demand"):
        evolve(np.zeros(3), DynamicsConfig(agent_count=3))


def test_config_rejects_boolean_fractional_and_non_finite_values() -> None:
    invalid_configs = (
        {"agent_count": True},
        {"agent_count": 3, "cycles": 1.5},
        {"agent_count": 3, "step_size": float("nan")},
        {"agent_count": 3, "temperature": float("inf")},
        {"agent_count": 3, "inhibition": float("nan")},
    )

    for values in invalid_configs:
        with np.testing.assert_raises(ValueError):
            DynamicsConfig(**values)
