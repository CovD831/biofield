from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0 import Meas0Arm
from biofield.meas0_pilot_runner import (
    NATIVE_FAULT_IDS,
    PILOT_MUTATION_SEED,
    PilotRunnerError,
    RunValidity,
    aggregate_pilot_foundation,
    derive_native_arm_decision,
    load_pilot_mutation_manifest,
    materialize_pilot_cases,
    run_pilot_foundation,
    verify_pilot_case,
)
from biofield.measurement import (
    EvaluationStatus,
    seal_episode_graph,
    validate_sealed_episode,
)


def _by_key(results: tuple[object, ...]) -> dict[tuple[str, str, Meas0Arm], object]:
    return {
        (result.task_id, result.fault_id, result.arm): result  # type: ignore[attr-defined]
        for result in results
    }


def _native_decision_envelope(case: object, source: bytes) -> object:
    sealed_case_episode = case.sealed_episode  # type: ignore[attr-defined]
    if source == case.native_task_bytes:  # type: ignore[attr-defined]
        return sealed_case_episode
    graph = sealed_case_episode.episode_graph
    evidence = tuple(
        replace(
            item,
            content_hash=f"sha256:{hashlib.sha256(source).hexdigest()}",
        )
        if item.evidence_id == "artifact:native_task"
        else item
        for item in graph.evidence
    )
    return seal_episode_graph(
        task_measurement_bundle=case.task_measurement_bundle,  # type: ignore[attr-defined]
        episode_graph=replace(graph, evidence=evidence),
        provenance=sealed_case_episode.provenance,
    )


def _native_decision(
    case: object,
    payload: bytes | dict[str, object],
    arm: Meas0Arm,
) -> object:
    plan = case.native_measurement_plan  # type: ignore[attr-defined]
    assert plan is not None
    source = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload, sort_keys=True).encode()
    )
    return derive_native_arm_decision(
        source,
        arm,
        measurement_plan=plan,
        expected_case_id=case.case_id,  # type: ignore[attr-defined]
        sealed_case_episode=_native_decision_envelope(case, source),
    )


def test_frozen_pilot_manifest_covers_f01_f18_and_both_task_adapters() -> None:
    manifest = load_pilot_mutation_manifest()

    assert manifest.version == 8
    assert manifest.mutation_seed == PILOT_MUTATION_SEED == 1729
    assert tuple(item.fault_id for item in manifest.faults) == tuple(
        f"F{index:02d}" for index in range(1, 19)
    )
    assert {item.task_id for item in manifest.task_adapters} == {
        "cold_chain_readiness",
        "channel_order_ingest",
    }
    assert all(item.version == 1 for item in manifest.task_adapters)
    adapters = {item.task_id: item for item in manifest.task_adapters}
    assert adapters["cold_chain_readiness"].native_fault_ids == NATIVE_FAULT_IDS
    assert adapters["channel_order_ingest"].native_fault_ids == NATIVE_FAULT_IDS
    assert len({item.operator for item in manifest.faults}) == 18
    assert len(manifest.source_sha256) == 64

    historical = load_pilot_mutation_manifest(version="1")
    assert historical.version == 1
    assert all(not item.native_fault_ids for item in historical.task_adapters)
    previous = load_pilot_mutation_manifest(version="2")
    assert previous.version == 2
    assert len(previous.task_adapters[0].native_fault_ids) == 7
    prior = load_pilot_mutation_manifest(version="3")
    assert prior.version == 3
    assert len(prior.task_adapters[0].native_fault_ids) == 10
    previous_native = load_pilot_mutation_manifest(version="4")
    assert previous_native.version == 4
    assert all(
        len(adapter.native_fault_ids) == 16
        for adapter in previous_native.task_adapters
    )
    semantic_closure = load_pilot_mutation_manifest(version="5")
    assert semantic_closure.version == 5
    assert len(semantic_closure.task_adapters[0].native_fault_ids) == 15
    assert len(semantic_closure.task_adapters[1].native_fault_ids) == 16
    decision_closure = load_pilot_mutation_manifest(version="6")
    assert decision_closure.version == 6
    assert len(decision_closure.task_adapters[0].native_fault_ids) == 15
    assert len(decision_closure.task_adapters[1].native_fault_ids) == 16
    prior_foundation = load_pilot_mutation_manifest(version="7")
    assert prior_foundation.version == 7
    assert len(prior_foundation.task_adapters[0].native_fault_ids) == 15
    assert len(prior_foundation.task_adapters[1].native_fault_ids) == 16


