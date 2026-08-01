from __future__ import annotations

import json

import pytest

from biofield.meas0_protected_vault import SimulatedProtectedEvidenceVault
from biofield.meas0_raw_package_closure_v3 import (
    PUBLIC_PILOT_SLICE_FILES,
    RawPackageClosureError,
    SimulatedPublicPackageClosure,
)
from test_meas0_pilot_plan_v3 import _candidate, _hash


def _sources():
    candidate = _candidate()
    vault = SimulatedProtectedEvidenceVault.create(
        vault_id="pytest-raw-closure-vault",
        package_id="pytest.meas0.package.v3",
        common_ancestry_hash=candidate.common_ancestry_hash,
        acl_policy_hash=_hash(81),
        encryption_policy_hash=_hash(82),
        retention_policy_ref=_hash(83),
        legal_hold_ref=_hash(84),
    )
    references = (
        vault.write_once(
            object_id="protected-task-inputs",
            payload=b"exact protected test task bytes",
            classification="test_data",
        ),
        vault.write_once(
            object_id="protected-judge-material",
            payload=b"exact protected test judge bytes",
            classification="test_data",
        ),
    )
    return candidate, vault.seal(), references


def _closure() -> SimulatedPublicPackageClosure:
    candidate, manifest, references = _sources()
    return SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )


def test_typed_public_pilot_slice_is_closed_without_raw_or_replay_upgrade() -> None:
    closure = _closure()

    assert tuple(item.relative_path for item in closure.artifacts) == (
        PUBLIC_PILOT_SLICE_FILES
    )
    assert closure.claim_scope == "simulated_nonclaim"
    assert closure.production_authorized is False
    assert closure.test_only is True
    assert closure.slice_membership_closed is True
    assert closure.raw_package_closed is False
    assert closure.source_restoration_authorized is False
    assert closure.fresh_replay_ready is False
    assert closure.missing_replay_authorities == (
        "complete_public_and_protected_raw_closure",
        "source_restoration_artifact",
        "transport_verifier",
        "human_signature_verifier",
        "authority_bound_package_seal",
    )


def test_restore_rederives_all_files_and_requires_external_closure_binding() -> None:
    candidate, manifest, references = _sources()
    closure = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )

    assert (
        SimulatedPublicPackageClosure.restore_from_typed_sources(
            closure.to_dict(),
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=manifest,
            protected_references=references,
            expected_closure_hash=closure.closure_hash,
        )
        == closure
    )
    with pytest.raises(RawPackageClosureError, match="authority-bound closure"):
        SimulatedPublicPackageClosure.restore_from_typed_sources(
            closure.to_dict(),
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=manifest,
            protected_references=references,
            expected_closure_hash=_hash(85),
        )


def test_canonical_bytes_restore_rederives_typed_slice_in_fresh_process_shape() -> None:
    candidate, manifest, references = _sources()
    closure = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )
    raw = closure.to_canonical_bytes()

    restored = SimulatedPublicPackageClosure.restore_from_canonical_bytes(
        raw,
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
        expected_closure_hash=closure.closure_hash,
    )

    assert restored == closure
    assert restored.to_canonical_bytes() == raw


def test_canonical_bytes_restore_rejects_noncanonical_or_forged_payload() -> None:
    candidate, manifest, references = _sources()
    closure = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )
    raw = closure.to_canonical_bytes()

    with pytest.raises(RawPackageClosureError, match="canonical"):
        SimulatedPublicPackageClosure.restore_from_canonical_bytes(
            raw + b"\n",
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=manifest,
            protected_references=references,
            expected_closure_hash=closure.closure_hash,
        )

    duplicate = b'{"schema":"x","schema":"y"}'
    with pytest.raises(RawPackageClosureError, match="canonical"):
        SimulatedPublicPackageClosure.restore_from_canonical_bytes(
            duplicate,
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=manifest,
            protected_references=references,
            expected_closure_hash=closure.closure_hash,
        )

    forged = json.loads(raw)
    forged["fresh_replay_ready"] = True
    forged_raw = (
        json.dumps(forged, separators=(",", ":"), sort_keys=True).encode("utf-8")
        + b"\n"
    )
    with pytest.raises(RawPackageClosureError, match="source-derived"):
        SimulatedPublicPackageClosure.restore_from_canonical_bytes(
            forged_raw,
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=manifest,
            protected_references=references,
            expected_closure_hash=closure.closure_hash,
        )


def test_protected_reference_membership_must_exactly_match_vault_objects() -> None:
    candidate, manifest, references = _sources()
    for changed in (
        references[:-1],
        tuple(reversed(references)),
        (*references, references[-1]),
    ):
        with pytest.raises(RawPackageClosureError, match="protected.*membership"):
            SimulatedPublicPackageClosure.create_from_typed_sources(
                expected_package_id="pytest.meas0.package.v3",
                pilot_candidate=candidate,
                protected_vault_manifest=manifest,
                protected_references=changed,
            )


