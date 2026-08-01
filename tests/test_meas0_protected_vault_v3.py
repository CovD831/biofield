from __future__ import annotations

from dataclasses import fields, replace

import pytest

from biofield.meas0_protected_vault import (
    ProtectedEvidenceReference,
    ProtectedEvidenceReadbackReceipt,
    ProtectedVaultError,
    ProtectedVaultManifest,
    ProtectedVaultObject,
    SimulatedProtectedEvidenceVault,
)


def _hash(character: str) -> str:
    return character * 64


def _vault(
    *,
    vault_id: str = "pytest-protected-vault",
    package_id: str = "pytest.meas0.package.v3",
    ancestry: str = _hash("a"),
) -> SimulatedProtectedEvidenceVault:
    return SimulatedProtectedEvidenceVault.create(
        vault_id=vault_id,
        package_id=package_id,
        common_ancestry_hash=ancestry,
        acl_policy_hash=_hash("b"),
        encryption_policy_hash=_hash("c"),
        retention_policy_ref=_hash("d"),
        legal_hold_ref=_hash("e"),
    )


def test_public_reference_and_object_expose_metadata_not_location_or_bytes() -> None:
    vault = _vault()
    reference = vault.write_once(
        object_id="judge-transcript-0001",
        payload=b"exact\x00test\xffbytes",
        classification="test_data",
    )
    manifest = vault.seal()
    item = manifest.objects[0]

    assert isinstance(reference, ProtectedEvidenceReference)
    assert isinstance(item, ProtectedVaultObject)
    assert item.object_hash == reference.object_hash
    assert item.byte_count == len(b"exact\x00test\xffbytes")
    assert item.classification == "test_data"
    assert item.encryption_state == "simulated_not_encrypted"
    assert reference.claim_scope == "simulated_nonclaim"
    assert reference.test_only is True
    forbidden = {"path", "uri", "url", "payload", "bytes", "raw_bytes"}
    assert forbidden.isdisjoint(field.name for field in fields(reference))
    assert forbidden.isdisjoint(field.name for field in fields(item))
    encoded = {
        "reference": reference.to_dict(),
        "object": item.to_dict(),
        "manifest": manifest.to_dict(),
        "receipt": vault.readback(reference).to_dict(),
    }

    def encoded_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(encoded_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(encoded_keys(item) for item in value))
        return set()

    assert forbidden.isdisjoint(encoded_keys(encoded))


def test_manifest_has_exact_ordered_membership_and_strict_canonical_codec() -> None:
    vault = _vault()
    first = vault.write_once(
        object_id="first-object",
        payload=b"first",
        classification="test_data",
    )
    second = vault.write_once(
        object_id="second-object",
        payload=b"second",
        classification="test_data",
    )
    manifest = vault.seal()

    assert tuple(item.object_id for item in manifest.objects) == (
        first.object_id,
        second.object_id,
    )
    assert manifest.acl_policy_hash == _hash("b")
    assert manifest.encryption_policy_hash == _hash("c")
    assert manifest.retention_policy_ref == _hash("d")
    assert manifest.legal_hold_ref == _hash("e")
    assert manifest.package_id == "pytest.meas0.package.v3"
    assert manifest.common_ancestry_hash == _hash("a")
    assert ProtectedVaultManifest.from_dict(manifest.to_dict()) == manifest

    swapped = manifest.to_dict()
    swapped["objects"] = list(reversed(swapped["objects"]))
    with pytest.raises(ProtectedVaultError, match="contract hash"):
        ProtectedVaultManifest.from_dict(swapped)
    tampered = manifest.to_dict()
    tampered["objects"][0]["byte_count"] += 1
    with pytest.raises(ProtectedVaultError, match="hash|byte count|contract"):
        ProtectedVaultManifest.from_dict(tampered)