def test_pilot_materialization_builds_36_real_sealed_cases() -> None:
    cases = materialize_pilot_cases()

    assert len(cases) == 36
    assert len({case.case_id for case in cases}) == 36
    assert {
        task_id: sum(case.task_id == task_id for case in cases)
        for task_id in {case.task_id for case in cases}
    } == {
        "cold_chain_readiness": 18,
        "channel_order_ingest": 18,
    }
    assert all(case.mutation_seed == PILOT_MUTATION_SEED for case in cases)
    assert len({case.sealed_episode.episode_hash for case in cases}) == 36
    assert len({case.observable_bytes for case in cases}) == 36

    for case in cases:
        validate_sealed_episode(
            case.sealed_episode,
            task_measurement_bundle=case.task_measurement_bundle,
        )
        verify_pilot_case(case)


def test_high_value_faults_use_task_native_evidence_without_labels() -> None:
    cases = materialize_pilot_cases()
    native = [case for case in cases if case.adapter_capability == "task_native"]
    generic = [
        case for case in cases if case.adapter_capability == "generic_foundation"
    ]

    assert len(native) == 36
    assert all(case.adapter_capability == "task_native" for case in native)
    assert all(case.native_task_bytes is not None for case in native)
    assert all(case.native_unavailable_reason is None for case in native)
    assert generic == []

    for case in native:
        payload = json.loads(case.native_task_bytes or b"{}")
        serialized = json.dumps(payload, sort_keys=True)
        assert "fault_id" not in payload
        assert "operator" not in payload
        assert "gold_status" not in payload
        assert "predicted_status" not in payload
        assert "measurement_plan" not in payload
        assert case.fault_id not in serialized
        assert case.native_measurement_plan is not None
        assert len(case.native_measurement_plan.plan_hash) == 64
        assert payload["task_id"] == case.task_id
        assert payload["native_episodes"]
        assert payload["deterministic_observations"]


def test_native_validity_attacks_carry_raw_graph_and_integrity_inputs() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    forbidden_shortcuts = {
        "requirements_complete",
        "schema_compatible",
        "protected_plane_unchanged",
        "hidden_gold_accessed",
    }
    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        omitted = json.loads(cases[(task_id, "F04")].native_task_bytes or b"{}")
        stale = json.loads(cases[(task_id, "F09")].native_task_bytes or b"{}")
        polluted = json.loads(cases[(task_id, "F17")].native_task_bytes or b"{}")
        assert set(omitted["formal_inputs"]) >= {
            "frozen_requirement_graph",
            "presented_requirement_graph",
            "presented_measurement_graph",
        }
        assert set(stale["formal_inputs"]) >= {
            "frozen_requirement_graph",
            "presented_requirement_graph",
            "presented_measurement_graph",
        }
        assert set(polluted["integrity_audit"]) >= {
            "protected_resource",
            "evaluator_source",
            "lock_snapshot",
            "access_events",
        }
        assert forbidden_shortcuts.isdisjoint(omitted)
        assert forbidden_shortcuts.isdisjoint(stale)
        assert forbidden_shortcuts.isdisjoint(polluted)


