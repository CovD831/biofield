from __future__ import annotations

import numpy as np

from biofield.baselines import (
    equal_assignment,
    fixed_role_assignment,
    greedy_cover_assignment,
    random_assignment,
)
from biofield.metrics import evaluate_assignment, evaluate_trajectory


def test_equal_assignment_is_normalized_and_redundant() -> None:
    demand = np.ones(4)

    assignment = equal_assignment(demand, agent_count=3)
    metrics = evaluate_assignment(assignment, demand)

    np.testing.assert_allclose(np.linalg.norm(assignment, axis=1), np.ones(3))
    assert metrics.coverage == 1.0
    assert np.isclose(metrics.redundancy, 1.0)


def test_redundancy_is_clamped_to_its_declared_unit_interval() -> None:
    assignment = equal_assignment(np.ones(5), agent_count=5)

    metrics = evaluate_assignment(assignment, np.ones(5))

    assert 0.0 <= metrics.redundancy <= 1.0


def test_fixed_roles_and_greedy_cover_are_deterministic_and_cover_demand() -> None:
    demand = np.array([1.0, 0.9, 0.8, 0.7])

    fixed_first = fixed_role_assignment(demand, agent_count=3)
    fixed_second = fixed_role_assignment(demand, agent_count=3)
    greedy = greedy_cover_assignment(demand, agent_count=3)

    np.testing.assert_allclose(fixed_first, fixed_second)
    assert evaluate_assignment(fixed_first, demand).coverage == 1.0
    assert evaluate_assignment(greedy, demand).coverage == 1.0
    assert evaluate_assignment(fixed_first, demand).redundancy < 1.0


def test_random_assignment_is_seeded() -> None:
    demand = np.ones(5)

    first = random_assignment(demand, agent_count=4, seed=17)
    second = random_assignment(demand, agent_count=4, seed=17)
    different = random_assignment(demand, agent_count=4, seed=18)

    np.testing.assert_allclose(first, second)
    assert not np.allclose(first, different)


def test_trajectory_metrics_detect_reversals_and_energy() -> None:
    stable = np.array(
        [
            [[1.0, 0.0], [0.0, 1.0]],
            [[1.0, 0.0], [0.0, 1.0]],
            [[1.0, 0.0], [0.0, 1.0]],
        ]
    )
    oscillating = np.array(
        [
            [[1.0, 0.0], [0.0, 1.0]],
            [[0.8, 0.2], [0.2, 0.8]],
            [[1.0, 0.0], [0.0, 1.0]],
        ]
    )

    stable_metrics = evaluate_trajectory(stable, np.ones(2))
    oscillating_metrics = evaluate_trajectory(oscillating, np.ones(2))

    assert stable_metrics.simulated_energy == 0.0
    assert stable_metrics.oscillation == 0.0
    assert oscillating_metrics.simulated_energy > 0.0
    assert oscillating_metrics.oscillation > 0.9
