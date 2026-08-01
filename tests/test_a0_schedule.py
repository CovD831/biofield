from __future__ import annotations

from collections import Counter, defaultdict

from biofield.a0_schedule import CORE_CONTRAST_IDS, build_core_schedule


def test_technical_schedule_has_unique_pair_and_run_ids() -> None:
    schedule = build_core_schedule(
        task_ids=("software_release_readiness", "cold_chain_readiness"),
        agent_labels=("agent.a",),
        repeats=2,
        base_seed=4100,
    )

    assert len(schedule) == 16
    assert {item.contrast_id for item in schedule} == set(CORE_CONTRAST_IDS)
    assert len({item.pair_id for item in schedule}) == len(schedule)
    run_ids = [
        run_id
        for item in schedule
        for run_id in (item.contrast.control.run_id, item.contrast.treatment.run_id)
    ]
    assert len(set(run_ids)) == len(run_ids)
    assert Counter(item.execution_order for item in schedule) == {
        "control_first": 8,
        "treatment_first": 8,
    }


def test_full_core_schedule_balances_five_repeat_order_globally() -> None:
    schedule = build_core_schedule(
        task_ids=("software_release_readiness", "cold_chain_readiness"),
        agent_labels=("agent.a", "agent.b", "agent.c"),
        repeats=5,
        base_seed=4100,
    )

    assert len(schedule) == 120
    assert Counter(item.execution_order for item in schedule) == {
        "control_first": 60,
        "treatment_first": 60,
    }
    by_cell: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for item in schedule:
        by_cell[(item.task_id, item.agent_label, item.contrast_id)].append(
            item.execution_order
        )
    assert len(by_cell) == 24
    assert all(
        sorted(Counter(orders).values()) == [2, 3]
        for orders in by_cell.values()
    )


def test_seed_blocks_are_shared_across_conditions_but_not_repeats() -> None:
    schedule = build_core_schedule(
        task_ids=("software_release_readiness", "cold_chain_readiness"),
        agent_labels=("agent.a",),
        repeats=2,
        base_seed=7000,
    )

    by_block: dict[tuple[str, str, int], list[object]] = defaultdict(list)
    for item in schedule:
        by_block[(item.task_id, item.agent_label, item.repeat_index)].append(item)

    seed_sets: list[set[int]] = []
    for block in by_block.values():
        primary_seeds = {item.primary_seed for item in block}
        alternate_seeds = {item.alternate_seed for item in block}
        assert len(primary_seeds) == 1
        assert len(alternate_seeds) == 1
        seed_sets.append(primary_seeds | alternate_seeds)
        for item in block:
            if item.contrast_id == "sampling_noise":
                assert item.control_seed == item.primary_seed
                assert item.treatment_seed == item.alternate_seed
            else:
                assert item.control_seed == item.primary_seed
                assert item.treatment_seed == item.primary_seed
    for index, seed_set in enumerate(seed_sets):
        assert all(seed_set.isdisjoint(other) for other in seed_sets[index + 1 :])


def test_schedule_is_deterministic_for_the_same_frozen_inputs() -> None:
    kwargs = {
        "task_ids": ("software_release_readiness", "cold_chain_readiness"),
        "agent_labels": ("agent.a", "agent.b", "agent.c"),
        "repeats": 5,
        "base_seed": 4100,
    }

    assert build_core_schedule(**kwargs) == build_core_schedule(**kwargs)
