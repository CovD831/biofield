"""Atomic, write-once storage for simulated confirmatory commitments.

This module persists only the B5 commitment layer.  Restore deliberately
requires the original typed sources; source-independent fresh-process replay
remains a B8b responsibility.  A successfully restored directory therefore
does not prove execution, cost, outcomes, production authority, or Gate state.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .meas0_confirmatory_v3 import (
    ConfirmatoryContractError,
    FormalConfirmatoryAuthorization,
    SimulatedConfirmatoryArmCaseCommitment,
    SimulatedConfirmatoryCommitmentPackage,
    _commitment_matches_authorization,
)
from .meas0_stage_cost import StageCostLedger


CONFIRMATORY_COMMITMENT_STORE_FILES = (
    "authorization.json",
    "stage_cost_ledger.json",
    "commitments.json",
    "package.json",
    "manifest.json",
    "seal.json",
)
_DATA_FILES = CONFIRMATORY_COMMITMENT_STORE_FILES[:4]
_PACKAGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_CHECKPOINT_TOKEN = object()


class ConfirmatoryCommitmentStoreError(ValueError):
    """A checkpoint or write-once commitment directory failed closed."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ConfirmatoryCommitmentStoreError(
            "confirmatory store value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConfirmatoryCommitmentStoreError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _exact_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _exact_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


def _strict_json(raw_bytes: bytes, label: str) -> object:
    duplicate = False

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        nonlocal duplicate
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                duplicate = True
            result[key] = value
        return result

    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid constant {value}")
            ),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ConfirmatoryCommitmentStoreError(
            f"{label} is not strict canonical JSON"
        ) from error
    if duplicate or _canonical_bytes(value) != raw_bytes:
        raise ConfirmatoryCommitmentStoreError(f"{label} is not strict canonical JSON")
    return value


def _validate_package_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or _PACKAGE_ID.fullmatch(value) is None
    ):
        raise ConfirmatoryCommitmentStoreError(
            "package_id must be one opaque path-free identifier"
        )
    return value