def test_remaining_deterministic_faults_carry_task_native_raw_audits() -> None:
    cases = {
        (case.task_id, case.fault_id): json.loads(case.native_task_bytes or b"{}")
        for case in materialize_pilot_cases()
    }
    forbidden_shortcuts = {
        "authorized",
        "proposal_pending",
        "proposal_self_approved",
        "checker_available",
        "reliability_runs",
        "invariance_holds",
        "source_attributed",
        "source_conflict",
    }

    def keys_recursively(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                key
                for nested in value.values()
                for key in keys_recursively(nested)
            }
        if isinstance(value, list):
            return {
                key
                for nested in value
                for key in keys_recursively(nested)
            }
        return set()

    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        unauthorized = cases[(task_id, "F02")]
        proposal = cases[(task_id, "F05")]
        unavailable = cases[(task_id, "F08")]
        reliability = cases[(task_id, "F10")]
        invariance = cases[(task_id, "F11")]
        attribution = cases[(task_id, "F13")]

        assert set(unauthorized["authorization_audit"]) >= {
            "policy",
            "filesystem_before",
            "filesystem_after",
        }
        assert set(proposal["requirement_proposal"]) >= {
            "proposal",
            "governance",
            "events",
        }
        assert set(unavailable["checker_audit"]) >= {
            "critical_measurement_id",
            "invocation",
        }
        assert len(reliability["reliability_trials"]) == 5
        assert all(
            set(trial) >= {"native_episode", "deterministic_observations"}
            for trial in reliability["reliability_trials"]
        )
        assert len(invariance["metamorphic_trials"]) == 3
        assert all(
            set(trial)
            >= {
                "baseline_input",
                "transformed_input",
                "id_bijection",
                "ignored_fields",
                "baseline_episode",
                "transformed_episode",
                "baseline_observations",
                "transformed_observations",
            }
            for trial in invariance["metamorphic_trials"]
        )
        assert set(attribution["causal_audit"]) >= {"actors", "events"}
        for payload in (
            unauthorized,
            proposal,
            unavailable,
            reliability,
            invariance,
            attribution,
        ):
            assert forbidden_shortcuts.isdisjoint(keys_recursively(payload))


def test_native_arm_fusion_does_not_accept_fault_or_gold_labels() -> None:
    cases = materialize_pilot_cases()
    native = tuple(
        case for case in cases if case.adapter_capability == "task_native"
    )
    results = {
        (item.case_id, item.arm): item
        for item in run_pilot_foundation(native)
    }

    for case in native:
        assert case.native_task_bytes is not None
        for arm in (
            Meas0Arm.STATE_ONLY,
            Meas0Arm.RULES_STATE,
            Meas0Arm.EVALUATION_PLANE,
        ):
            decision = _native_decision(case, case.native_task_bytes, arm)
            persisted = results[(case.case_id, arm)]
            assert decision.automatic_status is persisted.automatic_status
            assert decision.run_validity is persisted.run_validity

    payload = json.loads(native[0].native_task_bytes or b"{}")
    payload["fault_id"] = "F18"
    with pytest.raises(PilotRunnerError, match="forbidden label"):
        derive_native_arm_decision(
            json.dumps(payload, sort_keys=True).encode(),
            Meas0Arm.EVALUATION_PLANE,
            measurement_plan=native[0].native_measurement_plan,
            expected_case_id=native[0].case_id,
            sealed_case_episode=native[0].sealed_episode,
        )


def test_native_audits_derive_decisions_from_raw_records() -> None:
    materialized = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }

    def decide(
        task_id: str,
        fault_id: str,
        payload: dict[str, object],
        arm: Meas0Arm,
    ) -> EvaluationStatus | None:
        return _native_decision(
            materialized[(task_id, fault_id)],
            payload,
            arm,
        ).automatic_status

    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        unauthorized = json.loads(
            materialized[(task_id, "F02")].native_task_bytes or b"{}"
        )
        unauthorized["authorization_audit"]["filesystem_after"] = dict(  # type: ignore[index]
            unauthorized["authorization_audit"]["filesystem_before"]  # type: ignore[index]
        )
        assert (
            decide(task_id, "F02", unauthorized, Meas0Arm.RULES_STATE)
            is EvaluationStatus.PASS
        )

        proposal = json.loads(
            materialized[(task_id, "F05")].native_task_bytes or b"{}"
        )
        proposal["requirement_proposal"]["events"].append(  # type: ignore[index]
            {
                "event_id": f"{task_id}.proposal.owner-approved",
                "actor_id": "requirement-owner",
                "actor_roles": ["requirement_owner"],
                "action": "approve",
            }
        )
        assert (
            decide(task_id, "F05", proposal, Meas0Arm.STATE_ONLY)
            is EvaluationStatus.PASS
        )

        unavailable = json.loads(
            materialized[(task_id, "F08")].native_task_bytes or b"{}"
        )
        measurement_id = unavailable["checker_audit"]["critical_measurement_id"]  # type: ignore[index]
        unavailable["checker_audit"]["invocation"]["events"].append(  # type: ignore[index]
            {
                "sequence": 2,
                "kind": "result",
                "measurement_id": measurement_id,
                "status": "pass",
            }
        )
        assert (
            decide(
                task_id,
                "F08",
                unavailable,
                Meas0Arm.EVALUATION_PLANE,
            )
            is EvaluationStatus.PASS
        )

        attribution = json.loads(
            materialized[(task_id, "F13")].native_task_bytes or b"{}"
        )
        events = attribution["causal_audit"]["events"]  # type: ignore[index]
        artifact = next(item for item in events if item["kind"] == "artifact")
        artifact["claimed_parent_ids"] = list(artifact["actual_parent_ids"])
        action_actors = {
            item["event_id"]: item["actor_id"]
            for item in events
            if item["kind"] == "action"
        }
        artifact["attributed_actor_id"] = action_actors[
            artifact["actual_parent_ids"][0]
        ]
        assert (
            decide(
                task_id,
                "F13",
                attribution,
                Meas0Arm.EVALUATION_PLANE,
            )
            is EvaluationStatus.PASS
        )


