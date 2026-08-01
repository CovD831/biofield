"""Offline, write-once storage for protected MEAS0 raw Judge artifacts.

The public receipt deliberately contains no raw bytes or resolved filesystem
path.  This module provides local integrity and handling-policy binding only;
it does not establish a production trust root or transport authenticity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProtectedArtifactContractError(ValueError):
    """A protected-artifact contract is malformed or inconsistent."""


class ProtectedArtifactIntegrityError(ProtectedArtifactContractError):
    """Protected storage does not match its sealed integrity contract."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _opaque_id(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not _OPAQUE_ID.fullmatch(value)
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ProtectedArtifactContractError(
            f"{label} must be a safe single-segment opaque identifier"
        )
    return value


def _sha256_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProtectedArtifactContractError(f"{label} must be a lowercase SHA-256")
    return value


def _media_type(value: object) -> str:
    if not isinstance(value, str) or not _MEDIA_TYPE.fullmatch(value):
        raise ProtectedArtifactContractError(
            "media_type must be a concrete MIME media type"
        )
    return value


def _normalized_absolute_root(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ProtectedArtifactContractError("protected artifact root must be absolute")
    if "\0" in str(path) or os.path.abspath(path) != str(path):
        raise ProtectedArtifactContractError(
            "protected artifact root must be normalized"
        )
    if path == Path(path.anchor):
        raise ProtectedArtifactContractError(
            "protected artifact root cannot be a filesystem root"
        )
    return path


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ProtectedArtifactIntegrityError(
                "cannot inspect protected artifact root ancestry"
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ProtectedArtifactIntegrityError(
                "protected artifact root ancestry cannot contain a symlink"
            )


@dataclass(frozen=True, kw_only=True)
class RawArtifactHandlingManifest:
    """Hash-bound policy references for one protected raw-artifact store."""

    manifest_id: str
    store_id: str
    media_type: str
    acl_manifest_hash: str
    observed_preflight_hash: str
    retention_manifest_hash: str
    public_export_forbidden: bool
    resolved_path_disclosure_forbidden: bool

    def __post_init__(self) -> None:
        _opaque_id(self.manifest_id, "manifest_id")
        _opaque_id(self.store_id, "store_id")
        _media_type(self.media_type)
        _sha256_text(self.acl_manifest_hash, "acl_manifest_hash")
        _sha256_text(
            self.observed_preflight_hash,
            "observed_preflight_hash",
        )
        _sha256_text(
            self.retention_manifest_hash,
            "retention_manifest_hash",
        )
        if self.public_export_forbidden is not True:
            raise ProtectedArtifactContractError(
                "protected raw artifact manifest must forbid public export"
            )
        if self.resolved_path_disclosure_forbidden is not True:
            raise ProtectedArtifactContractError(
                "protected raw artifact manifest must forbid resolved path disclosure"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "store_id": self.store_id,
            "media_type": self.media_type,
            "acl_manifest_hash": self.acl_manifest_hash,
            "observed_preflight_hash": self.observed_preflight_hash,
            "retention_manifest_hash": self.retention_manifest_hash,
            "public_export_forbidden": self.public_export_forbidden,
            "resolved_path_disclosure_forbidden": (
                self.resolved_path_disclosure_forbidden
            ),
        }

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True, kw_only=True)
class ProtectedRawArtifactReceipt:
    """Public, path-free receipt for protected raw bytes."""

    artifact_id: str
    store_id: str
    raw_sha256: str
    byte_length: int
    media_type: str
    acl_manifest_hash: str
    observed_preflight_hash: str
    retention_manifest_hash: str
    handling_manifest_hash: str
    source_evidence_hash: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        _opaque_id(self.artifact_id, "artifact_id")
        _opaque_id(self.store_id, "store_id")
        _sha256_text(self.raw_sha256, "raw_sha256")
        if (
            isinstance(self.byte_length, bool)
            or not isinstance(self.byte_length, int)
            or self.byte_length <= 0
        ):
            raise ProtectedArtifactContractError(
                "byte_length must be a positive integer"
            )
        _media_type(self.media_type)
        _sha256_text(self.acl_manifest_hash, "acl_manifest_hash")
        _sha256_text(
            self.observed_preflight_hash,
            "observed_preflight_hash",
        )
        _sha256_text(
            self.retention_manifest_hash,
            "retention_manifest_hash",
        )
        _sha256_text(
            self.handling_manifest_hash,
            "handling_manifest_hash",
        )
        _sha256_text(
            self.source_evidence_hash,
            "source_evidence_hash",
        )
        _sha256_text(
            self.request_fingerprint,
            "request_fingerprint",
        )

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "store_id": self.store_id,
            "raw_sha256": self.raw_sha256,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "acl_manifest_hash": self.acl_manifest_hash,
            "observed_preflight_hash": self.observed_preflight_hash,
            "retention_manifest_hash": self.retention_manifest_hash,
            "handling_manifest_hash": self.handling_manifest_hash,
            "source_evidence_hash": self.source_evidence_hash,
            "request_fingerprint": self.request_fingerprint,
        }