def test_cross_candidate_or_vault_substitution_fails_typed_ancestry() -> None:
    candidate, manifest, references = _sources()
    crossed_vault = SimulatedProtectedEvidenceVault.create(
        vault_id="crossed-vault",
        package_id="pytest.meas0.package.v3",
        common_ancestry_hash=_hash(86),
        acl_policy_hash=_hash(87),
        encryption_policy_hash=_hash(88),
        retention_policy_ref=_hash(89),
        legal_hold_ref=_hash(90),
    )
    crossed_ref = crossed_vault.write_once(
        object_id="crossed-object",
        payload=b"crossed",
        classification="test_data",
    )
    with pytest.raises(RawPackageClosureError, match="mixed ancestry"):
        SimulatedPublicPackageClosure.create_from_typed_sources(
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=crossed_vault.seal(),
            protected_references=(crossed_ref,),
        )

    foreign_vault = SimulatedProtectedEvidenceVault.create(
        vault_id="foreign-vault",
        package_id="pytest.foreign.package.v3",
        common_ancestry_hash=candidate.common_ancestry_hash,
        acl_policy_hash=_hash(92),
        encryption_policy_hash=_hash(93),
        retention_policy_ref=_hash(94),
        legal_hold_ref=_hash(95),
    )
    foreign_ref = foreign_vault.write_once(
        object_id="foreign-object",
        payload=b"foreign",
        classification="test_data",
    )
    foreign_manifest = foreign_vault.seal()
    with pytest.raises(RawPackageClosureError, match="package|membership"):
        SimulatedPublicPackageClosure.create_from_typed_sources(
            expected_package_id="pytest.meas0.package.v3",
            pilot_candidate=candidate,
            protected_vault_manifest=foreign_manifest,
            protected_references=(foreign_ref,),
        )


def test_raw_artifacts_are_not_a_public_closure_factory_surface() -> None:
    assert not hasattr(SimulatedPublicPackageClosure, "create")
    closure = _closure()
    assert {
        "raw_response_bytes",
        "raw_request_bytes",
        "protected_payload",
        "access_token",
        "secret",
    }.isdisjoint(str(closure.to_dict()))


def test_protected_object_ids_are_not_serialized_into_public_slice() -> None:
    candidate = _candidate()
    secret_object_id = "SUPER_SECRET_RAW_PAYLOAD_9c1f"
    vault = SimulatedProtectedEvidenceVault.create(
        vault_id="pytest-public-projection-vault",
        package_id="pytest.meas0.package.v3",
        common_ancestry_hash=candidate.common_ancestry_hash,
        acl_policy_hash=_hash(96),
        encryption_policy_hash=_hash(97),
        retention_policy_ref=_hash(98),
        legal_hold_ref=_hash(99),
    )
    reference = vault.write_once(
        object_id=secret_object_id,
        payload=b"protected bytes",
        classification="test_data",
    )

    closure = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=vault.seal(),
        protected_references=(reference,),
    )

    public_bytes = b"\n".join(item.raw_bytes for item in closure.artifacts)
    assert secret_object_id.encode() not in public_bytes
    assert b'"object_id"' not in public_bytes
    protected_files = {
        item.relative_path: json.loads(item.raw_bytes) for item in closure.artifacts
    }
    for path in (
        "protected/vault_manifest.json",
        "protected/vault_refs.json",
    ):
        projection = protected_files[path]
        assert "object_ids_public" not in projection
        assert projection["object_ids_serialized"] is False
        assert projection["object_id_hiding_verified"] is False
        assert (
            projection["object_id_hiding_gap"]
            == "deterministic_commitments_allow_low_entropy_dictionary_confirmation"
        )


def test_serialized_boolean_or_hash_upgrade_is_rederived_not_trusted() -> None:
    candidate, manifest, references = _sources()
    closure = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id="pytest.meas0.package.v3",
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )
    for field, value in (
        ("fresh_replay_ready", True),
        ("raw_package_closed", True),
        ("production_authorized", True),
        ("claim_scope", "formal_result"),
        ("closure_hash", _hash(91)),
    ):
        encoded = closure.to_dict()
        encoded[field] = value
        with pytest.raises(RawPackageClosureError, match="source-derived closure"):
            SimulatedPublicPackageClosure.restore_from_typed_sources(
                encoded,
                expected_package_id="pytest.meas0.package.v3",
                pilot_candidate=candidate,
                protected_vault_manifest=manifest,
                protected_references=references,
                expected_closure_hash=closure.closure_hash,
            )
