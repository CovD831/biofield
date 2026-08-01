from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_protected_artifacts import (
    ProtectedArtifactContractError,
    ProtectedArtifactIntegrityError,
    ProtectedRawArtifactStore,
    RawArtifactHandlingManifest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SOURCE_EVIDENCE_HASH = "d" * 64
REQUEST_FINGERPRINT = "e" * 64


def _manifest(
    *,
    store_id: str = "judge-raw-store",
) -> RawArtifactHandlingManifest:
    return RawArtifactHandlingManifest(
        manifest_id="judge-raw-handling-v1",
        store_id=store_id,
        media_type="application/json",
        acl_manifest_hash=SHA_A,
        observed_preflight_hash=SHA_B,
        retention_manifest_hash=SHA_C,
        public_export_forbidden=True,
        resolved_path_disclosure_forbidden=True,
    )


def _seal(
    store: ProtectedRawArtifactStore,
    *,
    artifact_id: str,
    raw: bytes,
    handling_manifest: RawArtifactHandlingManifest,
):
    return store.seal(
        artifact_id=artifact_id,
        raw=raw,
        handling_manifest=handling_manifest,
        source_evidence_hash=SOURCE_EVIDENCE_HASH,
        request_fingerprint=REQUEST_FINGERPRINT,
    )


def test_store_seals_write_once_raw_with_private_modes_and_public_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    raw = b'{"reasoning_content":"private-canary","id":"response-1"}'

    receipt = _seal(
        store,
        artifact_id="judge-response-0001",
        raw=raw,
        handling_manifest=_manifest(),
    )

    artifact = root / receipt.artifact_id
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert (
        store.verify_readback(
            receipt=receipt,
            handling_manifest=_manifest(),
        )
        == receipt
    )
    assert receipt.byte_length == len(raw)
    assert len(receipt.raw_sha256) == 64
    assert receipt.handling_manifest_hash == _manifest().contract_hash

    public = receipt.to_dict()
    assert set(public) == {
        "artifact_id",
        "store_id",
        "raw_sha256",
        "byte_length",
        "media_type",
        "acl_manifest_hash",
        "observed_preflight_hash",
        "retention_manifest_hash",
        "handling_manifest_hash",
        "source_evidence_hash",
        "request_fingerprint",
    }
    serialized = json.dumps(public, sort_keys=True)
    assert "private-canary" not in serialized
    assert "raw_response" not in serialized
    assert str(root) not in serialized
    assert "resolved_path" not in serialized


def test_store_fsyncs_artifact_then_root_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    real_fsync = os.fsync
    fsync_targets: list[str] = []

    def recording_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        fsync_targets.append(
            "directory" if stat.S_ISDIR(metadata.st_mode) else "artifact"
        )
        real_fsync(descriptor)

    monkeypatch.setattr(
        "biofield.meas0_protected_artifacts.os.fsync",
        recording_fsync,
    )

    _seal(
        store,
        artifact_id="judge-response-0001",
        raw=b'{"id":"response-1"}',
        handling_manifest=_manifest(),
    )

    assert fsync_targets == ["artifact", "directory"]


@pytest.mark.parametrize(
    "artifact_id",
    (
        "",
        ".",
        "..",
        "../escape",
        "nested/artifact",
        r"nested\artifact",
        "/absolute/artifact",
        "white space",
    ),
)
def test_store_rejects_nonopaque_or_multisegment_artifact_ids(
    tmp_path: Path,
    artifact_id: str,
) -> None:
    store = ProtectedRawArtifactStore(
        root=tmp_path / "protected",
        store_id="judge-raw-store",
    )

    with pytest.raises(ProtectedArtifactContractError, match="artifact_id"):
        _seal(
            store,
            artifact_id=artifact_id,
            raw=b"private",
            handling_manifest=_manifest(),
        )


def test_store_rejects_symlinked_parent_or_root(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlink_parent = tmp_path / "linked-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ProtectedArtifactIntegrityError, match="symlink"):
        ProtectedRawArtifactStore(
            root=symlink_parent / "protected",
            store_id="judge-raw-store",
        )

    real_root = tmp_path / "real-root"
    real_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ProtectedArtifactIntegrityError, match="symlink"):
        ProtectedRawArtifactStore(
            root=linked_root,
            store_id="judge-raw-store",
        )


def test_store_rejects_root_identity_replacement_after_initialization(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    displaced_parent = tmp_path / "displaced-parent"
    parent.rename(displaced_parent)
    parent.mkdir()
    root.mkdir(mode=0o700)

    with pytest.raises(ProtectedArtifactIntegrityError, match="identity"):
        _seal(
            store,
            artifact_id="judge-response-0001",
            raw=b"private",
            handling_manifest=_manifest(),
        )
    assert not (root / "judge-response-0001").exists()


def test_store_rejects_target_symlink_and_existing_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    (root / "linked-artifact").symlink_to(outside)

    with pytest.raises(ProtectedArtifactIntegrityError, match="symlink"):
        _seal(
            store,
            artifact_id="linked-artifact",
            raw=b"private",
            handling_manifest=_manifest(),
        )
    assert outside.read_bytes() == b"outside"

    _seal(
        store,
        artifact_id="judge-response-0001",
        raw=b"first",
        handling_manifest=_manifest(),
    )
    with pytest.raises(ProtectedArtifactIntegrityError, match="exists"):
        _seal(
            store,
            artifact_id="judge-response-0001",
            raw=b"second",
            handling_manifest=_manifest(),
        )
    assert (root / "judge-response-0001").read_bytes() == b"first"


def test_verify_readback_detects_content_size_mode_and_link_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    manifest = _manifest()

    content_receipt = _seal(
        store,
        artifact_id="content-tamper",
        raw=b"original",
        handling_manifest=manifest,
    )
    (root / content_receipt.artifact_id).write_bytes(b"tampered")
    with pytest.raises(ProtectedArtifactIntegrityError, match="hash"):
        store.verify_readback(
            receipt=content_receipt,
            handling_manifest=manifest,
        )

    size_receipt = _seal(
        store,
        artifact_id="size-tamper",
        raw=b"original",
        handling_manifest=manifest,
    )
    (root / size_receipt.artifact_id).write_bytes(b"short")
    with pytest.raises(ProtectedArtifactIntegrityError, match="size"):
        store.verify_readback(
            receipt=size_receipt,
            handling_manifest=manifest,
        )

    mode_receipt = _seal(
        store,
        artifact_id="mode-tamper",
        raw=b"original",
        handling_manifest=manifest,
    )
    (root / mode_receipt.artifact_id).chmod(0o644)
    with pytest.raises(ProtectedArtifactIntegrityError, match="0600"):
        store.verify_readback(
            receipt=mode_receipt,
            handling_manifest=manifest,
        )

    link_receipt = _seal(
        store,
        artifact_id="link-tamper",
        raw=b"original",
        handling_manifest=manifest,
    )
    os.link(
        root / link_receipt.artifact_id,
        root / "second-hardlink",
    )
    with pytest.raises(ProtectedArtifactIntegrityError, match="link count"):
        store.verify_readback(
            receipt=link_receipt,
            handling_manifest=manifest,
        )


def test_verify_readback_rejects_root_mode_and_manifest_substitution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    store = ProtectedRawArtifactStore(
        root=root,
        store_id="judge-raw-store",
    )
    manifest = _manifest()
    receipt = _seal(
        store,
        artifact_id="judge-response-0001",
        raw=b"original",
        handling_manifest=manifest,
    )

    with pytest.raises(ProtectedArtifactContractError, match="manifest"):
        store.verify_readback(
            receipt=receipt,
            handling_manifest=replace(
                manifest,
                retention_manifest_hash="d" * 64,
            ),
        )

    root.chmod(0o755)
    with pytest.raises(ProtectedArtifactIntegrityError, match="0700"):
        store.verify_readback(
            receipt=receipt,
            handling_manifest=manifest,
        )


def test_handling_manifest_is_strict_and_store_bound() -> None:
    manifest = _manifest()

    assert manifest.contract_hash
    assert manifest.to_dict()["public_export_forbidden"] is True
    assert manifest.to_dict()["resolved_path_disclosure_forbidden"] is True

    with pytest.raises(ProtectedArtifactContractError, match="public export"):
        replace(manifest, public_export_forbidden=False)
    with pytest.raises(ProtectedArtifactContractError, match="resolved path"):
        replace(manifest, resolved_path_disclosure_forbidden=False)
    with pytest.raises(ProtectedArtifactContractError, match="SHA-256"):
        replace(manifest, acl_manifest_hash="not-a-hash")