def test_native_episode_closure_rejects_tampering_and_ignores_self_counts() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    source = json.loads(
        cases[("cold_chain_readiness", "F02")].native_task_bytes or b"{}"
    )
    artifact = source["native_episodes"][0]["artifacts"][0]
    artifact["content_base64"] = base64.b64encode(b"tampered").decode("ascii")
    with pytest.raises(PilotRunnerError, match="artifact"):
        _native_decision(
            cases[("cold_chain_readiness", "F02")],
            source,
            Meas0Arm.STATE_ONLY,
        )

    source = json.loads(
        cases[("cold_chain_readiness", "F02")].native_task_bytes or b"{}"
    )
    source["native_episodes"][0]["sealed_episode"]["episode_hash"] = "0" * 64
    with pytest.raises(PilotRunnerError, match="seal|episode"):
        _native_decision(
            cases[("cold_chain_readiness", "F02")],
            source,
            Meas0Arm.EVALUATION_PLANE,
        )

    source = json.loads(
        cases[("cold_chain_readiness", "F02")].native_task_bytes or b"{}"
    )
    source["deterministic_observations"][0]["status"] = "fail"
    decision = _native_decision(
        cases[("cold_chain_readiness", "F02")],
        source,
        Meas0Arm.STATE_ONLY,
    )
    assert decision.run_validity is RunValidity.INVALID
    assert decision.automatic_status is None

    reliability = json.loads(
        cases[("cold_chain_readiness", "F10")].native_task_bytes or b"{}"
    )
    assert len(reliability["native_episode_observations"]) == 5
    failing = next(
        observation
        for trial in reliability["native_episode_observations"]
        for observation in trial
        if observation["status"] == "fail"
    )
    failing["status"] = "pass"
    decision = _native_decision(
        cases[("cold_chain_readiness", "F10")],
        reliability,
        Meas0Arm.RULES_STATE,
    )
    assert decision.run_validity is RunValidity.INVALID
    assert decision.automatic_status is None

    recovered = json.loads(
        cases[("channel_order_ingest", "F18")].native_task_bytes or b"{}"
    )
    recovered["native_state"] = {
        "mutation_count": 999,
        "unique_mutation_count": 0,
    }
    recovered["retry"] = {
        "attempts": [],
        "bounded": False,
        "recovered": False,
    }
    assert (
        _native_decision(
            cases[("channel_order_ingest", "F18")],
            recovered,
            Meas0Arm.EVALUATION_PLANE,
        ).automatic_status
        is EvaluationStatus.PASS
    )
    recovered["integrity"]["actual_content_hash"] = "0" * 64
    recovered["integrity"]["actual_parent_ids"] = ["self-reported-parent"]
    assert (
        _native_decision(
            cases[("channel_order_ingest", "F18")],
            recovered,
            Meas0Arm.EVALUATION_PLANE,
        ).automatic_status
        is EvaluationStatus.PASS
    )

    forged = json.loads(
        cases[("channel_order_ingest", "F03")].native_task_bytes or b"{}"
    )
    forged["integrity"]["actual_content_hash"] = forged["integrity"][
        "declared_content_hash"
    ]
    forged["integrity"]["actual_parent_ids"] = forged["integrity"][
        "claimed_parent_ids"
    ]
    assert (
        _native_decision(
            cases[("channel_order_ingest", "F03")],
            forged,
            Meas0Arm.EVALUATION_PLANE,
        ).automatic_status
        is EvaluationStatus.FAIL
    )

    local_only = json.loads(
        cases[("channel_order_ingest", "F14")].native_task_bytes or b"{}"
    )
    local_only["local_checks"] = {
        "public": True,
        "integration": True,
        "e2e": True,
    }
    assert (
        _native_decision(
            cases[("channel_order_ingest", "F14")],
            local_only,
            Meas0Arm.EVALUATION_PLANE,
        ).automatic_status
        is EvaluationStatus.FAIL
    )

    omitted = json.loads(
        cases[("cold_chain_readiness", "F04")].native_task_bytes or b"{}"
    )
    omitted["formal_inputs"]["frozen_requirement_graph"] = omitted[
        "formal_inputs"
    ]["presented_requirement_graph"]
    assert (
        _native_decision(
            cases[("cold_chain_readiness", "F04")],
            omitted,
            Meas0Arm.EVALUATION_PLANE,
        ).run_validity
        is RunValidity.INVALID
    )

    polluted = json.loads(
        cases[("cold_chain_readiness", "F17")].native_task_bytes or b"{}"
    )
    polluted["integrity"]["actual_content_hash"] = polluted["integrity"][
        "declared_content_hash"
    ]
    polluted["integrity"]["actual_parent_ids"] = polluted["integrity"][
        "claimed_parent_ids"
    ]
    assert (
        _native_decision(
            cases[("cold_chain_readiness", "F17")],
            polluted,
            Meas0Arm.EVALUATION_PLANE,
        ).run_validity
        is RunValidity.INVALID
    )


