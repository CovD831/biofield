from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.model_probe import ProbeArm, build_a0_contrasts
from biofield.probe_assets import (
    A0_RESPONSE_SCHEMA_VERSION,
    ProbeAssetError,
    ProbeAssetResolver,
    history_length_units,
)


A0_FIXTURE = (
    Path(__file__).parents[1]
    / "src"
    / "biofield"
    / "fixtures"
    / "a0"
    / "assets.v1.json"
)
R1_FIXTURE_ROOT = (
    Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"
)


def _resolver(*, asset_path: Path = A0_FIXTURE) -> ProbeAssetResolver:
    return ProbeAssetResolver(
        asset_path=asset_path,
        r1_fixture_root=R1_FIXTURE_ROOT,
    )


def _contrast(contrast_id: str):
    return next(
        contrast
        for contrast in build_a0_contrasts(ProbeArm.reference())
        if contrast.contrast_id == contrast_id
    )


def test_reference_arm_resolves_to_a_provider_neutral_r1_request() -> None:
    request = _resolver().resolve(ProbeArm.reference())

    assert request.run_id == "a0.reference"
    assert request.task_asset_id == "software_release_readiness"
    assert request.task_id == "software_release_readiness"
    assert request.task_version == "1"
    assert request.agent_label == "agent.a"
    assert request.sample_id == 0
    assert request.system_prompt_id == "prompt.common.v1"
    assert "证据审查 Agent" in request.system_prompt
    assert request.input_id == "input.common.v1"
    assert request.history_id == "history.common.v1"
    assert request.role_induction == "history"
    assert len(request.materials) == 4
    assert request.history
    assert request.messages[-1].role == "user"
    assert request.messages[-1].content == request.user_prompt
    schema = json.loads(request.response_schema_json)
    assert schema["type"] == "object"
    assert request.response_schema_version == A0_RESPONSE_SCHEMA_VERSION
    assert "behavior_signature" in schema["required"]
    assert schema["properties"]["behavior_signature"]["required"] == [
        "requirement_id",
        "action_type",
    ]


def test_task_aliases_load_both_existing_r1_fixtures() -> None:
    resolver = _resolver()
    first = resolver.resolve(ProbeArm.reference())
    second = resolver.resolve(
        replace(
            ProbeArm.reference(),
            run_id="a0.second-task",
            task_id="cold_chain_readiness",
        )
    )

    assert first.task_id == "software_release_readiness"
    assert second.task_id == "cold_chain_readiness"
    assert first.task_version == second.task_version == "1"
    assert {material.material_id for material in first.materials} != {
        material.material_id for material in second.materials
    }


def test_input_variant_only_changes_presentation_and_material_order() -> None:
    contrast = _contrast("task_input")
    resolver = _resolver()

    control = resolver.resolve(contrast.control)
    treatment = resolver.resolve(contrast.treatment)

    assert control.task_id == treatment.task_id
    assert control.task_version == treatment.task_version
    assert control.task_prompt == treatment.task_prompt
    assert control.response_schema_json == treatment.response_schema_json
    assert control.system_prompt == treatment.system_prompt
    assert control.history == treatment.history
    assert {
        item.material_id: (item.title, item.text) for item in control.materials
    } == {
        item.material_id: (item.title, item.text) for item in treatment.materials
    }
    assert tuple(item.material_id for item in treatment.materials) == tuple(
        reversed([item.material_id for item in control.materials])
    )
    assert control.user_prompt != treatment.user_prompt


def test_sampling_variant_keeps_the_resolved_model_content_identical() -> None:
    contrast = _contrast("sampling_noise")
    resolver = _resolver()

    control = resolver.resolve(contrast.control)
    treatment = resolver.resolve(contrast.treatment)

    assert control.sample_id == 0
    assert treatment.sample_id == 1
    assert control.system_prompt == treatment.system_prompt
    assert control.history == treatment.history
    assert control.user_prompt == treatment.user_prompt
    assert control.response_schema_json == treatment.response_schema_json
    assert control.request_fingerprint == treatment.request_fingerprint


def test_agent_label_is_visible_in_the_resolved_model_request() -> None:
    contrast = _contrast("agent_label")
    resolver = _resolver()

    control = resolver.resolve(contrast.control)
    treatment = resolver.resolve(contrast.treatment)

    assert control.agent_label == "agent.a"
    assert treatment.agent_label == "agent.b"
    assert "agent.a" in control.system_prompt
    assert "agent.b" in treatment.system_prompt
    assert control.system_prompt != treatment.system_prompt


def test_common_and_specialized_histories_are_frozen_and_length_matched() -> None:
    contrast = _contrast("execution_history")
    resolver = _resolver()

    common = resolver.resolve(contrast.control)
    specialized = resolver.resolve(contrast.treatment)

    common_units = history_length_units(common.history)
    specialized_units = history_length_units(specialized.history)
    relative_difference = abs(common_units - specialized_units) / max(
        common_units,
        specialized_units,
    )

    assert common.history_id == "history.common.v1"
    assert specialized.history_id == "history.specialized.v1"
    assert common.history != specialized.history
    assert relative_difference <= 0.05
    assert common.task_id == specialized.task_id
    assert common.system_prompt == specialized.system_prompt
    assert common.user_prompt == specialized.user_prompt
    assert resolver.resolve(contrast.control) == common


