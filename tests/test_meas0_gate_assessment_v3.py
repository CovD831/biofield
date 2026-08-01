from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace

import pytest

from biofield.meas0_gate_assessment_v3 import (
    B8B_PRODUCTION_SNAPSHOT_GAP,
    HARD_GATE_CRITERION_IDS,
    REQUIRED_GATE_CLOSURE_ROLES,
    CriterionFactStatus,
    GateAssessmentV3Error,
    GateEvidenceSliceV3,
    GateMAssessmentPreviewV3,
    GateMPreviewState,
    SimulatedSealedGateEvidenceIndexV3,
    derive_gate_m_assessment_preview,
    derive_gate_m_terminal,
    derive_verified_hard_gate_assessment,
)


def _hash(character: str) -> str:
    return character * 64


def _slice(
    criterion_id: str,
    *,
    comparison_block_id: str = "pytest.block.v3",
    common_ancestry_hash: str = _hash("a"),
    observed: tuple[str, ...] = ("member.1", "member.2"),
    violations: tuple[str, ...] = (),
) -> GateEvidenceSliceV3:
    return GateEvidenceSliceV3.create(
        criterion_id=criterion_id,
        comparison_block_id=comparison_block_id,
        common_ancestry_hash=common_ancestry_hash,
        required_member_ids=("member.1", "member.2"),
        observed_member_ids=observed,
        violation_member_ids=violations,
        member_evidence_refs=tuple(
            (member_id, hashlib.sha256(member_id.encode()).hexdigest())
            for member_id in observed
        ),
    )