@dataclass(frozen=True)
class SimulatedConfirmatoryCommitmentCheckpoint:
    """Serializable exact prefix of the 720-member commitment sequence."""

    schema: str
    authorization: FormalConfirmatoryAuthorization
    stage_cost_ledger: StageCostLedger
    completed_commitments: tuple[
        SimulatedConfirmatoryArmCaseCommitment,
        ...,
    ]
    authorization_hash: str
    stage_cost_ledger_hash: str
    completed_commitment_hashes: tuple[str, ...]
    next_execution_index: int
    claim_scope: str
    production_authorized: bool
    formal_eligible: bool
    execution_verified: bool
    cost_verified: bool
    outcome_package_closed: bool
    checkpoint_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "completed_commitments",
            tuple(self.completed_commitments),
        )
        object.__setattr__(
            self,
            "completed_commitment_hashes",
            tuple(self.completed_commitment_hashes),
        )
        if (
            self._factory_token is not _CHECKPOINT_TOKEN
            or self.schema != "meas0.simulated-confirmatory-commitment-checkpoint.v3"
            or not isinstance(
                self.authorization,
                FormalConfirmatoryAuthorization,
            )
            or not isinstance(self.stage_cost_ledger, StageCostLedger)
            or not 0 < len(self.completed_commitments) < 720
            or self.next_execution_index != len(self.completed_commitments)
            or self.authorization_hash != self.authorization.authorization_hash
            or self.stage_cost_ledger_hash != self.stage_cost_ledger.contract_hash
            or self.completed_commitment_hashes
            != tuple(item.commitment_hash for item in self.completed_commitments)
            or tuple(item.execution_index for item in self.completed_commitments)
            != tuple(range(self.next_execution_index))
            or any(
                not isinstance(
                    item,
                    SimulatedConfirmatoryArmCaseCommitment,
                )
                or not _commitment_matches_authorization(
                    item,
                    self.authorization,
                    self.stage_cost_ledger_hash,
                )
                for item in self.completed_commitments
            )
        ):
            raise ConfirmatoryCommitmentStoreError(
                "checkpoint is not one exact ordered confirmatory prefix"
            )
        expected_keys = tuple(
            (entry.case_id, arm_id)
            for entry in self.authorization.plan.input_manifest.entries
            for arm_id in self.authorization.plan.arm_order
        )[: self.next_execution_index]
        if (
            tuple((item.case_id, item.arm_id) for item in self.completed_commitments)
            != expected_keys
        ):
            raise ConfirmatoryCommitmentStoreError(
                "checkpoint differs from the authorized case.arm prefix"
            )
        for value, label in (
            (self.authorization_hash, "checkpoint authorization hash"),
            (self.stage_cost_ledger_hash, "checkpoint StageCost ledger hash"),
            (self.checkpoint_hash, "checkpoint hash"),
        ):
            _digest(value, label)
        if (
            self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.formal_eligible is not False
            or self.execution_verified is not False
            or self.cost_verified is not False
            or self.outcome_package_closed is not False
            or self.checkpoint_hash != _canonical_hash(self._body())
        ):
            raise ConfirmatoryCommitmentStoreError(
                "checkpoint cannot upgrade a commitment into evidence"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authorization_hash": self.authorization_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "completed_commitment_hashes": list(self.completed_commitment_hashes),
            "next_execution_index": self.next_execution_index,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
            "execution_verified": self.execution_verified,
            "cost_verified": self.cost_verified,
            "outcome_package_closed": self.outcome_package_closed,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._body(),
            "completed_commitments": [
                item.to_dict() for item in self.completed_commitments
            ],
            "checkpoint_hash": self.checkpoint_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        authorization: FormalConfirmatoryAuthorization,
        completed_commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentCheckpoint:
        try:
            commitments = tuple(completed_commitments)
        except TypeError as error:
            raise ConfirmatoryCommitmentStoreError(
                "checkpoint commitments must be a typed sequence"
            ) from error
        if (
            not isinstance(
                authorization,
                FormalConfirmatoryAuthorization,
            )
            or not isinstance(stage_cost_ledger, StageCostLedger)
            or not commitments
            or not all(
                isinstance(
                    item,
                    SimulatedConfirmatoryArmCaseCommitment,
                )
                for item in commitments
            )
        ):
            raise ConfirmatoryCommitmentStoreError(
                "checkpoint requires typed authorization, ledger, and commitments"
            )
        hashes = tuple(item.commitment_hash for item in commitments)
        body = {
            "schema": ("meas0.simulated-confirmatory-commitment-checkpoint.v3"),
            "authorization_hash": getattr(
                authorization,
                "authorization_hash",
                None,
            ),
            "stage_cost_ledger_hash": getattr(
                stage_cost_ledger,
                "contract_hash",
                None,
            ),
            "completed_commitment_hashes": list(hashes),
            "next_execution_index": len(commitments),
            "claim_scope": "simulated_nonclaim",
            "production_authorized": False,
            "formal_eligible": False,
            "execution_verified": False,
            "cost_verified": False,
            "outcome_package_closed": False,
        }
        return cls(
            schema=("meas0.simulated-confirmatory-commitment-checkpoint.v3"),
            authorization=authorization,
            stage_cost_ledger=stage_cost_ledger,
            completed_commitments=commitments,
            authorization_hash=body["authorization_hash"],
            stage_cost_ledger_hash=body["stage_cost_ledger_hash"],
            completed_commitment_hashes=hashes,
            next_execution_index=len(commitments),
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            formal_eligible=False,
            execution_verified=False,
            cost_verified=False,
            outcome_package_closed=False,
            checkpoint_hash=_canonical_hash(body),
            _factory_token=_CHECKPOINT_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        authorization: FormalConfirmatoryAuthorization,
        completed_commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentCheckpoint:
        if not isinstance(value, Mapping):
            raise ConfirmatoryCommitmentStoreError(
                "serialized checkpoint must be a mapping"
            )
        restored = cls.create(
            authorization=authorization,
            completed_commitments=completed_commitments,
            stage_cost_ledger=stage_cost_ledger,
        )
        if not _exact_equal(dict(value), restored.to_dict()):
            raise ConfirmatoryCommitmentStoreError(
                "serialized checkpoint differs from typed sources"
            )
        return restored


def resume_simulated_confirmatory_commitments(
    *,
    checkpoint: SimulatedConfirmatoryCommitmentCheckpoint,
    authorization: FormalConfirmatoryAuthorization,
    remaining_commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
    stage_cost_ledger: StageCostLedger,
) -> SimulatedConfirmatoryCommitmentPackage:
    """Resume one exact prefix without executing or fabricating outcomes."""

    if not isinstance(
        checkpoint,
        SimulatedConfirmatoryCommitmentCheckpoint,
    ):
        raise ConfirmatoryCommitmentStoreError(
            "resume requires a typed confirmatory checkpoint"
        )
    checkpoint.__post_init__()
    if (
        checkpoint.authorization != authorization
        or checkpoint.stage_cost_ledger != stage_cost_ledger
    ):
        raise ConfirmatoryCommitmentStoreError(
            "checkpoint authorization or StageCost ancestry changed"
        )
    try:
        remainder = tuple(remaining_commitments)
    except TypeError as error:
        raise ConfirmatoryCommitmentStoreError(
            "remaining commitments must be a typed sequence"
        ) from error
    combined = (*checkpoint.completed_commitments, *remainder)
    if len(combined) != 720:
        raise ConfirmatoryCommitmentStoreError(
            "resume requires the exact remaining 720-member closure"
        )
    try:
        return SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=combined,
            stage_cost_ledger=stage_cost_ledger,
        )
    except (ConfirmatoryContractError, AttributeError) as error:
        raise ConfirmatoryCommitmentStoreError(
            "remaining commitments do not continue the exact checkpoint prefix"
        ) from error


class SimulatedConfirmatoryCommitmentStore:
    """Filesystem write-once store for the typed-source commitment slice."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._root_fd = os.open(
                self.root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store root must be a real directory"
            ) from error
        root_stat = os.fstat(self._root_fd)
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)
        for directory in (".objects", ".reservations"):
            try:
                os.mkdir(directory, mode=0o700, dir_fd=self._root_fd)
            except FileExistsError:
                pass
        self._objects_fd = self._open_directory(".objects", self._root_fd)
        self._reservations_fd = self._open_directory(".reservations", self._root_fd)
        objects_stat = os.fstat(self._objects_fd)
        reservations_stat = os.fstat(self._reservations_fd)
        self._objects_identity = (objects_stat.st_dev, objects_stat.st_ino)
        self._reservations_identity = (
            reservations_stat.st_dev,
            reservations_stat.st_ino,
        )
        self._thread_lock = threading.RLock()
        try:
            self._lock_fd = os.open(
                ".store.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._root_fd,
            )
        except OSError as error:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store lock cannot be opened safely"
            ) from error
        lock_stat = os.fstat(self._lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store lock must be one regular file"
            )
        self._lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
        self._acquire_store_lock(exclusive=True)
        try:
            self._recover_reservation_temps()
        finally:
            self._release_store_lock()
        os.fsync(self._root_fd)

    def __del__(self) -> None:
        for attribute in (
            "_lock_fd",
            "_reservations_fd",
            "_objects_fd",
            "_root_fd",
        ):
            descriptor = getattr(self, attribute, None)
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
            setattr(self, attribute, None)

    def _acquire_store_lock(self, *, exclusive: bool) -> None:
        self._thread_lock.acquire()
        try:
            fcntl.flock(
                self._lock_fd,
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
        except BaseException:
            self._thread_lock.release()
            raise

    def _release_store_lock(self) -> None:
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        finally:
            self._thread_lock.release()

    @staticmethod
    def _open_directory(name: str, parent_fd: int) -> int:
        try:
            return os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise ConfirmatoryCommitmentStoreError(
                f"confirmatory store directory {name!r} is not a real directory"
            ) from error

    def _verify_root_identity(self) -> None:
        try:
            path_stat = self.root.lstat()
            fd_stat = os.fstat(self._root_fd)
            objects_path_stat = os.stat(
                ".objects",
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
            reservations_path_stat = os.stat(
                ".reservations",
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
            lock_path_stat = os.stat(
                ".store.lock",
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
            objects_fd_stat = os.fstat(self._objects_fd)
            reservations_fd_stat = os.fstat(self._reservations_fd)
            lock_fd_stat = os.fstat(self._lock_fd)
        except (FileNotFoundError, OSError) as error:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store root identity changed"
            ) from error
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self._root_identity
            or (fd_stat.st_dev, fd_stat.st_ino) != self._root_identity
            or not stat.S_ISDIR(objects_path_stat.st_mode)
            or (
                objects_path_stat.st_dev,
                objects_path_stat.st_ino,
            )
            != self._objects_identity
            or (
                objects_fd_stat.st_dev,
                objects_fd_stat.st_ino,
            )
            != self._objects_identity
            or not stat.S_ISDIR(reservations_path_stat.st_mode)
            or (
                reservations_path_stat.st_dev,
                reservations_path_stat.st_ino,
            )
            != self._reservations_identity
            or (
                reservations_fd_stat.st_dev,
                reservations_fd_stat.st_ino,
            )
            != self._reservations_identity
            or not stat.S_ISREG(lock_path_stat.st_mode)
            or (lock_path_stat.st_dev, lock_path_stat.st_ino) != self._lock_identity
            or (lock_fd_stat.st_dev, lock_fd_stat.st_ino) != self._lock_identity
            or lock_fd_stat.st_nlink != 1
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store root identity changed"
            )

    @staticmethod
    def _verify_object_payloads(
        object_fd: int,
        payloads: Mapping[str, bytes],
    ) -> None:
        if set(os.listdir(object_fd)) != set(CONFIRMATORY_COMMITMENT_STORE_FILES):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory staged object exact file set changed"
            )
        for name in CONFIRMATORY_COMMITMENT_STORE_FILES:
            if (
                SimulatedConfirmatoryCommitmentStore._read_regular_file(
                    name,
                    object_fd,
                )
                != payloads[name]
            ):
                raise ConfirmatoryCommitmentStoreError(
                    f"confirmatory staged object {name} changed"
                )

    @staticmethod
    def _read_regular_file(name: str, directory_fd: int) -> bytes:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise ConfirmatoryCommitmentStoreError(
                f"confirmatory store file {name!r} cannot be opened safely"
            ) from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory store files must be unlinked regular files"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _read_regular_file_allow_links(name: str, directory_fd: int) -> bytes:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise ConfirmatoryCommitmentStoreError(
                f"confirmatory store file {name!r} cannot be opened safely"
            ) from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory store entry is not a regular file"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _recover_reservation_temps(self) -> None:
        temporary_pattern = re.compile(
            r"\.[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.[0-9a-f]{32}\.tmp\Z"
        )
        changed = False
        for name in os.listdir(self._reservations_fd):
            if temporary_pattern.fullmatch(name) is None:
                continue
            try:
                metadata = os.stat(
                    name,
                    dir_fd=self._reservations_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(metadata.st_mode):
                    raise ConfirmatoryCommitmentStoreError(
                        "reservation recovery found a non-regular temp entry"
                    )
                os.unlink(name, dir_fd=self._reservations_fd)
                changed = True
            except OSError as error:
                raise ConfirmatoryCommitmentStoreError(
                    "reservation recovery could not remove a temp entry"
                ) from error
        if changed:
            os.fsync(self._reservations_fd)

    @staticmethod
    def _remove_object(object_id: str, objects_fd: int) -> None:
        try:
            object_fd = SimulatedConfirmatoryCommitmentStore._open_directory(
                object_id,
                objects_fd,
            )
        except ConfirmatoryCommitmentStoreError:
            return
        try:
            for name in os.listdir(object_fd):
                try:
                    os.unlink(name, dir_fd=object_fd)
                except OSError:
                    pass
        finally:
            os.close(object_fd)
        try:
            os.rmdir(object_id, dir_fd=objects_fd)
        except OSError:
            pass

    @staticmethod
    def _typed_payloads(
        *,
        package: SimulatedConfirmatoryCommitmentPackage,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> dict[str, bytes]:
        try:
            values = tuple(commitments)
            restored = (
                SimulatedConfirmatoryCommitmentPackage.restore_from_typed_sources(
                    package.to_dict(),
                    authorization=authorization,
                    commitments=values,
                    stage_cost_ledger=stage_cost_ledger,
                )
            )
        except (
            AttributeError,
            ConfirmatoryContractError,
            TypeError,
            ValueError,
        ) as error:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store preflight requires one exact typed package"
            ) from error
        if restored != package:
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory package differs after typed restoration"
            )
        return {
            "authorization.json": _canonical_bytes(authorization.to_dict()),
            "stage_cost_ledger.json": _canonical_bytes(stage_cost_ledger.to_dict()),
            "commitments.json": _canonical_bytes([item.to_dict() for item in values]),
            "package.json": _canonical_bytes(package.to_dict()),
        }

    @staticmethod
    def _manifest(
        *,
        package_id: str,
        package: SimulatedConfirmatoryCommitmentPackage,
        payloads: Mapping[str, bytes],
    ) -> dict[str, object]:
        return {
            "schema": "meas0.simulated-confirmatory-store-manifest.v3",
            "version": 1,
            "package_id": package_id,
            "files": [
                {
                    "relative_path": name,
                    "content_sha256": _bytes_hash(payloads[name]),
                    "byte_count": len(payloads[name]),
                }
                for name in _DATA_FILES
            ],
            "package_hash": package.package_hash,
            "run_hash": package.run.run_hash,
            "commitment_package_seal_hash": package.seal_hash,
            "claim_scope": "simulated_nonclaim",
            "typed_source_restore_required": True,
            "fresh_process_restore_ready": False,
            "production_authorized": False,
            "formal_eligible": False,
            "execution_verified": False,
            "cost_verified": False,
            "outcome_package_closed": False,
        }

    @staticmethod
    def _seal(
        *,
        manifest: Mapping[str, object],
        package: SimulatedConfirmatoryCommitmentPackage,
    ) -> dict[str, object]:
        body = {
            "schema": "meas0.simulated-confirmatory-store-seal.v3",
            "version": 1,
            "manifest_hash": _canonical_hash(dict(manifest)),
            "package_hash": package.package_hash,
            "run_hash": package.run.run_hash,
            "claim_scope": "simulated_nonclaim",
            "typed_source_restore_required": True,
            "fresh_process_restore_ready": False,
        }
        return {**body, "seal_hash": _canonical_hash(body)}

    def publish(
        self,
        *,
        package_id: str,
        package: SimulatedConfirmatoryCommitmentPackage,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> Path:
        self._acquire_store_lock(exclusive=True)
        try:
            return self._publish_unlocked(
                package_id=package_id,
                package=package,
                authorization=authorization,
                commitments=commitments,
                stage_cost_ledger=stage_cost_ledger,
            )
        finally:
            self._release_store_lock()

    def _publish_unlocked(
        self,
        *,
        package_id: str,
        package: SimulatedConfirmatoryCommitmentPackage,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> Path:
        package_id = _validate_package_id(package_id)
        payloads = self._typed_payloads(
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=stage_cost_ledger,
        )
        manifest = self._manifest(
            package_id=package_id,
            package=package,
            payloads=payloads,
        )
        payloads = {
            **payloads,
            "manifest.json": _canonical_bytes(manifest),
            "seal.json": _canonical_bytes(
                self._seal(manifest=manifest, package=package)
            ),
        }
        self._verify_root_identity()
        objects_fd = self._objects_fd
        reservations_fd = self._reservations_fd
        object_id = uuid.uuid4().hex
        reservation_temp = f".{package_id}.{uuid.uuid4().hex}.tmp"
        object_created = False
        committed = False
        object_fd: int | None = None
        reservation: bytes | None = None
        try:
            try:
                os.mkdir(object_id, mode=0o700, dir_fd=objects_fd)
            except OSError as error:
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory object staging directory cannot be created"
                ) from error
            object_created = True
            object_fd = self._open_directory(object_id, objects_fd)
            for relative_path in CONFIRMATORY_COMMITMENT_STORE_FILES:
                descriptor = os.open(
                    relative_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=object_fd,
                )
                try:
                    view = memoryview(payloads[relative_path])
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            os.fsync(object_fd)
            self._verify_object_payloads(object_fd, payloads)
            object_stat = os.fstat(object_fd)

            reservation = _canonical_bytes(
                {
                    "schema": "meas0.simulated-confirmatory-reservation.v3",
                    "package_id": package_id,
                    "object_id": object_id,
                    "object_device": object_stat.st_dev,
                    "object_inode": object_stat.st_ino,
                    "package_hash": package.package_hash,
                    "claim_scope": "simulated_nonclaim",
                }
            )
            descriptor = os.open(
                reservation_temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=reservations_fd,
            )
            try:
                view = memoryview(reservation)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(
                    reservation_temp,
                    package_id,
                    src_dir_fd=reservations_fd,
                    dst_dir_fd=reservations_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                try:
                    final_reservation = self._read_regular_file_allow_links(
                        package_id,
                        reservations_fd,
                    )
                except ConfirmatoryCommitmentStoreError:
                    raise ConfirmatoryCommitmentStoreError(
                        "write-once confirmatory publish lost a concurrent race"
                    ) from error
                if final_reservation != reservation:
                    raise ConfirmatoryCommitmentStoreError(
                        "write-once confirmatory publish lost a concurrent race"
                    ) from error
            committed = True
            linked_stat = os.stat(
                object_id,
                dir_fd=objects_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISDIR(linked_stat.st_mode) or (
                linked_stat.st_dev,
                linked_stat.st_ino,
            ) != (object_stat.st_dev, object_stat.st_ino):
                raise ConfirmatoryCommitmentStoreError(
                    "committed confirmatory object mapping changed"
                )
            self._verify_object_payloads(object_fd, payloads)
            os.unlink(reservation_temp, dir_fd=reservations_fd)
            os.fsync(reservations_fd)
            os.fsync(objects_fd)
            os.fsync(self._root_fd)
            self._verify_root_identity()
            return self.root / ".objects" / object_id
        finally:
            try:
                os.unlink(reservation_temp, dir_fd=reservations_fd)
            except OSError:
                pass
            if object_created and not committed and reservation is not None:
                try:
                    committed = (
                        self._read_regular_file_allow_links(
                            package_id,
                            reservations_fd,
                        )
                        == reservation
                    )
                except ConfirmatoryCommitmentStoreError:
                    pass
            if object_created and not committed:
                self._remove_object(object_id, objects_fd)
            if object_fd is not None:
                os.close(object_fd)

    def _read_exact_directory(
        self,
        package_id: str,
    ) -> dict[str, bytes]:
        package_id = _validate_package_id(package_id)
        self._verify_root_identity()
        reservation_raw = self._read_regular_file(
            package_id,
            self._reservations_fd,
        )
        reservation_stat = os.stat(
            package_id,
            dir_fd=self._reservations_fd,
            follow_symlinks=False,
        )
        reservation = _strict_json(reservation_raw, "reservation")
        if (
            not isinstance(reservation, Mapping)
            or set(reservation)
            != {
                "schema",
                "package_id",
                "object_id",
                "object_device",
                "object_inode",
                "package_hash",
                "claim_scope",
            }
            or reservation["schema"] != "meas0.simulated-confirmatory-reservation.v3"
            or reservation["package_id"] != package_id
            or reservation["claim_scope"] != "simulated_nonclaim"
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory package reservation is invalid"
            )
        object_id = _validate_package_id(reservation["object_id"])
        if (
            type(reservation["object_device"]) is not int
            or type(reservation["object_inode"]) is not int
            or reservation["object_device"] < 0
            or reservation["object_inode"] <= 0
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory reservation object identity is invalid"
            )
        _digest(reservation["package_hash"], "reservation package hash")
        object_fd = self._open_directory(object_id, self._objects_fd)
        try:
            object_stat = os.fstat(object_fd)
            if (object_stat.st_dev, object_stat.st_ino) != (
                reservation["object_device"],
                reservation["object_inode"],
            ):
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory reservation object identity changed"
                )
            entries = set(os.listdir(object_fd))
            if entries != set(CONFIRMATORY_COMMITMENT_STORE_FILES):
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory store exact file set is missing or extra"
                )
            result: dict[str, bytes] = {}
            for name in CONFIRMATORY_COMMITMENT_STORE_FILES:
                raw_bytes = self._read_regular_file(name, object_fd)
                _strict_json(raw_bytes, name)
                result[name] = raw_bytes
            current_object_stat = os.stat(
                object_id,
                dir_fd=self._objects_fd,
                follow_symlinks=False,
            )
            if (
                current_object_stat.st_dev,
                current_object_stat.st_ino,
            ) != (object_stat.st_dev, object_stat.st_ino):
                raise ConfirmatoryCommitmentStoreError(
                    "confirmatory object mapping changed during restore"
                )
        finally:
            os.close(object_fd)
        current_reservation_stat = os.stat(
            package_id,
            dir_fd=self._reservations_fd,
            follow_symlinks=False,
        )
        if (
            current_reservation_stat.st_dev,
            current_reservation_stat.st_ino,
        ) != (reservation_stat.st_dev, reservation_stat.st_ino) or (
            self._read_regular_file(package_id, self._reservations_fd)
            != reservation_raw
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory reservation changed during restore"
            )
        self._verify_root_identity()
        package_raw = _strict_json(result["package.json"], "package.json")
        if (
            not isinstance(package_raw, Mapping)
            or package_raw.get("package_hash") != reservation["package_hash"]
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory reservation differs from stored package"
            )
        return result

    def restore(
        self,
        *,
        package_id: str,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentPackage:
        self._acquire_store_lock(exclusive=False)
        try:
            return self._restore_unlocked(
                package_id=package_id,
                authorization=authorization,
                commitments=commitments,
                stage_cost_ledger=stage_cost_ledger,
            )
        finally:
            self._release_store_lock()

    def _restore_unlocked(
        self,
        *,
        package_id: str,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentPackage:
        package_id = _validate_package_id(package_id)
        payloads = self._read_exact_directory(package_id)
        decoded = {
            name: _strict_json(raw_bytes, name) for name, raw_bytes in payloads.items()
        }
        manifest = decoded["manifest.json"]
        seal = decoded["seal.json"]
        if not isinstance(manifest, Mapping) or not isinstance(seal, Mapping):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory manifest and seal must be mappings"
            )
        package_raw = decoded["package.json"]
        if not isinstance(package_raw, Mapping):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory package JSON must be a mapping"
            )
        try:
            package = SimulatedConfirmatoryCommitmentPackage.restore_from_typed_sources(
                package_raw,
                authorization=authorization,
                commitments=commitments,
                stage_cost_ledger=stage_cost_ledger,
            )
        except ConfirmatoryContractError as error:
            raise ConfirmatoryCommitmentStoreError(
                "stored package differs from supplied typed sources"
            ) from error
        expected_payloads = self._typed_payloads(
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=stage_cost_ledger,
        )
        for name, expected in expected_payloads.items():
            if payloads[name] != expected:
                raise ConfirmatoryCommitmentStoreError(
                    f"stored {name} differs from typed sources"
                )
        expected_manifest = self._manifest(
            package_id=package_id,
            package=package,
            payloads=expected_payloads,
        )
        expected_seal = self._seal(
            manifest=expected_manifest,
            package=package,
        )
        if (
            not _exact_equal(dict(manifest), expected_manifest)
            or not _exact_equal(dict(seal), expected_seal)
            or payloads["manifest.json"] != _canonical_bytes(expected_manifest)
            or payloads["seal.json"] != _canonical_bytes(expected_seal)
        ):
            raise ConfirmatoryCommitmentStoreError(
                "confirmatory store manifest or seal is invalid"
            )
        return package


__all__ = [
    "CONFIRMATORY_COMMITMENT_STORE_FILES",
    "ConfirmatoryCommitmentStoreError",
    "SimulatedConfirmatoryCommitmentCheckpoint",
    "SimulatedConfirmatoryCommitmentStore",
    "resume_simulated_confirmatory_commitments",
]
