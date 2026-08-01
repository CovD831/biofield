from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

from biofield.a0_action_bias import (
    ActionBiasPairResult,
    build_action_bias_schedule,
    execute_action_bias_schedule,
    summarize_action_bias_results,
)
from biofield.a0_action_probe import ActionChoiceResult
from biofield.a0_runner import ModelInvocationAudit
from biofield.artifacts import RunArtifactStore
from biofield.ollama_adapter import StructuredInvocation
from biofield.probe_assets import ProbeAssetResolver


class SemanticFakeAdapter:
    def invoke_structured(
        self,
        *,
        system_prompt,
        messages,
        response_schema,
        effective_seed,
        request_fingerprint,
    ) -> StructuredInvocation:
        del system_prompt, response_schema
        history_text = "\n".join(message["content"] for message in messages[:-1])
        action = (
            "cross_check_conflicts" if "优先追查冲突" in history_text else "inspect_facts"
        )
        return StructuredInvocation(
            structured_output={"selected_action": action},
            input_tokens=10,
            output_tokens=2,
            audit=ModelInvocationAudit(
                request_fingerprint=request_fingerprint,
                provider_payload_hash="a" * 64,
                provider_response_hash="b" * 64,
                effective_seed=effective_seed,
                provider_model_id="fake-model",
                done_reason="stop",
                total_duration_ns=1,
                load_duration_ns=0,
                prompt_eval_duration_ns=0,
                eval_duration_ns=1,
            ),
        )


class MismatchedAuditAdapter(SemanticFakeAdapter):
    def invoke_structured(self, **kwargs) -> StructuredInvocation:
        invocation = super().invoke_structured(**kwargs)
        return StructuredInvocation(
            structured_output=invocation.structured_output,
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            audit=replace(
                invocation.audit,
                request_fingerprint="mismatched-request",
            ),
        )


def _schedule():
    return build_action_bias_schedule(repeats=5, base_seed=11100)


def _completed(action: str) -> ActionChoiceResult:
    return ActionChoiceResult(
        status="completed",
        selected_action=action,
        latency_ms=1.0,
        input_tokens=10,
        output_tokens=2,
    )


def _failed() -> ActionChoiceResult:
    return ActionChoiceResult(
        status="failed",
        selected_action=None,
        latency_ms=1.0,
        failure_type="RuntimeError",
        failure_message="planned failure",
    )


def _semantic_results():
    return tuple(
        ActionBiasPairResult(
            pair=pair,
            control=_completed("inspect_facts"),
            treatment=_completed("cross_check_conflicts"),
        )
        for pair in _schedule()
    )


def test_bias_schedule_is_a_five_seed_repeated_measure_design() -> None:
    schedule = _schedule()

    assert len(schedule) == 30
    assert len({pair.pair_id for pair in schedule}) == 30
    assert len(
        {
            arm.run_id
            for pair in schedule
            for arm in (pair.control, pair.treatment)
        }
    ) == 60
    assert Counter(pair.execution_order for pair in schedule) == {
        "control_first": 15,
        "treatment_first": 15,
    }
    assert len({pair.primary_seed for pair in schedule}) == 5
    assert set(Counter(pair.primary_seed for pair in schedule).values()) == {6}
    assert set(
        Counter(
            (pair.tie_break_enabled, pair.order_id) for pair in schedule
        ).values()
    ) == {5}
    assert all(pair.control_seed == pair.treatment_seed for pair in schedule)


def test_bias_schedule_counterbalances_arms_and_rotates_factorial_cell_order() -> None:
    schedule = _schedule()

    for order_id in {pair.order_id for pair in schedule}:
        assert Counter(
            pair.execution_order for pair in schedule if pair.order_id == order_id
        ) == {"control_first": 5, "treatment_first": 5}
    assert Counter(
        pair.execution_order for pair in schedule if pair.tie_break_enabled
    ) == {"control_first": 8, "treatment_first": 7}
    assert Counter(
        pair.execution_order for pair in schedule if not pair.tie_break_enabled
    ) == {"control_first": 7, "treatment_first": 8}
    cell_orders = []
    expected_cells = {
        (tie_break_enabled, order_id)
        for tie_break_enabled in (True, False)
        for order_id in {
            "inspect_first",
            "cross_check_first",
            "synthesize_first",
        }
    }
    for repeat_index in range(1, 6):
        cells = tuple(
            (pair.tie_break_enabled, pair.order_id)
            for pair in schedule
            if pair.repeat_index == repeat_index
        )
        assert set(cells) == expected_cells
        cell_orders.append(cells)
    assert len(set(cell_orders)) == 5
    for offset, cells in enumerate(cell_orders):
        assert cells == cell_orders[0][offset:] + cell_orders[0][:offset]


def test_bias_metrics_describe_non_default_seed_count_dynamically() -> None:
    schedule = build_action_bias_schedule(repeats=2, base_seed=11900)
    results = tuple(
        ActionBiasPairResult(
            pair=pair,
            control=_completed("inspect_facts"),
            treatment=_completed("cross_check_conflicts"),
        )
        for pair in schedule
    )

    metrics = summarize_action_bias_results(schedule, results)

    assert metrics["unique_primary_seeds"] == 2
    assert metrics["planned_pairs"] == 12
    assert metrics["design_interpretation"] == (
        "2_seed_blocks_repeated_across_six_cells"
    )


