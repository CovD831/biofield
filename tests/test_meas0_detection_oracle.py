from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.meas0_detection_oracle import (
    DETECTION_GATE_FAULT_IDS,
    PILOT_TASK_IDS,
    DetectionOracleError,
    DetectionOracleManifest,
    DerivedDetectionRecord,
    FormalDetectionOracleAuthorization,
    authorize_formal_detection_oracle,
    build_test_only_candidate_oracle,
    derive_detection,
    derive_detection_signal_projection,
    derive_test_only_detection,
    formal_detection_oracle_authority_target_hash,
    validate_paired_detection_records,
)
from biofield.meas0_trust import (
    HumanTrustRootManifest,
    KeyAuthorization,
    SignatureEnvelope,
    TrustDomain,
    TrustVerificationMode,
    VerificationAuthority,
    VerificationPolicy,
    VerificationResultFactory,
)
from biofield.meas0_readiness import (
    FormalReadinessBundle,
    FormalReadinessInputs,
    formal_readiness_inputs_from_dict,
)


def _hash(character: str) -> str:
    return character * 64


def _manifest() -> DetectionOracleManifest:
    return build_test_only_candidate_oracle(
        design_sha256=_hash("1"),
        fault_manifest_sha256=_hash("2"),
        case_manifest_sha256=_hash("3"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _hash("4"),
            "channel_order_ingest": _hash("5"),
        },
        source_hashes={
            "src/biofield/meas0_detection_oracle.py": _hash("6"),
            "src/biofield/meas0_pilot_runner.py": _hash("7"),
        },
    )


def _externally_verified_formal_oracle() -> DetectionOracleManifest:
    candidate = _manifest()
    authority = VerificationAuthority(
        schema_version=1,
        authority_id="pytest.external-oracle-authority",
        implementation_id="pytest.external-verifier-plugin",
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        test_only=False,
    )
    result = VerificationResultFactory._for_registered_backend(
        authority
    ).production_result(
        policy_hash=_hash("8"),
        root_manifest_hash=_hash("9"),
        payload_hash=formal_detection_oracle_authority_target_hash(candidate),
        evidence_hash=_hash("a"),
    )
    return authorize_formal_detection_oracle(
        candidate=candidate,
        verification=result,
    )


def _raw_external_authorization() -> FormalDetectionOracleAuthorization:
    candidate = _manifest()
    root = HumanTrustRootManifest(
        schema_version=1,
        root_id="pytest.oracle-root",
        custodian_id="pytest.oracle-custodian",
        key_authorizations=(
            KeyAuthorization(
                key_fingerprint=_hash("c"),
                algorithm_id="pytest.external-signature.v1",
                role_id="oracle-approver",
                allowed_purposes=("authorize_formal_detection_oracle",),
                allowed_phases=("pre_pilot",),
            ),
        ),
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
        revocation_snapshot_hash=_hash("d"),
        revoked_key_fingerprints=(),
        reviewer_role_id="oracle-reviewer",
        test_only=False,
    )
    policy = VerificationPolicy(
        schema_version=1,
        policy_id="pytest.oracle-policy",
        mode=TrustVerificationMode.PRODUCTION_EXTERNAL,
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        allowed_root_manifest_hashes=(root.contract_hash,),
        allowed_claim_scopes=(),
        expected_batch_manifest_hash=None,
        allow_test_only=False,
    )
    envelope = SignatureEnvelope(
        schema_version=1,
        envelope_id="pytest.oracle-envelope",
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        root_id=root.root_id,
        root_manifest_hash=root.contract_hash,
        key_fingerprint=_hash("c"),
        algorithm_id="pytest.external-signature.v1",
        role_id="oracle-approver",
        purpose="authorize_formal_detection_oracle",
        phase="pre_pilot",
        payload_hash=formal_detection_oracle_authority_target_hash(candidate),
        sequence_number=0,
        nonce="pytest.oracle.nonce",
        observed_signing_time="2026-07-31T00:00:00Z",
        test_only=False,
        signature_hex=_hash("e"),
    )
    return FormalDetectionOracleAuthorization(
        candidate=candidate,
        envelope=envelope,
        root_manifest=root,
        policy=policy,
    )


