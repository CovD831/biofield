from __future__ import annotations

import json

from biofield.pre0 import Pre0Config, aggregate_pre0, run_pre0


def test_pre0_runs_all_declared_strategies_for_each_seed() -> None:
    config = Pre0Config(
        demand=(1.0, 1.0, 1.0, 1.0),
        agent_count=3,
        cycles=8,
        seeds=(3, 7),
    )

    results = run_pre0(config)

    assert len(results) == 12
    assert {result.strategy for result in results} == {
        "equal",
        "fixed_role",
        "greedy_cover",
        "random",
        "no_inhibition",
        "field",
    }
    assert {result.seed for result in results} == {3, 7}
    assert all(0.0 <= result.coverage <= 1.0 for result in results)
    assert all(0.0 <= result.redundancy <= 1.0 for result in results)


def test_pre0_results_are_deterministic_and_json_serializable() -> None:
    config = Pre0Config(seeds=(11,), cycles=4)

    first = run_pre0(config)
    second = run_pre0(config)

    assert first == second
    json.dumps([result.to_dict() for result in first], sort_keys=True)


def test_pre0_aggregation_keeps_strategy_level_means() -> None:
    results = run_pre0(Pre0Config(seeds=(1, 2), cycles=4))

    summary = aggregate_pre0(results)

    assert set(summary) == {
        "equal",
        "fixed_role",
        "greedy_cover",
        "random",
        "no_inhibition",
        "field",
    }
    assert all(item["runs"] == 2 for item in summary.values())