class ProtectedRawArtifactStore:
    """POSIX protected store with write-once, readback-verified artifacts."""

    def __init__(
        self,
        *,
        root: Path | str,
        store_id: str,
    ) -> None:
        self._root = _normalized_absolute_root(root)
        self.store_id = _opaque_id(store_id, "store_id")
        self._root_identity: tuple[int, int] | None = None
        self._initialize_root()

    @staticmethod
    def _required_flag(name: str) -> int:
        value = getattr(os, name, None)
        if not isinstance(value, int):
            raise ProtectedArtifactIntegrityError(
                f"protected artifact store requires {name}"
            )
        return value

    def _initialize_root(self) -> None:
        descriptor = self._open_root_path(create=True)
        try:
            metadata = self._validate_root_descriptor(descriptor)
            self._root_identity = (metadata.st_dev, metadata.st_ino)
        finally:
            os.close(descriptor)

    def _open_root_path(self, *, create: bool) -> int:
        flags = (
            os.O_RDONLY
            | self._required_flag("O_DIRECTORY")
            | self._required_flag("O_NOFOLLOW")
        )
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self._root.anchor, flags)
        except OSError as error:
            raise ProtectedArtifactIntegrityError(
                "cannot securely open protected artifact root anchor"
            ) from error
        try:
            for index, part in enumerate(self._root.parts[1:]):
                final = index == len(self._root.parts[1:]) - 1
                try:
                    child_descriptor = os.open(
                        part,
                        flags,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not (create and final):
                        raise ProtectedArtifactIntegrityError(
                            "protected artifact root is missing"
                        ) from None
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                        child_descriptor = os.open(
                            part,
                            flags,
                            dir_fd=descriptor,
                        )
                    except OSError as error:
                        raise ProtectedArtifactIntegrityError(
                            "cannot securely create protected artifact root"
                        ) from error
                except OSError as error:
                    raise ProtectedArtifactIntegrityError(
                        "protected artifact root ancestry cannot contain "
                        "a symlink or non-directory"
                    ) from error
                os.close(descriptor)
                descriptor = child_descriptor
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    def _validate_root_descriptor(
        self,
        descriptor: int,
    ) -> os.stat_result:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ProtectedArtifactIntegrityError(
                "protected artifact root must remain a directory"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ProtectedArtifactIntegrityError(
                "protected artifact root mode must be 0700"
            )
        if metadata.st_uid != os.geteuid():
            raise ProtectedArtifactIntegrityError(
                "protected artifact root must be owned by the effective user"
            )
        return metadata

    def _open_root(self) -> int:
        descriptor = self._open_root_path(create=False)
        try:
            metadata = self._validate_root_descriptor(descriptor)
            if (
                self._root_identity is None
                or (metadata.st_dev, metadata.st_ino) != self._root_identity
            ):
                raise ProtectedArtifactIntegrityError(
                    "protected artifact root identity changed"
                )
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    def _validate_manifest(
        self,
        manifest: RawArtifactHandlingManifest,
    ) -> None:
        if not isinstance(manifest, RawArtifactHandlingManifest):
            raise ProtectedArtifactContractError(
                "raw artifact handling manifest is required"
            )
        if manifest.store_id != self.store_id:
            raise ProtectedArtifactContractError(
                "raw artifact handling manifest is bound to another store"
            )

    @staticmethod
    def _check_manifest_receipt_binding(
        *,
        receipt: ProtectedRawArtifactReceipt,
        manifest: RawArtifactHandlingManifest,
    ) -> None:
        if (
            receipt.store_id != manifest.store_id
            or receipt.media_type != manifest.media_type
            or receipt.acl_manifest_hash != manifest.acl_manifest_hash
            or receipt.observed_preflight_hash != manifest.observed_preflight_hash
            or receipt.retention_manifest_hash != manifest.retention_manifest_hash
            or receipt.handling_manifest_hash != manifest.contract_hash
        ):
            raise ProtectedArtifactContractError(
                "protected raw artifact receipt/manifest binding mismatch"
            )

    @staticmethod
    def _existing_target(
        *,
        root_descriptor: int,
        artifact_id: str,
    ) -> os.stat_result | None:
        try:
            return os.stat(
                artifact_id,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ProtectedArtifactIntegrityError(
                "cannot inspect protected artifact target"
            ) from error

    @staticmethod
    def _write_all(descriptor: int, raw: bytes) -> None:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise ProtectedArtifactIntegrityError(
                    "protected artifact write made no progress"
                )
            remaining = remaining[written:]

    @staticmethod
    def _read_all(descriptor: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _validate_artifact_metadata(
        metadata: os.stat_result,
        *,
        expected_size: int,
    ) -> None:
        if not stat.S_ISREG(metadata.st_mode):
            raise ProtectedArtifactIntegrityError(
                "protected artifact must be a regular file"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ProtectedArtifactIntegrityError(
                "protected artifact mode must be 0600"
            )
        if metadata.st_nlink != 1:
            raise ProtectedArtifactIntegrityError(
                "protected artifact link count must equal 1"
            )
        if metadata.st_size != expected_size:
            raise ProtectedArtifactIntegrityError(
                "protected artifact size does not match receipt"
            )

    def seal(
        self,
        *,
        artifact_id: str,
        raw: bytes,
        handling_manifest: RawArtifactHandlingManifest,
        source_evidence_hash: str,
        request_fingerprint: str,
    ) -> ProtectedRawArtifactReceipt:
        artifact_id = _opaque_id(artifact_id, "artifact_id")
        if not isinstance(raw, bytes) or not raw:
            raise ProtectedArtifactContractError(
                "protected raw artifact must be non-empty bytes"
            )
        self._validate_manifest(handling_manifest)
        source_evidence_hash = _sha256_text(
            source_evidence_hash,
            "source_evidence_hash",
        )
        request_fingerprint = _sha256_text(
            request_fingerprint,
            "request_fingerprint",
        )
        receipt = ProtectedRawArtifactReceipt(
            artifact_id=artifact_id,
            store_id=self.store_id,
            raw_sha256=_sha256(raw),
            byte_length=len(raw),
            media_type=handling_manifest.media_type,
            acl_manifest_hash=handling_manifest.acl_manifest_hash,
            observed_preflight_hash=(handling_manifest.observed_preflight_hash),
            retention_manifest_hash=(handling_manifest.retention_manifest_hash),
            handling_manifest_hash=handling_manifest.contract_hash,
            source_evidence_hash=source_evidence_hash,
            request_fingerprint=request_fingerprint,
        )
        root_descriptor = self._open_root()
        artifact_descriptor: int | None = None
        created = False
        try:
            existing = self._existing_target(
                root_descriptor=root_descriptor,
                artifact_id=artifact_id,
            )
            if existing is not None:
                if stat.S_ISLNK(existing.st_mode):
                    raise ProtectedArtifactIntegrityError(
                        "protected artifact target cannot be a symlink"
                    )
                raise ProtectedArtifactIntegrityError(
                    "protected artifact already exists"
                )
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | self._required_flag("O_NOFOLLOW")
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                artifact_descriptor = os.open(
                    artifact_id,
                    flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError as error:
                raise ProtectedArtifactIntegrityError(
                    "protected artifact already exists"
                ) from error
            except OSError as error:
                raise ProtectedArtifactIntegrityError(
                    "cannot securely create protected artifact"
                ) from error
            created = True
            self._write_all(artifact_descriptor, raw)
            os.fsync(artifact_descriptor)
            metadata = os.fstat(artifact_descriptor)
            self._validate_artifact_metadata(
                metadata,
                expected_size=receipt.byte_length,
            )
            os.lseek(artifact_descriptor, 0, os.SEEK_SET)
            persisted = self._read_all(artifact_descriptor)
            if _sha256(persisted) != receipt.raw_sha256:
                raise ProtectedArtifactIntegrityError(
                    "protected artifact readback hash mismatch"
                )
            os.fsync(root_descriptor)
        except Exception:
            if artifact_descriptor is not None:
                os.close(artifact_descriptor)
                artifact_descriptor = None
            if created:
                try:
                    os.unlink(
                        artifact_id,
                        dir_fd=root_descriptor,
                    )
                    os.fsync(root_descriptor)
                except OSError:
                    pass
            raise
        finally:
            if artifact_descriptor is not None:
                os.close(artifact_descriptor)
            os.close(root_descriptor)
        return self.verify_readback(
            receipt=receipt,
            handling_manifest=handling_manifest,
        )

    def verify_readback(
        self,
        *,
        receipt: ProtectedRawArtifactReceipt,
        handling_manifest: RawArtifactHandlingManifest,
    ) -> ProtectedRawArtifactReceipt:
        self.read_verified(
            receipt=receipt,
            handling_manifest=handling_manifest,
        )
        return receipt

    def read_verified(
        self,
        *,
        receipt: ProtectedRawArtifactReceipt,
        handling_manifest: RawArtifactHandlingManifest,
    ) -> bytes:
        """Return bytes only after verifying the protected storage contract."""
        if not isinstance(receipt, ProtectedRawArtifactReceipt):
            raise ProtectedArtifactContractError(
                "protected raw artifact receipt is required"
            )
        self._validate_manifest(handling_manifest)
        if receipt.store_id != self.store_id:
            raise ProtectedArtifactContractError(
                "protected raw artifact receipt is bound to another store"
            )
        self._check_manifest_receipt_binding(
            receipt=receipt,
            manifest=handling_manifest,
        )
        root_descriptor = self._open_root()
        artifact_descriptor: int | None = None
        try:
            path_metadata = self._existing_target(
                root_descriptor=root_descriptor,
                artifact_id=receipt.artifact_id,
            )
            if path_metadata is None:
                raise ProtectedArtifactIntegrityError("protected artifact is missing")
            if stat.S_ISLNK(path_metadata.st_mode):
                raise ProtectedArtifactIntegrityError(
                    "protected artifact target cannot be a symlink"
                )
            self._validate_artifact_metadata(
                path_metadata,
                expected_size=receipt.byte_length,
            )
            flags = (
                os.O_RDONLY
                | self._required_flag("O_NOFOLLOW")
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                artifact_descriptor = os.open(
                    receipt.artifact_id,
                    flags,
                    dir_fd=root_descriptor,
                )
            except OSError as error:
                raise ProtectedArtifactIntegrityError(
                    "cannot securely open protected artifact"
                ) from error
            opened_metadata = os.fstat(artifact_descriptor)
            if (
                opened_metadata.st_dev != path_metadata.st_dev
                or opened_metadata.st_ino != path_metadata.st_ino
            ):
                raise ProtectedArtifactIntegrityError(
                    "protected artifact changed while opening"
                )
            self._validate_artifact_metadata(
                opened_metadata,
                expected_size=receipt.byte_length,
            )
            persisted = self._read_all(artifact_descriptor)
            if len(persisted) != receipt.byte_length:
                raise ProtectedArtifactIntegrityError(
                    "protected artifact readback size mismatch"
                )
            if _sha256(persisted) != receipt.raw_sha256:
                raise ProtectedArtifactIntegrityError(
                    "protected artifact readback hash mismatch"
                )
        finally:
            if artifact_descriptor is not None:
                os.close(artifact_descriptor)
            os.close(root_descriptor)
        return persisted


__all__ = [
    "ProtectedArtifactContractError",
    "ProtectedArtifactIntegrityError",
    "ProtectedRawArtifactReceipt",
    "ProtectedRawArtifactStore",
    "RawArtifactHandlingManifest",
]