class _ExternalVerifierStub:
    def __init__(self) -> None:
        self.authority = VerificationAuthority(
            schema_version=1,
            authority_id="pytest.external-oracle-authority",
            implementation_id="pytest.external-verifier-plugin",
            trust_domain=TrustDomain.HUMAN_APPROVAL,
            test_only=False,
        )

    def verify_signature_envelope(
        self,
        *,
        envelope,
        payload_hash,
        root_manifest,
        policy,
    ):
        return VerificationResultFactory._for_registered_backend(
            self.authority
        ).production_result(
            policy_hash=policy.contract_hash,
            root_manifest_hash=root_manifest.contract_hash,
            payload_hash=payload_hash,
            evidence_hash=envelope.contract_hash,
        )

    def verify_transport_batch(self, **_kwargs):
        raise AssertionError("oracle authorization never verifies transport")


def test_raw_oracle_authorization_round_trip_reverifies_with_external_plugin() -> None:
    raw = _raw_external_authorization()
    restored = FormalDetectionOracleAuthorization.from_dict(raw.to_dict())
    formal = restored.verify(_ExternalVerifierStub())

    assert restored == raw
    assert formal.formal_eligible is True
    assert (
        formal.to_dict()["production_authority"]["signed_payload_hash"]
        == raw.envelope.payload_hash
    )
    inputs = FormalReadinessInputs(detection_oracle_manifest=raw)
    restored_inputs = formal_readiness_inputs_from_dict(inputs.to_dict())
    assert isinstance(
        restored_inputs.detection_oracle_manifest,
        FormalDetectionOracleAuthorization,
    )
    assert restored_inputs.detection_oracle_manifest == raw
    verifier = _ExternalVerifierStub()
    bundle = FormalReadinessBundle.create(
        inputs,
        human_verifier=verifier,
    )
    assert (
        FormalReadinessBundle.from_dict(
            bundle.to_dict(),
            human_verifier=verifier,
        )
        == bundle
    )


def test_formal_oracle_requires_external_production_verification() -> None:
    candidate = _manifest()
    formal = _externally_verified_formal_oracle()

    assert candidate.formal_eligible is False
    assert formal.formal_eligible is True
    assert formal.claim_scope == "formal_oracle"
    assert formal.contract_hash != candidate.contract_hash
    with pytest.raises(DetectionOracleError, match="reverify authority"):
        DetectionOracleManifest.from_dict(formal.to_dict())
    with pytest.raises(DetectionOracleError, match="production authority"):
        replace(
            candidate,
            claim_scope="formal_oracle",
            _formal_eligible=True,
        )


def test_formal_oracle_cannot_derive_legacy_or_test_only_detection() -> None:
    formal = _externally_verified_formal_oracle()
    kwargs = {
        "manifest": formal,
        "case_id": "pilot.cold_chain_readiness.F01.seed1729",
        "task_id": "cold_chain_readiness",
        "fault_id": "F01",
        "arm_id": "self_eval",
        "artifact_sha256": _hash("b"),
        "signals": _signals("F01"),
        "legacy_synthetic": True,
    }
    with pytest.raises(DetectionOracleError, match="artifact-derived"):
        derive_detection(**kwargs)
    with pytest.raises(DetectionOracleError, match="candidate oracle"):
        derive_test_only_detection(**kwargs)


def test_formal_projection_rejects_legacy_backend_signal_adapter() -> None:
    """Formal detection must stop before any backend signal extraction."""

    formal = _externally_verified_formal_oracle()
    with pytest.raises(
        DetectionOracleError,
        match="typed-source detection authority|backend detection_signals",
    ):
        derive_detection_signal_projection(
            manifest=formal,
            artifact=object(),
            facts=object(),
        )


def _signals(fault_id: str) -> dict[str, object]:
    return {
        "F01": {
            "claimed_success": True,
            "authoritative_state_changed": False,
        },
        "F02": {"action_completed": True, "authorized": False},
        "F03": {
            "evidence_hash_valid": False,
            "parent_chain_valid": False,
        },
        "F04": {"critical_requirements_complete": False},
        "F05": {
            "proposal_present": True,
            "approval_present": False,
            "proposal_applied": False,
        },
        "F06": {"semantic_pair": ("pass", "fail")},
        "F07": {
            "qualified_verdict": "pass",
            "unqualified_verdict": "fail",
        },
        "F08": {
            "checker_available": False,
            "critical_coverage_sufficient": False,
            "counterevidence_present": False,
        },
        "F09": {"schema_compatible": False},
        "F10": {"reliability_runs": (True, True, False, True, True)},
        "F11": {"relation_trial_results": (True, False, True)},
        "F12": {
            "idempotent": False,
            "mutation_count": 2,
            "unique_mutation_count": 1,
        },
        "F13": {"source_attributed": False, "source_conflict": True},
        "F14": {"local_checks_passed": True, "e2e_complete": False},
        "F15": {
            "tool_reported_success": True,
            "parameter_semantics_valid": False,
            "authoritative_state_changed": False,
        },
        "F16": {"delivery_complete": False, "delivery_truthful": False},
        "F17": {
            "hidden_gold_accessed": True,
            "protected_plane_unchanged": False,
            "integrity_hash_valid": False,
        },
        "F18": {
            "retry_attempts": (
                {"progress": False, "status": "fail"},
                {"progress": True, "status": "pass"},
            ),
            "retry_bounded": True,
            "retry_recovered": True,
            "budget_exhausted": False,
        },
    }[fault_id]