def test_semantic_control_extreme_is_position_balanced() -> None:
    schedule = _schedule()
    metrics = summarize_action_bias_results(schedule, _semantic_results())

    assert metrics["planned_pairs"] == 30
    assert metrics["planned_calls"] == 60
    assert metrics["completed_calls"] == 60
    assert metrics["target_transition_successes"] == 30
    assert metrics["semantic_target_successes"] == 60
    assert metrics["position_follow_successes"] == 20
    assert metrics["selected_position_counts"] == {
        "position_1": 20,
        "position_2": 20,
        "position_3": 20,
    }
    assert metrics["transition_counts"] == {
        "inspect_facts->cross_check_conflicts": 30
    }
    assert metrics["all_orders_target_success_by_tie"] == {
        "off": {
            "planned_seed_blocks": 5,
            "all_orders_target_success_blocks": 5,
        },
        "on": {
            "planned_seed_blocks": 5,
            "all_orders_target_success_blocks": 5,
        },
    }


def test_first_position_bias_extreme_does_not_pass_semantic_target() -> None:
    schedule = _schedule()
    results = tuple(
        ActionBiasPairResult(
            pair=pair,
            control=_completed(pair.action_order[0]),
            treatment=_completed(pair.action_order[0]),
        )
        for pair in schedule
    )

    metrics = summarize_action_bias_results(schedule, results)

    assert metrics["target_transition_successes"] == 0
    assert metrics["position_follow_successes"] == 60
    assert metrics["selected_position_counts"] == {"position_1": 60}
    assert all(
        group["all_orders_target_success_blocks"] == 0
        for group in metrics["all_orders_target_success_by_tie"].values()
    )


def test_wrong_direction_change_is_not_a_target_transition() -> None:
    schedule = _schedule()
    results = list(_semantic_results())
    results[0] = ActionBiasPairResult(
        pair=schedule[0],
        control=_completed("cross_check_conflicts"),
        treatment=_completed("inspect_facts"),
    )

    metrics = summarize_action_bias_results(schedule, results)

    assert metrics["changed_pairs"] == 30
    assert metrics["target_transition_successes"] == 29
    assert metrics["transition_counts"][
        "cross_check_conflicts->inspect_facts"
    ] == 1


def test_failure_stays_in_planned_denominators() -> None:
    schedule = _schedule()
    results = list(_semantic_results())
    results[0] = ActionBiasPairResult(
        pair=schedule[0],
        control=_failed(),
        treatment=_completed("cross_check_conflicts"),
    )

    metrics = summarize_action_bias_results(schedule, results)

    assert metrics["planned_pairs"] == 30
    assert metrics["planned_calls"] == 60
    assert metrics["completed_pairs"] == 29
    assert metrics["completed_calls"] == 59
    assert metrics["failed_calls"] == 1
    assert metrics["target_transition_successes"] == 29
    assert metrics["semantic_target_successes"] == 59


def test_bias_executor_records_factorial_and_request_metadata(tmp_path: Path) -> None:
    schedule = build_action_bias_schedule(repeats=1, base_seed=12100)
    store = RunArtifactStore.create(tmp_path, "a0a-action-bias", "fake-run")
    store.write_config({"evidence_level": "exploratory_technical"})

    results = execute_action_bias_schedule(
        schedule,
        resolver=ProbeAssetResolver(),
        adapter=SemanticFakeAdapter(),  # type: ignore[arg-type]
        store=store,
    )

    events = store.read_events()
    assert len(results) == 6
    assert len(events) == 12
    assert [event["call_index"] for event in events] == list(range(1, 13))
    assert {event["tie_break_enabled"] for event in events} == {True, False}
    assert {event["order_id"] for event in events} == {
        "inspect_first",
        "cross_check_first",
        "synthesize_first",
    }
    assert all(len(event["action_order"]) == 3 for event in events)
    assert all(len(event["request_fingerprint"]) == 64 for event in events)
    assert all(event["effective_seed"] == 12100 for event in events)
    assert all(event["status"] == "completed" for event in events)


def test_bias_executor_rejects_mismatched_provider_audit(tmp_path: Path) -> None:
    schedule = build_action_bias_schedule(repeats=1, base_seed=15100)
    store = RunArtifactStore.create(tmp_path, "a0a-action-bias", "bad-audit")

    results = execute_action_bias_schedule(
        schedule,
        resolver=ProbeAssetResolver(),
        adapter=MismatchedAuditAdapter(),  # type: ignore[arg-type]
        store=store,
    )

    assert all(
        result.control.status == "failed" and result.treatment.status == "failed"
        for result in results
    )
    events = store.read_events()
    assert len(events) == 12
    assert all(event["status"] == "failed" for event in events)
    assert all("fingerprint" in event["failure_message"] for event in events)
