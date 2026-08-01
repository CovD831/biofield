from __future__ import annotations

import json

import pytest

from biofield.meas0_protected_raw_bundle_v3 import (
    ProtectedRawBundleError,
    SimulatedProtectedRawBundleV3,
)
from biofield.meas0_protected_vault import SimulatedProtectedEvidenceVault
from test_meas0_pilot_plan_v3 import _candidate, _hash


def _sources():
    candidate = _candidate()
    vault = SimulatedProtectedEvidenceVault.create(
        vault_id="pytest-protected-raw-vault",
        package_id="pytest.meas0.package.v3",
        common_ancestry_hash=candidate.common_ancestry_hash,
        acl_policy_hash=_hash(121),
        encryption_policy_hash=_hash(122),
        retention_policy_ref=_hash(123),
        legal_hold_ref=_hash(124),
    )
    refs = (
        vault.write_once(
            object_id="protected-input",
            payload=b"protected input bytes",
            classification="test_data",
        ),
        vault.write_once(
            object_id="protected-judge",
            payload=b"protected judge bytes",
            classification="test_data",
        ),
    )
    return candidate, vault.seal(), refs


def _bundle():
    candidate, manifest, refs = _sources()
    bundle = SimulatedProtectedRawBundleV3.create_from_typed_sources(
        expected_package_id=manifest.package_id,
        common_ancestry_hash=candidate.common_ancestry_hash,
        protected_vault_manifest=manifest,
        protected_references=refs,
        payloads={
            "protected-input": b"protected input bytes",
            "protected-judge": b"protected judge bytes",
        },
    )
    return bundle, manifest, refs


def test_protected_raw_bundle_binds_exact_payload_membership_without_replay_upgrade():
    bundle, manifest, refs = _bundle()

    assert bundle.package_id == manifest.package_id
    assert bundle.vault_id == manifest.vault_id
    assert tuple(item.object_id for item in bundle.entries) == tuple(
        item.object_id for item in refs
    )
    assert bundle.payload_membership_closed is True
    assert bundle.fresh_replay_ready is False
    assert bundle.claim_scope == "simulated_nonclaim"
    assert bundle.test_only is True
    assert bundle.production_authorized is False
    assert bundle.vault_manifest_hash == manifest.contract_hash
    assert bundle.reference_index_hash == bundle._reference_index_hash(refs)


def test_protected_raw_bundle_rejects_manifest_or_reference_index_substitution():
    bundle, manifest, refs = _bundle()
    candidate, _, _ = _sources()
    forged = bundle.to_dict()
    forged["vault_manifest_hash"] = _hash(126)
    with pytest.raises(ProtectedRawBundleError, match="source-derived"):
        SimulatedProtectedRawBundleV3.restore_from_typed_sources(
            forged,
            expected_package_id=manifest.package_id,
            common_ancestry_hash=candidate.common_ancestry_hash,
            protected_vault_manifest=manifest,
            protected_references=refs,
            payloads={
                "protected-input": b"protected input bytes",
                "protected-judge": b"protected judge bytes",
            },
            expected_bundle_hash=bundle.bundle_hash,
        )


def test_protected_raw_bundle_canonical_bytes_restore_rederives_in_fresh_process_shape():
    bundle, manifest, refs = _bundle()
    candidate, _, _ = _sources()
    raw = bundle.to_canonical_bytes()

    restored = SimulatedProtectedRawBundleV3.restore_from_canonical_bytes(
        raw,
        expected_package_id=manifest.package_id,
        common_ancestry_hash=candidate.common_ancestry_hash,
        protected_vault_manifest=manifest,
        protected_references=refs,
        expected_bundle_hash=bundle.bundle_hash,
    )

    assert restored == bundle
    assert restored.to_canonical_bytes() == raw


def test_protected_raw_bundle_typed_restore_rederives_payload_and_external_binding():
    bundle, manifest, refs = _bundle()
    candidate, _, _ = _sources()

    restored = SimulatedProtectedRawBundleV3.restore_from_typed_sources(
        bundle.to_dict(),
        expected_package_id=manifest.package_id,
        common_ancestry_hash=candidate.common_ancestry_hash,
        protected_vault_manifest=manifest,
        protected_references=refs,
        payloads={
            "protected-input": b"protected input bytes",
            "protected-judge": b"protected judge bytes",
        },
        expected_bundle_hash=bundle.bundle_hash,
    )
    assert restored == bundle

    with pytest.raises(ProtectedRawBundleError, match="authority-bound"):
        SimulatedProtectedRawBundleV3.restore_from_typed_sources(
            bundle.to_dict(),
            expected_package_id=manifest.package_id,
            common_ancestry_hash=candidate.common_ancestry_hash,
            protected_vault_manifest=manifest,
            protected_references=refs,
            payloads={
                "protected-input": b"protected input bytes",
                "protected-judge": b"protected judge bytes",
            },
            expected_bundle_hash=_hash(125),
        )


def test_protected_raw_bundle_rejects_noncanonical_or_forged_payloads():
    bundle, manifest, refs = _bundle()
    candidate, _, _ = _sources()
    raw = bundle.to_canonical_bytes()

    with pytest.raises(ProtectedRawBundleError, match="canonical"):
        SimulatedProtectedRawBundleV3.restore_from_canonical_bytes(
            raw + b"\n",
            expected_package_id=manifest.package_id,
            common_ancestry_hash=candidate.common_ancestry_hash,
            protected_vault_manifest=manifest,
            protected_references=refs,
            expected_bundle_hash=bundle.bundle_hash,
        )

    forged = json.loads(raw)
    forged["fresh_replay_ready"] = True
    forged_raw = json.dumps(forged, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(ProtectedRawBundleError, match="source-derived"):
        SimulatedProtectedRawBundleV3.restore_from_canonical_bytes(
            forged_raw,
            expected_package_id=manifest.package_id,
            common_ancestry_hash=candidate.common_ancestry_hash,
            protected_vault_manifest=manifest,
            protected_references=refs,
            expected_bundle_hash=bundle.bundle_hash,
        )


def test_protected_raw_bundle_requires_exact_payload_keys_and_hashes():
    candidate, manifest, refs = _sources()
    common = {
        "expected_package_id": manifest.package_id,
        "common_ancestry_hash": candidate.common_ancestry_hash,
        "protected_vault_manifest": manifest,
        "protected_references": refs,
    }
    with pytest.raises(ProtectedRawBundleError, match="payload membership"):
        SimulatedProtectedRawBundleV3.create_from_typed_sources(
            **common,
            payloads={"protected-input": b"protected input bytes"},
        )
    with pytest.raises(ProtectedRawBundleError, match="payload membership"):
        SimulatedProtectedRawBundleV3.create_from_typed_sources(
            **common,
            payloads={
                "protected-input": b"protected input bytes",
                "protected-judge": b"protected judge bytes",
                "unexpected": b"unexpected",
            },
        )
    with pytest.raises(ProtectedRawBundleError, match="hash|byte count"):
        SimulatedProtectedRawBundleV3.create_from_typed_sources(
            **common,
            payloads={
                "protected-input": b"tampered",
                "protected-judge": b"protected judge bytes",
            },
        )