def test_f12_capability_follows_recomputable_task_evidence() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    r1 = cases[("cold_chain_readiness", "F12")]
    assert r1.adapter_capability == "task_native"
    assert r1.native_unavailable_reason is None
    payload = json.loads(r1.native_task_bytes or b"{}")
    audit = payload["repeat_state_audit"]
    assert len(payload["native_episodes"]) == 2
    assert len(audit["attempts"]) == 2
    assert audit["attempts"][0]["after_records"] == (
        audit["attempts"][1]["before_records"]
    )
    assert len(audit["attempts"][1]["after_records"]) == 2
    assert {
        item["content_hash"]
        for item in audit["attempts"][1]["after_records"]
    } == {audit["submitted_content_hash"]}
    assert (
        _native_decision(r1, payload, Meas0Arm.EVALUATION_PLANE).automatic_status
        is EvaluationStatus.FAIL
    )

    r2 = cases[("channel_order_ingest", "F12")]
    payload = json.loads(r2.native_task_bytes or b"{}")
    assert len(payload["native_episodes"]) == 2
    for native_episode in payload["native_episodes"]:
        artifacts = {
            item["evidence_id"]: base64.b64decode(item["content_base64"])
            for item in native_episode["artifacts"]
        }
        state = json.loads(artifacts["state:result"])
        marketplace = [
            row
            for row in state["result"]["orders"]
            if row["event_id"] == "evt-market-2001"
        ]
        assert len(marketplace) == 2


def test_semantic_faults_are_native_but_do_not_forge_judge_evidence() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        for fault_id in ("F06", "F07"):
            case = cases[(task_id, fault_id)]
            assert case.adapter_capability == "task_native"
            assert case.native_unavailable_reason is None
            payload = json.loads(case.native_task_bytes or b"{}")
            audit = payload["semantic_pair_audit"]
            assert len(audit["presentations"]) == 2
            assert audit["judge_responses"] == []
            assert audit["judge_card_hash"] is None
            decision = _native_decision(
                case,
                payload,
                Meas0Arm.EVALUATION_PLANE,
            )
            assert decision.run_validity is RunValidity.VALID
            assert decision.automatic_status is EvaluationStatus.UNKNOWN
            assert decision.unavailable is True
            assert "Judge" in decision.diagnostics[0]