def test_manual_prompt_and_history_induction_both_affect_the_request() -> None:
    contrast = _contrast("role_induction")
    resolver = _resolver()

    history_induced = resolver.resolve(contrast.control)
    manual = resolver.resolve(contrast.treatment)

    assert history_induced.role_induction == "history"
    assert history_induced.history_id == "history.specialized.v1"
    assert history_induced.history
    assert "延续对话历史" in history_induced.system_prompt
    assert manual.role_induction == "manual_prompt"
    assert manual.history_id == "history.common.v1"
    assert "固定角色要求" in manual.system_prompt
    assert manual.history != history_induced.history
    assert manual.system_prompt != history_induced.system_prompt
    assert manual.request_fingerprint != history_induced.request_fingerprint


def test_clear_history_produces_no_historical_messages() -> None:
    contrast = _contrast("history_clear")

    request = _resolver().resolve(contrast.treatment)

    assert request.history_id == "history.empty.v1"
    assert request.history == ()
    assert request.messages == (request.messages[-1],)
    assert request.messages[-1].role == "user"


def test_behavior_signature_prompt_defines_the_reported_decision_point() -> None:
    request = _resolver().resolve(ProbeArm.reference())

    assert "本轮形成答案时主要投入的需求维度" in request.user_prompt
    assert "主要执行的动作" in request.user_prompt
    assert "不是任务主题或固定身份" in request.user_prompt


def test_unknown_asset_id_is_rejected_without_fallback() -> None:
    arm = replace(
        ProbeArm.reference(),
        run_id="a0.unknown-input",
        input_id="input.missing.v1",
    )

    with pytest.raises(ProbeAssetError, match="unknown input asset"):
        _resolver().resolve(arm)


def test_catalog_rejects_histories_outside_the_five_percent_length_contract(
    tmp_path: Path,
) -> None:
    assets = json.loads(A0_FIXTURE.read_text(encoding="utf-8"))
    assets["histories"]["history.specialized.v1"][1]["content"] += "额外内容" * 30
    invalid_path = tmp_path / "invalid-assets.json"
    invalid_path.write_text(
        json.dumps(assets, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ProbeAssetError, match="within 5%"):
        _resolver(asset_path=invalid_path)


def test_neutral_history_matches_the_frozen_history_length_contract() -> None:
    resolver = _resolver()
    common = resolver.resolve(ProbeArm.reference()).history
    neutral = resolver.resolve(
        replace(
            ProbeArm.reference(),
            run_id="a0.neutral-history",
            history_id="history.neutral.v1",
        )
    ).history

    assert neutral
    assert "不预设某个需求维度" in neutral[-1].content
    difference = abs(history_length_units(common) - history_length_units(neutral))
    assert difference / max(
        history_length_units(common), history_length_units(neutral)
    ) <= 0.05


def _perfect_software_answer() -> dict[str, object]:
    return {
        "decision": "hold",
        "key_facts": [
            {
                "fact_id": "planned_release_date",
                "value": "2026-07-18",
                "citations": ["release_brief"],
            },
            {
                "fact_id": "auth_27_status",
                "value": "open",
                "citations": ["security_audit"],
            },
            {
                "fact_id": "refund_regression",
                "value": "failed",
                "citations": ["ci_log"],
            },
            {
                "fact_id": "dashboard_snapshot_date",
                "value": "2026-07-09",
                "citations": ["dashboard_export"],
            },
            {
                "fact_id": "readiness",
                "value": "hold",
                "citations": ["security_audit", "ci_log"],
            },
        ],
        "contradictions": [
            {
                "contradiction_id": "security_status_conflict",
                "material_ids": ["release_brief", "security_audit"],
            },
            {
                "contradiction_id": "critical_test_status_conflict",
                "material_ids": ["dashboard_export", "ci_log"],
            },
        ],
        "behavior_signature": {
            "requirement_id": "contradiction_resolution",
            "action_type": "cross_check",
        },
    }


def test_normalized_probe_response_uses_a0_signature_and_r1_score() -> None:
    resolver = _resolver()
    request = resolver.resolve(ProbeArm.reference())

    response = resolver.normalize_response(
        request,
        model_id="fake-model-v1",
        structured_output=_perfect_software_answer(),
        input_tokens=100,
        output_tokens=50,
    )

    assert response.requirement_id == "contradiction_resolution"
    assert response.action_type == "cross_check"
    assert response.evidence_score == 1.0
    assert response.critical_fact_score == 1.0
    assert response.citation_score == 1.0
    assert response.contradiction_score == 1.0
    assert response.decision_score == 1.0
    assert response.scoring_issues == ()
    assert json.loads(response.content)["decision"] == "hold"


def test_normalized_probe_response_rejects_missing_behavior_signature() -> None:
    resolver = _resolver()
    request = resolver.resolve(ProbeArm.reference())
    output = _perfect_software_answer()
    del output["behavior_signature"]

    with pytest.raises(ProbeAssetError, match="behavior_signature"):
        resolver.normalize_response(
            request,
            model_id="fake-model-v1",
            structured_output=output,
            input_tokens=None,
            output_tokens=None,
        )
