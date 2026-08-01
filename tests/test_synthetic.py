from __future__ import annotations

import numpy as np

from biofield.synthetic import (
    C1_EXPERIMENT_ID,
    C1PilotConfig,
    SyntheticTask,
    SyntheticTaskConfig,
    c1_config_sha256,
    c1_reproducibility_config,
    c1_result_event,
    oracle_allocation,
    run_c1_pilot,
)


def _task_config(*, seed: int = 7, shift_cycle: int | None = None) -> SyntheticTaskConfig:
    return SyntheticTaskConfig(
        quality_initial=(
            (0.9, 0.2, 0.1),
            (0.1, 0.9, 0.2),
        ),
        residual_initial=(4.0, 4.0, 4.0),
        progress_scale=1.0,
        observation_noise=0.05,
        seed=seed,
        shift_cycle=shift_cycle,
        quality_after_shift=(
            (0.1, 0.2, 0.9),
            (0.9, 0.2, 0.1),
        )
        if shift_cycle is not None
        else None,
    )


def test_synthetic_task_is_deterministic_for_seeded_actions() -> None:
    allocation = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    first = SyntheticTask(_task_config(seed=11))
    second = SyntheticTask(_task_config(seed=11))

    first_step = first.step(allocation)
    second_step = second.step(allocation)

    np.testing.assert_allclose(first_step.true_progress, second_step.true_progress)
    np.testing.assert_allclose(
        first_step.observed_quality,
        second_step.observed_quality,
        equal_nan=True,
    )
    np.testing.assert_allclose(first.residual, second.residual)


def test_environment_shift_is_explicit_before_the_shift_cycle_action() -> None:
    task = SyntheticTask(_task_config(shift_cycle=1))
    allocation = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    before = task.step(allocation)
    after = task.step(allocation)

    assert before.environment_changed is False
    assert after.environment_changed is True
    assert before.true_progress[0] > after.true_progress[0]


def test_oracle_maximizes_immediate_progress_over_equal_allocation() -> None:
    quality = np.array([[0.9, 0.2, 0.1], [0.1, 0.9, 0.2]])
    residual = np.ones(3)
    capacity = np.ones(2)
    equal = np.full((2, 3), 1.0 / 3.0)

    oracle = oracle_allocation(quality, residual, capacity)

    oracle_gain = np.minimum(residual, (oracle * quality).sum(axis=0)).sum()
    equal_gain = np.minimum(residual, (equal * quality).sum(axis=0)).sum()
    assert oracle_gain >= equal_gain
    np.testing.assert_allclose(oracle.sum(axis=1), capacity)


def test_c1_pilot_runs_equal_ucb_field_and_oracle_for_paired_seeds() -> None:
    config = C1PilotConfig(
        cycles=8,
        seeds=(3, 5),
        shift_cycle=4,
        task_structures=("switch",),
    )

    first = run_c1_pilot(config)
    second = run_c1_pilot(config)

    assert first == second
    assert len(first) == 8
    assert {result.strategy for result in first} == {
        "equal",
        "ucb",
        "field",
        "oracle",
    }
    assert {result.seed for result in first} == {3, 5}
    assert {result.task_structure for result in first} == {"switch"}
    assert all(result.final_residual >= 0 for result in first)
    assert all(result.total_cost > 0 for result in first)


def test_c1_default_design_contains_all_three_protocol_task_structures() -> None:
    config = C1PilotConfig(cycles=4, seeds=(1,), shift_cycle=2)

    results = run_c1_pilot(config)

    assert {result.task_structure for result in results} == {
        "complementary",
        "homogeneous",
        "switch",
    }


def test_c1_reproducibility_config_records_controller_and_code_identity() -> None:
    config = c1_reproducibility_config(
        C1PilotConfig(cycles=4, seeds=(1,), shift_cycle=2)
    )

    assert config["experiment_id"] == C1_EXPERIMENT_ID
    assert config["fixture_version"] == "s1.v1"
    assert config["implementation_version"] == "2"
    assert config["ucb_config"] == {"exploration_weight": 1.0}
    assert config["field_config"]["n_min"] == 2
    assert config["action_spaces"] == {
        "equal": "continuous_requirement_share",
        "ucb": "continuous_requirement_share",
        "field": "continuous_requirement_share",
        "oracle": "privileged_discrete_one_step_reference",
    }
    assert set(config["code_sha256"]) == {"allocator.py", "synthetic.py"}
    assert all(
        len(digest) == 64 and set(digest) <= set("0123456789abcdef")
        for digest in config["code_sha256"].values()
    )


def test_c1_result_event_has_deterministic_versioned_envelope() -> None:
    result = run_c1_pilot(
        C1PilotConfig(
            cycles=2,
            seeds=(3,),
            shift_cycle=1,
            task_structures=("switch",),
        )
    )[0]

    config_sha256 = "a" * 64
    recorded_at = "2026-07-13T10:00:00+00:00"
    first = c1_result_event(
        result,
        logical_cycle=0,
        config_sha256=config_sha256,
        recorded_at=recorded_at,
    )
    second = c1_result_event(
        result,
        logical_cycle=0,
        config_sha256=config_sha256,
        recorded_at=recorded_at,
    )

    assert first == second
    assert first["event_type"] == "strategy_result"
    assert first["payload_version"] == "c1.strategy_result.v1"
    assert first["logical_cycle"] == 0
    assert first["recorded_at"] == recorded_at
    assert first["config_sha256"] == config_sha256
    assert first["causal_parent_ids"] == []
    assert first["payload"] == result.to_dict()
    assert len(first["event_id"]) == 64


def test_c1_config_hash_is_canonical_and_binds_event_identity() -> None:
    first_config = {"experiment_id": C1_EXPERIMENT_ID, "seeds": [0, 1]}
    reordered_config = {"seeds": [0, 1], "experiment_id": C1_EXPERIMENT_ID}
    changed_config = {"experiment_id": C1_EXPERIMENT_ID, "seeds": [0, 2]}

    first_hash = c1_config_sha256(first_config)
    assert first_hash == c1_config_sha256(reordered_config)
    assert first_hash != c1_config_sha256(changed_config)

    result = run_c1_pilot(
        C1PilotConfig(
            cycles=2,
            seeds=(3,),
            shift_cycle=1,
            task_structures=("switch",),
        )
    )[0]
    first_event = c1_result_event(
        result,
        logical_cycle=0,
        config_sha256=first_hash,
        recorded_at="2026-07-13T10:00:00+00:00",
    )
    changed_event = c1_result_event(
        result,
        logical_cycle=0,
        config_sha256=c1_config_sha256(changed_config),
        recorded_at="2026-07-13T10:00:00+00:00",
    )
    assert first_event["event_id"] != changed_event["event_id"]