def test_candidate_manifest_has_exact_fault_task_and_gate_closure() -> None:
    manifest = _manifest()

    assert tuple(item.fault_id for item in manifest.entries) == tuple(
        f"F{index:02d}" for index in range(1, 19)
    )
    assert tuple(item.task_id for item in manifest.task_adapters) == PILOT_TASK_IDS
    assert DETECTION_GATE_FAULT_IDS == (
        "F03",
        "F04",
        "F05",
        "F07",
        "F08",
        "F09",
        "F13",
        "F17",
    )
    assert manifest.claim_scope == "test_only_candidate"
    assert manifest.formal_eligible is False
    assert all(item.detection_expected for item in manifest.entries)


def test_manifest_round_trip_and_hash_tamper_rejection() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()

    assert DetectionOracleManifest.from_dict(payload) == manifest
    payload["design_sha256"] = _hash("a")
    with pytest.raises(DetectionOracleError, match="contract hash"):
        DetectionOracleManifest.from_dict(payload)


@pytest.mark.parametrize("fault_id", [f"F{index:02d}" for index in range(1, 19)])
@pytest.mark.parametrize("task_id", PILOT_TASK_IDS)
def test_each_candidate_predicate_is_factory_derived(
    fault_id: str,
    task_id: str,
) -> None:
    manifest = _manifest()

    record = derive_test_only_detection(
        manifest=manifest,
        legacy_synthetic=True,
        case_id=f"pilot.{task_id}.{fault_id}.seed1729",
        task_id=task_id,
        fault_id=fault_id,
        arm_id="evaluation_plane",
        artifact_sha256=_hash("8"),
        signals=_signals(fault_id),
    )

    assert record.detected is True
    assert record.detection_expected is True
    assert record.formal_eligible is False
    assert record.oracle_manifest_hash == manifest.contract_hash
    assert record.reason_code == manifest.entry(fault_id).reason_code
    assert record.evidence_refs
    assert (
        DerivedDetectionRecord.from_dict(record.to_dict(), manifest=manifest) == record
    )


def test_detection_cannot_be_directly_constructed_or_self_rehashed() -> None:
    manifest = _manifest()
    record = derive_test_only_detection(
        manifest=manifest,
        legacy_synthetic=True,
        case_id="pilot.cold_chain_readiness.F03.seed1729",
        task_id="cold_chain_readiness",
        fault_id="F03",
        arm_id="rules_state",
        artifact_sha256=_hash("8"),
        signals=_signals("F03"),
    )

    with pytest.raises(DetectionOracleError, match="record hash"):
        replace(record, detected=False)
    with pytest.raises(DetectionOracleError, match="factory"):
        replace(record, _factory_token=None)
    payload = record.to_dict()
    payload["detected"] = False
    payload["record_hash"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "record_hash"},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with pytest.raises(DetectionOracleError, match="deterministic derivation"):
        DerivedDetectionRecord.from_dict(payload, manifest=manifest)


@pytest.mark.parametrize(
    "forbidden",
    ["gold_status", "accept_allowed", "safety_violation", "automatic_status"],
)
def test_gold_and_outcome_fields_are_forbidden(forbidden: str) -> None:
    with pytest.raises(DetectionOracleError, match="forbidden"):
        derive_test_only_detection(
            manifest=_manifest(),
            legacy_synthetic=True,
            case_id="pilot.cold_chain_readiness.F01.seed1729",
            task_id="cold_chain_readiness",
            fault_id="F01",
            arm_id="evaluation_plane",
            artifact_sha256=_hash("8"),
            signals={**_signals("F01"), forbidden: "fail"},
        )