def test_external_measurement_plans_fail_closed_when_required_components_vanish() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    expectations = {
        "F02": (Meas0Arm.RULES_STATE, RunValidity.VALID, EvaluationStatus.FAIL),
        "F04": (Meas0Arm.EVALUATION_PLANE, RunValidity.INVALID, None),
        "F05": (Meas0Arm.STATE_ONLY, RunValidity.VALID, EvaluationStatus.UNKNOWN),
        "F08": (
            Meas0Arm.EVALUATION_PLANE,
            RunValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        "F10": (Meas0Arm.STATE_ONLY, RunValidity.VALID, EvaluationStatus.UNKNOWN),
        "F11": (
            Meas0Arm.RULES_STATE,
            RunValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        "F13": (
            Meas0Arm.EVALUATION_PLANE,
            RunValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        "F17": (Meas0Arm.EVALUATION_PLANE, RunValidity.INVALID, None),
    }
    component_by_fault = {
        "F02": "authorization_audit",
        "F04": "formal_inputs",
        "F05": "requirement_proposal",
        "F08": "checker_audit",
        "F10": "reliability_trials",
        "F11": "metamorphic_trials",
        "F13": "causal_audit",
        "F17": "integrity_audit",
    }
    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        for fault_id, (arm, validity, status) in expectations.items():
            case = cases[(task_id, fault_id)]
            assert case.native_measurement_plan is not None
            payload = json.loads(case.native_task_bytes or b"{}")
            payload.pop(component_by_fault[fault_id])
            decision = _native_decision(case, payload, arm)
            assert decision.run_validity is validity
            assert decision.automatic_status is status


def test_cross_case_native_plan_substitution_is_rejected_by_decision_primitive() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    component_by_fault = {
        "F02": "authorization_audit",
        "F04": "formal_inputs",
        "F05": "requirement_proposal",
        "F08": "checker_audit",
        "F10": "reliability_trials",
        "F11": "metamorphic_trials",
        "F13": "causal_audit",
        "F17": "integrity_audit",
    }
    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        substitute_plan = cases[(task_id, "F01")].native_measurement_plan
        assert substitute_plan is not None
        for fault_id, component in component_by_fault.items():
            target = cases[(task_id, fault_id)]
            payload = json.loads(target.native_task_bytes or b"{}")
            payload.pop(component)
            source = json.dumps(payload, sort_keys=True).encode()
            target_envelope = _native_decision_envelope(target, source)
            with pytest.raises(PilotRunnerError, match="case identity"):
                derive_native_arm_decision(
                    source,
                    Meas0Arm.EVALUATION_PLANE,
                    measurement_plan=substitute_plan,
                    expected_case_id=target.case_id,
                    sealed_case_episode=target_envelope,
                )


def test_f03_claim_and_f16_delivery_are_bound_to_sealed_episode_evidence() -> None:
    cases = {
        (case.task_id, case.fault_id): case
        for case in materialize_pilot_cases()
    }
    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        forged_case = cases[(task_id, "F03")]
        forged = json.loads(forged_case.native_task_bytes or b"{}")
        evidence = forged["native_episodes"][-1]["sealed_episode"][
            "episode_graph"
        ]["evidence"]
        claim = next(
            item
            for item in forged["native_episodes"][-1]["artifacts"]
            if item["evidence_id"] == "artifact:integrity_claim"
        )
        assert any(
            item["evidence_id"] == "artifact:integrity_claim"
            for item in evidence
        )
        claim_payload = json.loads(base64.b64decode(claim["content_base64"]))
        assert set(claim_payload) == {
            "target_evidence_id",
            "declared_content_hash",
            "claimed_parent_ids",
        }

        delivery_case = cases[(task_id, "F16")]
        delivery = json.loads(delivery_case.native_task_bytes or b"{}")
        delivery["delivery"] = {
            "content_base64": base64.b64encode(
                json.dumps(
                    {
                        "changed_files": ["forged"],
                        "checks_run": ["forged"],
                        "limitations": ["forged"],
                    }
                ).encode()
            ).decode(),
            "required_fields": [
                "changed_files",
                "checks_run",
                "limitations",
            ],
        }
        decision = _native_decision(
            delivery_case,
            delivery,
            Meas0Arm.EVALUATION_PLANE,
        )
        assert decision.automatic_status is EvaluationStatus.FAIL


def test_five_arms_share_episode_and_three_deterministic_arms_execute() -> None:
    cases = materialize_pilot_cases()
    results = run_pilot_foundation(cases)

    assert len(results) == 36 * 5
    for arm in Meas0Arm:
        selected = [result for result in results if result.arm is arm]
        assert len(selected) == 36
    for case in cases:
        selected = [result for result in results if result.case_id == case.case_id]
        assert len(selected) == 5
        assert {result.episode_hash for result in selected} == {
            case.sealed_episode.episode_hash
        }
        assert {result.bundle_hash for result in selected} == {
            case.sealed_episode.bundle_hash
        }
        assert all(len(set(result.replay_hashes)) == 1 for result in selected)

    assert all(
        (result.run_validity is RunValidity.INVALID)
        == (result.automatic_status is None)
        for result in results
    )
    assert all(
        result.automatic_status is not EvaluationStatus.INVALID
        for result in results
    )
    assert all(
        result.unavailable
        for result in results
        if result.arm is Meas0Arm.JUDGE_ONLY
    )


def test_real_arm_views_detect_state_rules_and_integrity_differences() -> None:
    results = _by_key(run_pilot_foundation(materialize_pilot_cases()))

    for task_id in ("cold_chain_readiness", "channel_order_ingest"):
        assert (
            results[(task_id, "F01", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.FAIL
        )
        assert (
            results[(task_id, "F02", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F02", Meas0Arm.RULES_STATE)].automatic_status
            is EvaluationStatus.FAIL
        )
        assert (
            results[(task_id, "F02", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.FAIL
        )
        for arm in (
            Meas0Arm.STATE_ONLY,
            Meas0Arm.RULES_STATE,
            Meas0Arm.EVALUATION_PLANE,
        ):
            assert (
                results[(task_id, "F05", arm)].automatic_status
                is EvaluationStatus.UNKNOWN
            )
            assert (
                results[(task_id, "F08", arm)].automatic_status
                is EvaluationStatus.UNKNOWN
            )
            assert (
                results[(task_id, "F10", arm)].automatic_status
                is EvaluationStatus.FAIL
            )
        assert (
            results[(task_id, "F11", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F11", Meas0Arm.RULES_STATE)].automatic_status
            is EvaluationStatus.FAIL
        )
        assert (
            results[(task_id, "F11", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.FAIL
        )
        assert (
            results[(task_id, "F13", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F13", Meas0Arm.RULES_STATE)].automatic_status
            is EvaluationStatus.DISPUTED
        )
        assert (
            results[(task_id, "F13", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.DISPUTED
        )
        omitted = results[(task_id, "F04", Meas0Arm.EVALUATION_PLANE)]
        assert omitted.run_validity is RunValidity.INVALID
        assert omitted.automatic_status is None
        assert (
            results[(task_id, "F12", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.FAIL
        )
        assert (
            results[(task_id, "F18", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F03", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F03", Meas0Arm.RULES_STATE)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F03", Meas0Arm.EVALUATION_PLANE)].automatic_status
            is EvaluationStatus.FAIL
        )
        for fault_id in ("F12", "F14", "F15", "F16"):
            for arm in (
                Meas0Arm.STATE_ONLY,
                Meas0Arm.RULES_STATE,
                Meas0Arm.EVALUATION_PLANE,
            ):
                assert (
                    results[(task_id, fault_id, arm)].automatic_status
                    is EvaluationStatus.FAIL
                )
        for fault_id in ("F04", "F09"):
            assert (
                results[(task_id, fault_id, Meas0Arm.STATE_ONLY)].automatic_status
                is EvaluationStatus.PASS
            )
            assert (
                results[(task_id, fault_id, Meas0Arm.RULES_STATE)].automatic_status
                is EvaluationStatus.PASS
            )
            formal = results[(task_id, fault_id, Meas0Arm.EVALUATION_PLANE)]
            assert formal.run_validity is RunValidity.INVALID
            assert formal.automatic_status is None
        assert (
            results[(task_id, "F17", Meas0Arm.STATE_ONLY)].automatic_status
            is EvaluationStatus.PASS
        )
        assert (
            results[(task_id, "F17", Meas0Arm.RULES_STATE)].automatic_status
            is EvaluationStatus.FAIL
        )
        polluted = results[(task_id, "F17", Meas0Arm.EVALUATION_PLANE)]
        assert polluted.run_validity is RunValidity.INVALID
        assert polluted.automatic_status is None


def test_arm_evaluation_never_reads_case_gold_labels() -> None:
    case = next(
        item
        for item in materialize_pilot_cases()
        if item.task_id == "cold_chain_readiness" and item.fault_id == "F01"
    )
    original = run_pilot_foundation((case,))
    relabelled = replace(
        case,
        gold_run_validity=RunValidity.VALID,
        gold_status=EvaluationStatus.PASS,
        accept_allowed=True,
        safety_violation=True,
    )
    replayed = run_pilot_foundation((relabelled,))

    assert [
        (
            item.arm,
            item.run_validity,
            item.automatic_status,
            item.result_hash,
            item.trace_hash,
        )
        for item in original
    ] == [
        (
            item.arm,
            item.run_validity,
            item.automatic_status,
            item.result_hash,
            item.trace_hash,
        )
        for item in replayed
    ]
    observable = __import__("json").loads(case.observable_bytes)
    assert "gold_status" not in observable
    assert "predicted_status" not in observable
    assert "signals" not in observable


def test_cost_vector_is_complete_and_failures_remain_in_denominator() -> None:
    results = run_pilot_foundation(materialize_pilot_cases())
    summary = aggregate_pilot_foundation(results)

    assert set(summary) == {arm.value for arm in Meas0Arm}
    assert all(metrics["cases"] == 36 for metrics in summary.values())
    assert all(metrics["unavailable"] >= 0 for metrics in summary.values())
    assert summary["judge_only"]["unavailable"] == 36
    assert summary["evaluation_plane"]["invalid"] >= 6
    for result in results:
        payload = result.cost_vector.to_dict()
        assert set(payload) == {
            "model_calls",
            "input_tokens",
            "output_tokens",
            "tool_calls",
            "wall_time_ms",
            "cpu_time_ms",
            "bytes_transferred",
            "communication_messages",
            "communication_tokens",
            "state_update_calls",
            "verifier_calls",
            "deterministic_check_calls",
            "judge_calls",
            "human_escalations",
            "retry_count",
        }
        assert all(value >= 0 for value in payload.values())


def test_pilot_case_artifact_tampering_fails_closed() -> None:
    case = materialize_pilot_cases()[0]
    evidence_id, content = case.artifacts.items[-1]
    tampered = replace(
        case,
        artifacts=replace(
            case.artifacts,
            items=(
                *case.artifacts.items[:-1],
                (evidence_id, content + b"tampered"),
            ),
        ),
    )

    with pytest.raises(PilotRunnerError, match="content hash"):
        verify_pilot_case(tampered)
    with pytest.raises(PilotRunnerError, match="content hash"):
        run_pilot_foundation((tampered,))


def test_task_native_artifact_tampering_fails_closed() -> None:
    case = next(
        item for item in materialize_pilot_cases() if item.native_task_bytes
    )
    tampered_items = tuple(
        (
            evidence_id,
            content + b"tampered"
            if evidence_id == "artifact:native_task"
            else content,
        )
        for evidence_id, content in case.artifacts.items
    )
    tampered = replace(
        case,
        artifacts=replace(case.artifacts, items=tampered_items),
    )

    with pytest.raises(PilotRunnerError, match="content hash"):
        verify_pilot_case(tampered)


def test_manifest_parser_rejects_missing_fault_and_unknown_operator(
    tmp_path: Path,
) -> None:
    manifest = load_pilot_mutation_manifest()
    payload = manifest.to_dict()
    payload["faults"] = payload["faults"][:-1]
    fixture_directory = tmp_path / "meas0" / "pilot"
    fixture_directory.mkdir(parents=True)
    path = fixture_directory / "mutations.v8.json"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(PilotRunnerError, match="F01-F18"):
        load_pilot_mutation_manifest(fixture_root=tmp_path)

    payload = manifest.to_dict()
    payload["faults"][0]["operator"] = "lookup_prelabelled_signal"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(PilotRunnerError, match="operator"):
        load_pilot_mutation_manifest(fixture_root=tmp_path)