def test_write_once_readback_receipt_binds_exact_bytes_and_reference() -> None:
    vault = _vault()
    payload = b"\x00canonical bytes are not text\xfe"
    reference = vault.write_once(
        object_id="oracle-record-0001",
        payload=payload,
        classification="test_data",
    )
    receipt = vault.readback(reference)

    assert receipt.reference_hash == reference.reference_hash
    assert receipt.observed_object_hash == reference.object_hash
    assert receipt.observed_byte_count == len(payload)
    assert receipt.exact_match is True
    assert receipt.claim_scope == "simulated_nonclaim"
    assert receipt.test_only is True
    assert receipt.production_authorized is False
    assert ProtectedEvidenceReadbackReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(ProtectedVaultError, match="write-once"):
        vault.write_once(
            object_id=reference.object_id,
            payload=b"different",
            classification="test_data",
        )
    vault.seal()
    with pytest.raises(ProtectedVaultError, match="sealed"):
        vault.write_once(
            object_id="late-object",
            payload=b"late",
            classification="test_data",
        )


def test_missing_cross_vault_swap_and_tampered_reference_fail_closed() -> None:
    first_vault = _vault(vault_id="first-vault")
    reference = first_vault.write_once(
        object_id="shared-name",
        payload=b"first payload",
        classification="test_data",
    )
    second_vault = _vault(vault_id="second-vault")
    swapped = second_vault.write_once(
        object_id="shared-name",
        payload=b"second payload",
        classification="test_data",
    )

    with pytest.raises(ProtectedVaultError, match="vault binding"):
        first_vault.readback(swapped)
    with pytest.raises(ProtectedVaultError, match="vault binding"):
        second_vault.readback(reference)
    parallel_same_binding = _vault(vault_id="first-vault")
    missing = parallel_same_binding.write_once(
        object_id="missing-object",
        payload=b"not present in first vault",
        classification="test_data",
    )
    with pytest.raises(ProtectedVaultError, match="missing"):
        first_vault.readback(missing)
    with pytest.raises(ProtectedVaultError, match="object hash"):
        replace(reference, object_hash=_hash("f"))


@pytest.mark.parametrize(
    "object_id",
    (
        ".",
        "..",
        "../secret",
        "folder/object",
        r"folder\object",
        "/absolute",
        "file:secret",
        "link->secret",
    ),
)
def test_path_and_symlink_like_object_ids_are_rejected(object_id: str) -> None:
    with pytest.raises(ProtectedVaultError, match="opaque object ID"):
        _vault().write_once(
            object_id=object_id,
            payload=b"test",
            classification="test_data",
        )


@pytest.mark.parametrize(
    "package_id",
    (
        "..",
        "../package",
        "parent/child",
        r"parent\child",
        "/absolute/package",
        "file:///private/package",
        "https://example.test/package",
        "scheme:package",
        "package..backup",
    ),
)
def test_path_and_uri_like_package_ids_fail_at_all_public_boundaries(
    package_id: str,
) -> None:
    with pytest.raises(ProtectedVaultError, match="opaque package ID"):
        _vault(package_id=package_id)

    vault = _vault()
    reference = vault.write_once(
        object_id="safe-object",
        payload=b"safe",
        classification="test_data",
    )
    manifest = vault.seal()
    encoded_reference = reference.to_dict()
    encoded_reference["package_id"] = package_id
    with pytest.raises(ProtectedVaultError, match="opaque package ID"):
        ProtectedEvidenceReference.from_dict(encoded_reference)
    encoded_manifest = manifest.to_dict()
    encoded_manifest["package_id"] = package_id
    with pytest.raises(ProtectedVaultError, match="opaque package ID"):
        ProtectedVaultManifest.from_dict(encoded_manifest)


def test_vault_rejects_non_test_data_and_direct_public_artifact_construction() -> None:
    vault = _vault()
    with pytest.raises(ProtectedVaultError, match="test data"):
        vault.write_once(
            object_id="production-evidence",
            payload=b"must not enter simulated vault",
            classification="production",
        )
    with pytest.raises(ProtectedVaultError, match="factory"):
        ProtectedEvidenceReference(
            schema="meas0.protected-evidence-reference",
            version=3,
            vault_id="forged",
            package_id="pytest.meas0.package.v3",
            common_ancestry_hash=_hash("a"),
            object_id="forged-object",
            object_hash=_hash("b"),
            byte_count=1,
            classification="test_data",
            encryption_state="simulated_not_encrypted",
        )