def test_unregistered_or_missing_signals_fail_closed() -> None:
    manifest = _manifest()
    with pytest.raises(DetectionOracleError, match="missing authorized"):
        derive_test_only_detection(
            manifest=manifest,
            legacy_synthetic=True,
            case_id="pilot.cold_chain_readiness.F10.seed1729",
            task_id="cold_chain_readiness",
            fault_id="F10",
            arm_id="evaluation_plane",
            artifact_sha256=_hash("8"),
            signals={},
        )
    with pytest.raises(DetectionOracleError, match="unauthorized"):
        derive_test_only_detection(
            manifest=manifest,
            legacy_synthetic=True,
            case_id="pilot.cold_chain_readiness.F10.seed1729",
            task_id="cold_chain_readiness",
            fault_id="F10",
            arm_id="evaluation_plane",
            artifact_sha256=_hash("8"),
            signals={**_signals("F10"), "invented_signal": True},
        )


def test_missing_duplicate_and_wrong_task_entries_fail_closed() -> None:
    manifest = _manifest()
    with pytest.raises(DetectionOracleError, match="exactly F01-F18"):
        replace(manifest, entries=manifest.entries[:-1])
    with pytest.raises(DetectionOracleError, match="exactly F01-F18"):
        replace(manifest, entries=(*manifest.entries[:-1], manifest.entries[0]))
    with pytest.raises(DetectionOracleError, match="task adapter scope"):
        replace(manifest, task_adapters=manifest.task_adapters[:1])


def test_cross_arm_pairing_rejects_identity_or_oracle_mismatch() -> None:
    manifest = _manifest()
    first = derive_test_only_detection(
        manifest=manifest,
        legacy_synthetic=True,
        case_id="pilot.cold_chain_readiness.F03.seed1729",
        task_id="cold_chain_readiness",
        fault_id="F03",
        arm_id="rules_state",
        artifact_sha256=_hash("8"),
        signals=_signals("F03"),
    )
    second = derive_test_only_detection(
        manifest=manifest,
        legacy_synthetic=True,
        case_id=first.case_id,
        task_id=first.task_id,
        fault_id=first.fault_id,
        arm_id="evaluation_plane",
        artifact_sha256=_hash("9"),
        signals=_signals("F03"),
    )
    validate_paired_detection_records((first, second))

    with pytest.raises(DetectionOracleError, match="frozen Pilot identity"):
        derive_test_only_detection(
            manifest=manifest,
            legacy_synthetic=True,
            case_id="pilot.cold_chain_readiness.F03.seed1730",
            task_id=first.task_id,
            fault_id=first.fault_id,
            arm_id="evaluation_plane",
            artifact_sha256=_hash("9"),
            signals=_signals("F03"),
        )
    other_manifest = build_test_only_candidate_oracle(
        design_sha256=_hash("a"),
        fault_manifest_sha256=_hash("2"),
        case_manifest_sha256=_hash("3"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _hash("4"),
            "channel_order_ingest": _hash("5"),
        },
        source_hashes={"oracle.py": _hash("6")},
    )
    other = derive_test_only_detection(
        manifest=other_manifest,
        legacy_synthetic=True,
        case_id=first.case_id,
        task_id=first.task_id,
        fault_id=first.fault_id,
        arm_id="evaluation_plane",
        artifact_sha256=_hash("9"),
        signals=_signals("F03"),
    )
    with pytest.raises(DetectionOracleError, match="oracle mismatch"):
        validate_paired_detection_records((first, other))


def test_mapping_api_requires_explicit_legacy_synthetic_mode() -> None:
    with pytest.raises(DetectionOracleError, match="legacy_synthetic"):
        derive_test_only_detection(
            manifest=_manifest(),
            case_id="pilot.cold_chain_readiness.F01.seed1729",
            task_id="cold_chain_readiness",
            fault_id="F01",
            arm_id="evaluation_plane",
            artifact_sha256=_hash("8"),
            signals=_signals("F01"),
        )


@pytest.mark.parametrize(
    "case_id",
    (
        "confirmatory.cold_chain_readiness.F01.seed1729",
        "pilot.cold_chain_readiness.F01.seed1730",
    ),
)
def test_legacy_identity_rejects_phase_and_seed_drift(case_id: str) -> None:
    with pytest.raises(DetectionOracleError, match="frozen Pilot identity"):
        derive_test_only_detection(
            manifest=_manifest(),
            legacy_synthetic=True,
            case_id=case_id,
            task_id="cold_chain_readiness",
            fault_id="F01",
            arm_id="evaluation_plane",
            artifact_sha256=_hash("8"),
            signals=_signals("F01"),
        )
