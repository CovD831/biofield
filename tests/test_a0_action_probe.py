from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.a0_action_probe import (
    ACTION_CONTRAST_IDS,
    ActionChoiceResult,
    ActionPairResult,
    build_action_schedule,
    execute_action_schedule,
    resolve_action_request,
    summarize_action_results,
)
from biofield.a0_runner import ModelInvocationAudit
from biofield.artifacts import RunArtifactStore
from biofield.ollama_adapter import StructuredInvocation
from biofield.probe_assets import ProbeAssetResolver


class MismatchedAuditAdapter:
    def invoke_structured(
        self,
        *,
        system_prompt,
        messages,
        response_schema,
        effective_seed,
        request_fingerprint,
    ) -> StructuredInvocation:
        del system_prompt, messages, response_schema
        audit = ModelInvocationAudit(
            request_fingerprint=request_fingerprint,
            provider_payload_hash="e" * 64,
            provider_response_hash="f" * 64,
            effective_seed=effective_seed,
            provider_model_id="fake-model",
            done_reason="stop",
            total_duration_ns=1,
            load_duration_ns=0,
            prompt_eval_duration_ns=0,
            eval_duration_ns=1,
        )
        return StructuredInvocation(
            structured_output={"selected_action": "inspect_facts"},
            input_tokens=10,
            output_tokens=2,
            audit=replace(audit, effective_seed=effective_seed + 1),
        )


def _schedule():
    return build_action_schedule(
        task_ids=("software_release_readiness", "cold_chain_readiness"),
        agent_labels=("agent.a",),
        repeats=1,
        base_seed=8100,
    )


def test_action_schedule_is_unique_balanced_and_seed_blocked() -> None:
    schedule = _schedule()

    assert len(schedule) == 8
    assert {pair.contrast_id for pair in schedule} == set(ACTION_CONTRAST_IDS)
    assert len({pair.pair_id for pair in schedule}) == 8
    assert Counter(pair.execution_order for pair in schedule) == {
        "control_first": 4,
        "treatment_first": 4,
    }
    assert len(
        {
            arm.run_id
            for pair in schedule
            for arm in (pair.control, pair.treatment)
        }
    ) == 16
    for pair in schedule:
        if pair.contrast_id == "sampling_noise":
            assert pair.control_seed != pair.treatment_seed
        else:
            assert pair.control_seed == pair.treatment_seed


def test_sampling_pair_has_identical_content_fingerprint() -> None:
    resolver = ProbeAssetResolver()
    pair = next(item for item in _schedule() if item.contrast_id == "sampling_noise")

    control = resolve_action_request(pair.control, resolver)
    treatment = resolve_action_request(pair.treatment, resolver)

    assert control.request_fingerprint == treatment.request_fingerprint
    assert control.system_prompt == treatment.system_prompt
    assert control.messages == treatment.messages


def test_history_contrast_changes_history_but_not_system_or_task_prompt() -> None:
    resolver = ProbeAssetResolver()
    pair = next(
        item for item in _schedule() if item.contrast_id == "execution_history"
    )

    fact = resolve_action_request(pair.control, resolver)
    conflict = resolve_action_request(pair.treatment, resolver)

    assert pair.control.history_id == "history.common.v1"
    assert pair.treatment.history_id == "history.specialized.v1"
    assert fact.system_prompt == conflict.system_prompt
    assert fact.messages[-1] == conflict.messages[-1]
    assert fact.messages[:-1] != conflict.messages[:-1]


def test_manual_role_uses_neutral_history_and_changes_only_system_instruction() -> None:
    resolver = ProbeAssetResolver()
    pair = next(item for item in _schedule() if item.contrast_id == "manual_role")

    neutral = resolve_action_request(pair.control, resolver)
    manual = resolve_action_request(pair.treatment, resolver)

    assert pair.control.history_id == "history.neutral.v1"
    assert pair.treatment.history_id == "history.neutral.v1"
    assert neutral.messages == manual.messages
    assert neutral.system_prompt != manual.system_prompt
    assert "优先交叉核验相互矛盾" in manual.system_prompt


def test_role_channel_places_the_same_conflict_tendency_in_different_channels() -> None:
    resolver = ProbeAssetResolver()
    pair = next(item for item in _schedule() if item.contrast_id == "role_channel")

    history = resolve_action_request(pair.control, resolver)
    prompt = resolve_action_request(pair.treatment, resolver)

    assert pair.control.history_id == "history.specialized.v1"
    assert pair.treatment.history_id == "history.neutral.v1"
    assert "优先交叉核验相互矛盾" not in history.system_prompt
    assert "优先交叉核验相互矛盾" in prompt.system_prompt
    assert history.messages != prompt.messages
    assert history.response_schema == prompt.response_schema


def test_action_request_exposes_three_real_routing_choices() -> None:
    request = resolve_action_request(_schedule()[0].control, ProbeAssetResolver())
    action_enum = request.response_schema["properties"]["selected_action"]["enum"]

    assert action_enum == [
        "inspect_facts",
        "cross_check_conflicts",
        "synthesize_decision",
    ]
    assert "只能选择一个" in request.messages[-1]["content"]
    assert "剩余能量预算：1 个动作" in request.messages[-1]["content"]


