from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

from biofield.a0_action_axis import (
    ActionAxisPairResult,
    build_action_axis_schedule,
    execute_action_axis_schedule,
    summarize_action_axis_results,
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
                provider_payload_hash="c" * 64,
                provider_response_hash="d" * 64,
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
                effective_seed=invocation.audit.effective_seed + 1,
            ),
        )


def _schedule():
    return build_action_axis_schedule(repeats=5, base_seed=11100)


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


def _results(control_choice):
    return tuple(
        ActionAxisPairResult(
            pair=pair,
            control=_completed(control_choice(pair)),
            treatment=_completed("cross_check_conflicts"),
        )
        for pair in _schedule()
    )


def test_axis_schedule_is_a_complete_four_cell_repeated_measure_design() -> None:
    schedule = _schedule()

    assert len(schedule) == 20
    assert len({pair.pair_id for pair in schedule}) == 20
    assert len(
        {
            arm.run_id
            for pair in schedule
            for arm in (pair.control, pair.treatment)
        }
    ) == 40
    assert len({pair.primary_seed for pair in schedule}) == 5
    assert set(Counter(pair.primary_seed for pair in schedule).values()) == {4}
    assert Counter(pair.cell_id for pair in schedule) == {
        "menu_canonical_schema_canonical": 5,
        "menu_synth_schema_canonical": 5,
        "menu_canonical_schema_synth": 5,
        "menu_synth_schema_synth": 5,
    }
    assert Counter(pair.execution_order for pair in schedule) == {
        "control_first": 10,
        "treatment_first": 10,
    }
    assert all(pair.control_seed == pair.treatment_seed for pair in schedule)
    for repeat_index in range(1, 6):
        cells = [
            pair.cell_id
            for pair in schedule
            if pair.repeat_index == repeat_index
        ]
        assert set(cells) == {
            "menu_canonical_schema_canonical",
            "menu_synth_schema_canonical",
            "menu_canonical_schema_synth",
            "menu_synth_schema_synth",
        }
        assert len(cells) == 4
    first_four_orders = [
        tuple(
            pair.cell_id
            for pair in schedule
            if pair.repeat_index == repeat_index
        )
        for repeat_index in range(1, 5)
    ]
    assert len({order for order in first_four_orders}) == 4


def test_menu_driven_extreme_is_distinguishable_from_schema_position() -> None:
    schedule = _schedule()
    metrics = summarize_action_axis_results(
        schedule,
        _results(lambda pair: pair.menu_order[0]),
    )

    assert metrics["target_transition_successes"] == 10
    assert metrics["semantic_target_successes"] == 30
    assert metrics["menu_first_follow_successes"] == 20
    assert metrics["schema_first_follow_successes"] == 10
    assert metrics["seed_pattern_counts"] == {"menu_dominant": 5}
    assert metrics["by_cell"]["menu_synth_schema_canonical"][
        "control_action_counts"
    ] == {"synthesize_decision": 5}
    assert metrics["by_cell"]["menu_canonical_schema_synth"][
        "control_action_counts"
    ] == {"inspect_facts": 5}


def test_schema_driven_extreme_is_distinguishable_from_menu_position() -> None:
    schedule = _schedule()
    metrics = summarize_action_axis_results(
        schedule,
        _results(lambda pair: pair.schema_order[0]),
    )

    assert metrics["target_transition_successes"] == 10
    assert metrics["semantic_target_successes"] == 30
    assert metrics["menu_first_follow_successes"] == 10
    assert metrics["schema_first_follow_successes"] == 20
    assert metrics["seed_pattern_counts"] == {"schema_dominant": 5}
    assert metrics["by_cell"]["menu_synth_schema_canonical"][
        "control_action_counts"
    ] == {"inspect_facts": 5}
    assert metrics["by_cell"]["menu_canonical_schema_synth"][
        "control_action_counts"
    ] == {"synthesize_decision": 5}


def test_semantic_extreme_passes_both_missing_cells() -> None:
    schedule = _schedule()
    metrics = summarize_action_axis_results(
        schedule,
        _results(lambda _: "inspect_facts"),
    )

    assert metrics["planned_pairs"] == 20
    assert metrics["planned_calls"] == 40
    assert metrics["completed_calls"] == 40
    assert metrics["target_transition_successes"] == 20
    assert metrics["semantic_target_successes"] == 40
    assert metrics["menu_first_follow_successes"] == 10
    assert metrics["schema_first_follow_successes"] == 10
    assert metrics["seed_pattern_counts"] == {"no_synthesis_bias": 5}


def test_axis_failure_remains_in_planned_denominators() -> None:
    schedule = _schedule()
    results = list(_results(lambda _: "inspect_facts"))
    results[0] = ActionAxisPairResult(
        pair=schedule[0],
        control=_failed(),
        treatment=_completed("cross_check_conflicts"),
    )

    metrics = summarize_action_axis_results(schedule, results)

    assert metrics["planned_pairs"] == 20
    assert metrics["planned_calls"] == 40
    assert metrics["completed_pairs"] == 19
    assert metrics["completed_calls"] == 39
    assert metrics["failed_calls"] == 1
    assert metrics["target_transition_successes"] == 19
    assert metrics["semantic_target_successes"] == 39


def test_axis_executor_records_both_order_axes(tmp_path: Path) -> None:
    schedule = build_action_axis_schedule(repeats=1, base_seed=13100)
    store = RunArtifactStore.create(tmp_path, "a0a-action-axis", "fake-run")
    store.write_config({"evidence_level": "exploratory_technical"})

    results = execute_action_axis_schedule(
        schedule,
        resolver=ProbeAssetResolver(),
        adapter=SemanticFakeAdapter(),  # type: ignore[arg-type]
        store=store,
    )

    events = store.read_events()
    assert len(results) == 4
    assert len(events) == 8
    assert [event["call_index"] for event in events] == list(range(1, 9))
    assert {event["cell_id"] for event in events} == {
        "menu_canonical_schema_canonical",
        "menu_synth_schema_canonical",
        "menu_canonical_schema_synth",
        "menu_synth_schema_synth",
    }
    assert all(len(event["menu_order"]) == 3 for event in events)
    assert all(len(event["schema_order"]) == 3 for event in events)
    assert all(event["tie_break_enabled"] is False for event in events)
    assert all(event["effective_seed"] == 13100 for event in events)
    assert all(len(event["request_fingerprint"]) == 64 for event in events)
    assert all(event["status"] == "completed" for event in events)


def test_axis_executor_rejects_mismatched_provider_audit(tmp_path: Path) -> None:
    schedule = build_action_axis_schedule(repeats=1, base_seed=14100)
    store = RunArtifactStore.create(tmp_path, "a0a-action-axis", "bad-audit")

    results = execute_action_axis_schedule(
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
    assert len(events) == 8
    assert all(event["status"] == "failed" for event in events)
    assert all(event["failure_type"] == "ValueError" for event in events)
    assert all("effective seed" in event["failure_message"] for event in events)
