from __future__ import annotations

import numpy as np

from biofield.allocator import (
    AllocationObservation,
    AllocationPhase,
    EqualAllocator,
    FieldAllocator,
    FieldConfig,
    UCBAllocator,
    reliable_quality,
)


def _observation(
    *,
    counts: np.ndarray,
    previous: np.ndarray | None = None,
    residual: np.ndarray | None = None,
    environment_changed: bool = False,
) -> AllocationObservation:
    agent_count, requirement_count = counts.shape
    return AllocationObservation(
        cycle=0,
        residual=np.ones(requirement_count) if residual is None else residual,
        quality_mean=np.full((agent_count, requirement_count), 0.6),
        quality_sigma=np.full((agent_count, requirement_count), 0.2),
        observation_count=counts,
        previous_allocation=(
            np.full((agent_count, requirement_count), 1.0 / requirement_count)
            if previous is None
            else previous
        ),
        cost=np.zeros((agent_count, requirement_count)),
        risk=np.zeros((agent_count, requirement_count)),
        capacity=np.ones(agent_count),
        environment_changed=environment_changed,
    )


def test_reliable_quality_excludes_pairs_below_the_observation_floor() -> None:
    mean = np.array([[0.8, 0.8]])
    sigma = np.array([[0.1, 0.1]])
    counts = np.array([[1, 2]])

    reliable, eligible = reliable_quality(
        mean,
        sigma,
        counts,
        n_min=2,
        kappa=0.5,
    )

    np.testing.assert_allclose(reliable, np.array([[0.0, 0.75]]))
    np.testing.assert_array_equal(eligible, np.array([[False, True]]))


def test_cold_start_balances_unknown_requirements_without_congestion() -> None:
    observation = _observation(counts=np.zeros((3, 4), dtype=int))

    decision = FieldAllocator(FieldConfig(n_min=2)).allocate(observation)

    assert decision.phase is AllocationPhase.COLD
    np.testing.assert_allclose(decision.allocation.sum(axis=1), np.ones(3))
    assert np.all(decision.allocation >= 0)
    assert len(set(np.argmax(decision.allocation, axis=1))) == 3


def test_warming_makes_an_unobserved_requirement_dominant_for_some_agent() -> None:
    counts = np.array(
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
        ]
    )
    previous = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ]
    )
    observation = _observation(counts=counts, previous=previous)

    decision = FieldAllocator(FieldConfig(n_min=2)).allocate(observation)

    assert decision.phase is AllocationPhase.WARMING
    assert 3 in set(np.argmax(decision.allocation, axis=1))


def test_mature_field_reduces_allocation_to_a_reliably_congested_dimension() -> None:
    previous = np.array(
        [
            [0.5, 0.5],
            [0.95, 0.05],
            [0.95, 0.05],
        ]
    )
    observation = _observation(
        counts=np.full((3, 2), 3),
        previous=previous,
    )
    allocator = FieldAllocator(
        FieldConfig(
            n_min=2,
            congestion_weight=3.0,
            exploration_initial=0.0,
            target_coverage=0.5,
            congestion_temperature=0.1,
        )
    )

    decision = allocator.allocate(observation)

    assert decision.phase is AllocationPhase.MATURE
    assert decision.allocation[0, 0] < decision.allocation[0, 1]
    np.testing.assert_allclose(decision.allocation.sum(axis=1), np.ones(3))


def test_recovery_reintroduces_exploration_after_environment_change() -> None:
    observation = _observation(
        counts=np.full((2, 3), 5),
        previous=np.array([[0.98, 0.01, 0.01], [0.98, 0.01, 0.01]]),
        environment_changed=True,
    )

    decision = FieldAllocator(FieldConfig()).allocate(observation)

    assert decision.phase is AllocationPhase.RECOVERY
    assert np.all(decision.allocation > 0)
    np.testing.assert_allclose(decision.allocation.sum(axis=1), np.ones(2))


def test_equal_and_ucb_controllers_obey_capacity() -> None:
    observation = _observation(
        counts=np.full((2, 3), 2),
        residual=np.array([1.0, 0.5, 0.25]),
    )

    equal = EqualAllocator().allocate(observation)
    ucb = UCBAllocator(exploration_weight=1.0).allocate(observation)

    np.testing.assert_allclose(equal.allocation.sum(axis=1), np.ones(2))
    np.testing.assert_allclose(ucb.allocation.sum(axis=1), np.ones(2))
    assert np.all(equal.allocation >= 0)
    assert np.all(ucb.allocation >= 0)
    assert np.all(ucb.allocation[:, 0] > ucb.allocation[:, 2])