def test_action_request_applies_the_same_cyclic_order_to_menu_and_schema() -> None:
    arm = _schedule()[0].control
    resolver = ProbeAssetResolver()
    default = resolve_action_request(arm, resolver)
    permuted = resolve_action_request(
        arm,
        resolver,
        action_order=(
            "cross_check_conflicts",
            "synthesize_decision",
            "inspect_facts",
        ),
    )

    assert permuted.response_schema["properties"]["selected_action"]["enum"] == [
        "cross_check_conflicts",
        "synthesize_decision",
        "inspect_facts",
    ]
    menu = permuted.messages[-1]["content"]
    assert menu.index("cross_check_conflicts") < menu.index("synthesize_decision")
    assert menu.index("synthesize_decision") < menu.index("inspect_facts")
    assert permuted.request_fingerprint != default.request_fingerprint


def test_action_request_can_disable_history_tie_break_without_other_role_change() -> None:
    arm = _schedule()[0].control
    resolver = ProbeAssetResolver()

    enabled = resolve_action_request(arm, resolver, use_tie_break=True)
    disabled = resolve_action_request(arm, resolver, use_tie_break=False)

    assert "沿用对话历史" in enabled.system_prompt
    assert "沿用对话历史" not in disabled.system_prompt
    assert enabled.messages == disabled.messages
    assert enabled.response_schema == disabled.response_schema
    assert enabled.request_fingerprint != disabled.request_fingerprint


def test_action_request_rejects_non_permutation_action_order() -> None:
    with pytest.raises(ValueError, match="action_order"):
        resolve_action_request(
            _schedule()[0].control,
            ProbeAssetResolver(),
            action_order=(
                "inspect_facts",
                "inspect_facts",
                "synthesize_decision",
            ),
        )


def test_action_request_can_decouple_menu_order_from_schema_order() -> None:
    arm = _schedule()[0].control
    request = resolve_action_request(
        arm,
        ProbeAssetResolver(),
        menu_order=(
            "synthesize_decision",
            "inspect_facts",
            "cross_check_conflicts",
        ),
        schema_order=(
            "inspect_facts",
            "cross_check_conflicts",
            "synthesize_decision",
        ),
        use_tie_break=False,
    )

    menu = request.messages[-1]["content"]
    assert menu.index("synthesize_decision") < menu.index("inspect_facts")
    assert menu.index("inspect_facts") < menu.index("cross_check_conflicts")
    assert request.response_schema["properties"]["selected_action"]["enum"] == [
        "inspect_facts",
        "cross_check_conflicts",
        "synthesize_decision",
    ]


def test_action_request_rejects_ambiguous_combined_and_axis_orders() -> None:
    with pytest.raises(ValueError, match="action_order"):
        resolve_action_request(
            _schedule()[0].control,
            ProbeAssetResolver(),
            action_order=(
                "cross_check_conflicts",
                "synthesize_decision",
                "inspect_facts",
            ),
            menu_order=(
                "synthesize_decision",
                "inspect_facts",
                "cross_check_conflicts",
            ),
        )


def test_action_summary_counts_observed_choice_changes_by_contrast() -> None:
    schedule = _schedule()
    results = tuple(
        ActionPairResult(
            pair=pair,
            control=ActionChoiceResult(
                status="completed",
                selected_action="inspect_facts",
                latency_ms=1.0,
                input_tokens=10,
                output_tokens=2,
            ),
            treatment=ActionChoiceResult(
                status="completed",
                selected_action=(
                    "cross_check_conflicts"
                    if pair.contrast_id in {"execution_history", "manual_role"}
                    else "inspect_facts"
                ),
                latency_ms=1.0,
                input_tokens=10,
                output_tokens=2,
            ),
        )
        for pair in schedule
    )

    metrics = summarize_action_results(schedule, results)

    assert metrics["planned_calls"] == 16
    assert metrics["completed_calls"] == 16
    assert metrics["failed_calls"] == 0
    assert metrics["by_contrast"]["execution_history"]["changed_pairs"] == 2
    assert metrics["by_contrast"]["execution_history"]["transition_counts"] == {
        "inspect_facts->cross_check_conflicts": 2
    }
    assert metrics["by_contrast"]["execution_history"][
        "target_transition_successes"
    ] == 2
    assert metrics["by_contrast"]["manual_role"]["changed_pairs"] == 2
    assert metrics["by_contrast"]["sampling_noise"]["changed_pairs"] == 0
    assert metrics["sampling_noise_band_p90"] == 0


def test_action_executor_rejects_mismatched_provider_audit(tmp_path: Path) -> None:
    schedule = _schedule()
    store = RunArtifactStore.create(tmp_path, "a0a-action-choice", "bad-audit")

    results = execute_action_schedule(
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
    assert len(events) == 16
    assert all(event["status"] == "failed" for event in events)
    assert all("effective seed" in event["failure_message"] for event in events)