def _index(
    *,
    slices: tuple[GateEvidenceSliceV3, ...] | None = None,
    closure_roles: tuple[str, ...] = REQUIRED_GATE_CLOSURE_ROLES,
) -> SimulatedSealedGateEvidenceIndexV3:
    if slices is None:
        slices = tuple(_slice(criterion_id) for criterion_id in HARD_GATE_CRITERION_IDS)
    return SimulatedSealedGateEvidenceIndexV3.create(
        comparison_block_id="pytest.block.v3",
        common_ancestry_hash=_hash("a"),
        source_lock_hash=_hash("b"),
        sealed_package_hash=_hash("c"),
        closure_evidence_refs=tuple(
            (role, hashlib.sha256(role.encode()).hexdigest()) for role in closure_roles
        ),
        criterion_slices=slices,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_complete_simulated_index_only_derives_diagnostics_and_never_terminal() -> None:
    preview = derive_gate_m_assessment_preview(_index())

    assert preview.hard_gate_status is CriterionFactStatus.UNKNOWN
    assert preview.assessment_complete is False
    assert tuple(item.criterion_id for item in preview.criteria) == (
        HARD_GATE_CRITERION_IDS
    )
    assert all(item.status is CriterionFactStatus.UNKNOWN for item in preview.criteria)
    assert all(not item.missing_member_ids for item in preview.criteria)
    assert preview.missing_criterion_ids == ()
    assert preview.missing_closure_roles == ()
    assert preview.gate_m_state is GateMPreviewState.NOT_EVALUATED
    assert preview.terminal is False
    assert preview.terminal_receipt_hash is None
    assert preview.claim_scope == "simulated_nonclaim"
    assert preview.formal_eligible is False
    assert preview.prohibited_claim_scopes == (
        "formal_gate_m_terminal",
        "pilot_evidence",
        "confirmatory_evidence",
        "scientific_evidence",
    )


def test_caller_created_slice_membership_cannot_determine_any_gate_fact() -> None:
    complete = derive_gate_m_assessment_preview(_index())
    violated = list(_index().criterion_slices)
    violated[0] = _slice("13.1.1", violations=("member.1",))
    caller_flagged = derive_gate_m_assessment_preview(_index(slices=tuple(violated)))

    for preview in (complete, caller_flagged):
        assert preview.hard_gate_status is CriterionFactStatus.UNKNOWN
        assert preview.assessment_complete is False
        assert all(
            fact.status is CriterionFactStatus.UNKNOWN for fact in preview.criteria
        )
        assert "B8B_VERIFIED_SNAPSHOT_UNAVAILABLE" in preview.reason_codes


def test_caller_flagged_violation_and_missing_members_are_diagnostics_only() -> None:
    violated = list(_index().criterion_slices)
    violated[2] = _slice("13.1.3", violations=("member.2",))
    failed = derive_gate_m_assessment_preview(_index(slices=tuple(violated)))

    assert failed.assessment_complete is False
    assert failed.hard_gate_status is CriterionFactStatus.UNKNOWN
    assert failed.criteria[2].status is CriterionFactStatus.UNKNOWN
    assert failed.criteria[2].missing_member_ids == ()
    assert failed.criteria[2].violation_member_ids == ("member.2",)
    assert failed.gate_m_state is GateMPreviewState.NOT_EVALUATED

    incomplete = list(_index().criterion_slices)
    incomplete[2] = _slice("13.1.3", observed=("member.1",))
    unknown = derive_gate_m_assessment_preview(_index(slices=tuple(incomplete)))

    assert unknown.assessment_complete is False
    assert unknown.hard_gate_status is CriterionFactStatus.UNKNOWN
    assert unknown.criteria[2].status is CriterionFactStatus.UNKNOWN
    assert unknown.criteria[2].missing_member_ids == ("member.2",)
    assert unknown.gate_m_state is GateMPreviewState.NOT_EVALUATED


def test_deleted_criterion_or_closure_evidence_cannot_default_to_pass() -> None:
    missing_slice = derive_gate_m_assessment_preview(
        _index(slices=_index().criterion_slices[:-1])
    )
    assert missing_slice.hard_gate_status is CriterionFactStatus.UNKNOWN
    assert missing_slice.criteria[-1].criterion_id == "13.1.8"
    assert missing_slice.criteria[-1].status is CriterionFactStatus.UNKNOWN
    assert "13.1.8" in missing_slice.missing_criterion_ids

    missing_role = REQUIRED_GATE_CLOSURE_ROLES[-1]
    missing_closure = derive_gate_m_assessment_preview(
        _index(closure_roles=REQUIRED_GATE_CLOSURE_ROLES[:-1])
    )
    assert missing_closure.hard_gate_status is CriterionFactStatus.UNKNOWN
    assert missing_closure.assessment_complete is False
    assert missing_closure.missing_closure_roles == (missing_role,)
    assert missing_closure.gate_m_state is GateMPreviewState.NOT_EVALUATED


def test_assessment_rejects_caller_boolean_and_non_index_inputs() -> None:
    parameters = inspect.signature(derive_gate_m_assessment_preview).parameters
    assert tuple(parameters) == ("evidence_index",)
    assert {
        "passed",
        "pass_ids",
        "count",
        "coverage",
        "replay_verified",
        "qualification_passed",
    }.isdisjoint(parameters)

    for forged in (
        True,
        {"passed": True},
        {"count": 144, "coverage": 1.0},
        object(),
    ):
        with pytest.raises(GateAssessmentV3Error, match="typed sealed evidence index"):
            derive_gate_m_assessment_preview(forged)  # type: ignore[arg-type]


def test_index_rejects_cross_ancestry_duplicate_and_unbacked_membership() -> None:
    cross_block = tuple(
        (
            _slice("13.1.4", comparison_block_id="pytest.other.block")
            if item.criterion_id == "13.1.4"
            else item
        )
        for item in _index().criterion_slices
    )
    with pytest.raises(GateAssessmentV3Error, match="common ancestry"):
        _index(slices=cross_block)

    duplicate = (*_index().criterion_slices, _index().criterion_slices[-1])
    with pytest.raises(GateAssessmentV3Error, match="ordered"):
        _index(slices=duplicate)

    with pytest.raises(GateAssessmentV3Error, match="evidence refs"):
        GateEvidenceSliceV3.create(
            criterion_id="13.1.1",
            comparison_block_id="pytest.block.v3",
            common_ancestry_hash=_hash("a"),
            required_member_ids=("member.1",),
            observed_member_ids=("member.1",),
            violation_member_ids=(),
            member_evidence_refs=(),
        )


def test_strict_sealed_codec_is_deterministic_and_scope_cannot_be_upgraded() -> None:
    index = _index()
    sealed_bytes = index.to_canonical_bytes()
    sealed_hash = hashlib.sha256(sealed_bytes).hexdigest()

    restored = SimulatedSealedGateEvidenceIndexV3.restore_from_sealed_bytes(
        sealed_bytes,
        expected_sha256=sealed_hash,
    )
    assert restored == index
    assert restored.to_canonical_bytes() == sealed_bytes
    assert derive_gate_m_assessment_preview(restored).assessment_hash == (
        derive_gate_m_assessment_preview(index).assessment_hash
    )

    tampered = index.to_dict()
    tampered["comparison_block_id"] = "pytest.changed.block"
    with pytest.raises(GateAssessmentV3Error, match="sealed bytes hash"):
        SimulatedSealedGateEvidenceIndexV3.restore_from_sealed_bytes(
            _canonical(tampered),
            expected_sha256=sealed_hash,
        )

    upgraded = index.to_dict()
    upgraded["claim_scope"] = "formal_gate_m_terminal"
    upgraded_bytes = _canonical(upgraded)
    with pytest.raises(GateAssessmentV3Error, match="claim boundary"):
        SimulatedSealedGateEvidenceIndexV3.restore_from_sealed_bytes(
            upgraded_bytes,
            expected_sha256=hashlib.sha256(upgraded_bytes).hexdigest(),
        )


def test_direct_dataclass_construction_and_local_resigning_do_not_create_authority() -> (
    None
):
    source = _slice("13.1.1")
    with pytest.raises(GateAssessmentV3Error, match="factory-derived|hash changed"):
        replace(source, violation_member_ids=("member.1",))

    source_index = _index()
    with pytest.raises(GateAssessmentV3Error, match="factory-derived|hash changed"):
        replace(source_index, sealed_package_hash=_hash("f"))


def test_formal_terminal_factory_fails_closed_without_b8b_production_snapshot() -> None:
    parameters = inspect.signature(derive_gate_m_terminal).parameters
    assert tuple(parameters) == ("verified_snapshot",)
    assert "passed" not in parameters

    with pytest.raises(GateAssessmentV3Error, match="simulated_nonclaim"):
        derive_gate_m_terminal(_index())
    with pytest.raises(GateAssessmentV3Error, match="B8b"):
        derive_gate_m_terminal(object())
    assert "B8b" in B8B_PRODUCTION_SNAPSHOT_GAP

    payload = derive_gate_m_assessment_preview(_index()).to_dict()
    assert payload["gate_m_state"] == "not_evaluated"
    assert payload["terminal"] is False
    assert payload["terminal_receipt_hash"] is None
    assert "passed" not in payload


def test_formal_hard_gate_factory_requires_future_b8b_verified_snapshot() -> None:
    parameters = inspect.signature(derive_verified_hard_gate_assessment).parameters
    assert tuple(parameters) == ("verified_snapshot",)
    assert "passed" not in parameters

    with pytest.raises(GateAssessmentV3Error, match="simulated_nonclaim"):
        derive_verified_hard_gate_assessment(_index())
    with pytest.raises(GateAssessmentV3Error, match="B8b"):
        derive_verified_hard_gate_assessment(object())


def test_not_evaluated_preview_replay_is_derived_and_rejects_local_resigning() -> None:
    index = _index()
    preview = derive_gate_m_assessment_preview(index)

    assert (
        GateMAssessmentPreviewV3.restore_from_index(
            preview.to_dict(),
            evidence_index=index,
        )
        == preview
    )

    for field_name, forged_value in (
        ("gate_m_state", "pass"),
        ("terminal", True),
        ("formal_eligible", True),
        ("assessment_complete", 1),
    ):
        forged = preview.to_dict()
        forged[field_name] = forged_value
        body = dict(forged)
        body.pop("assessment_hash")
        forged["assessment_hash"] = hashlib.sha256(_canonical(body)).hexdigest()
        with pytest.raises(GateAssessmentV3Error, match="exact derived"):
            GateMAssessmentPreviewV3.restore_from_index(
                forged,
                evidence_index=index,
            )


def test_nonclaim_fact_and_preview_types_reject_rehashed_pass_or_fail_states() -> None:
    preview = derive_gate_m_assessment_preview(_index())
    fact = preview.criteria[0]
    fact_body = fact._body()
    fact_body["status"] = "pass"
    with pytest.raises(GateAssessmentV3Error, match="UNKNOWN"):
        replace(
            fact,
            status=CriterionFactStatus.PASS,
            fact_hash=hashlib.sha256(_canonical(fact_body)).hexdigest(),
        )
