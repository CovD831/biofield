from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from biofield.meas0_pilot_run import prepare_pilot_run
from biofield.meas0_source_lock_v3 import (
    SealedSourceLockBytes,
    SourceLockBytesError,
)


DESIGN_DOCUMENT = (
    Path(__file__).parents[1] / "docs" / "experiments" / "MEAS0_DESIGN_V1.md"
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _lock_bytes(tmp_path: Path) -> bytes:
    path = prepare_pilot_run(
        lock_directory=tmp_path / "locks",
        lock_id="source-lock-v3",
        design_document=DESIGN_DOCUMENT,
    )
    return path.read_bytes()


def test_exact_existing_v2_lock_bytes_are_typed_without_source_restoration(
    tmp_path: Path,
) -> None:
    raw = _lock_bytes(tmp_path)
    digest = hashlib.sha256(raw).hexdigest()

    lock = SealedSourceLockBytes.from_canonical_bytes(
        raw,
        expected_sha256=digest,
    )

    assert lock.raw_bytes == raw
    assert lock.source_lock_hash == digest
    assert len(lock.source_entries) == 29
    assert tuple(item.name for item in lock.source_entries) == tuple(
        sorted(item.name for item in lock.source_entries)
    )
    assert lock.claim_scope == "simulated_nonclaim"
    assert lock.source_restoration_authorized is False
    assert lock.production_authorized is False
    assert lock.test_only is True


def test_lock_rejects_unknown_missing_noncanonical_and_hash_mismatch(
    tmp_path: Path,
) -> None:
    raw = _lock_bytes(tmp_path)
    value = json.loads(raw)

    with pytest.raises(SourceLockBytesError, match="hash"):
        SealedSourceLockBytes.from_canonical_bytes(
            raw,
            expected_sha256="f" * 64,
        )

    with pytest.raises(SourceLockBytesError, match="canonical"):
        SealedSourceLockBytes.from_canonical_bytes(
            json.dumps(value, indent=2).encode(),
            expected_sha256=hashlib.sha256(
                json.dumps(value, indent=2).encode()
            ).hexdigest(),
        )

    unknown = {**value, "self_consistent_extension": "allowed?"}
    unknown_raw = _canonical_bytes(unknown)
    with pytest.raises(SourceLockBytesError, match="fields"):
        SealedSourceLockBytes.from_canonical_bytes(
            unknown_raw,
            expected_sha256=hashlib.sha256(unknown_raw).hexdigest(),
        )

    missing = dict(value)
    missing.pop("source_hashes")
    missing_raw = _canonical_bytes(missing)
    with pytest.raises(SourceLockBytesError, match="fields"):
        SealedSourceLockBytes.from_canonical_bytes(
            missing_raw,
            expected_sha256=hashlib.sha256(missing_raw).hexdigest(),
        )


def test_lock_rejects_source_membership_substitution_even_when_rehashed(
    tmp_path: Path,
) -> None:
    value = json.loads(_lock_bytes(tmp_path))
    source_hashes = dict(value["source_hashes"])
    source_hashes["unapproved.py"] = source_hashes.pop("resources.py")
    drifted = _canonical_bytes({**value, "source_hashes": source_hashes})

    with pytest.raises(SourceLockBytesError, match="source entries"):
        SealedSourceLockBytes.from_canonical_bytes(
            drifted,
            expected_sha256=hashlib.sha256(drifted).hexdigest(),
        )


def test_lock_is_factory_only(tmp_path: Path) -> None:
    lock = SealedSourceLockBytes.from_canonical_bytes(
        (raw := _lock_bytes(tmp_path)),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )

    with pytest.raises(SourceLockBytesError, match="canonical bytes"):
        SealedSourceLockBytes(
            raw_bytes=lock.raw_bytes,
            source_lock_hash=lock.source_lock_hash,
            source_entries=lock.source_entries,
            claim_scope=lock.claim_scope,
            source_restoration_authorized=lock.source_restoration_authorized,
            production_authorized=lock.production_authorized,
            test_only=lock.test_only,
        )
