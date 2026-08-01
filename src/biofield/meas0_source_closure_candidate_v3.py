"""D12 self-contained source-closure candidate (offline, non-claim only).

This module binds exact wheel/sdist, dependency-lock, environment, build
metadata, and source-lock bytes.  It is deliberately a *candidate* carrier:
it does not authorize source restoration, fresh replay, production execution,
formal outcomes, or Gate assessment.  A later normative decision may choose
this artifact family or an authority-bound immutable resolver; this module
does not make that choice.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


class SelfContainedClosureCandidateError(ValueError):
    """The offline D12 candidate is incomplete, non-canonical, or forged."""


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DEPENDENCY_TOKEN = object()
_CANDIDATE_TOKEN = object()

SCHEMA = "meas0.simulated-self-contained-source-closure-candidate.v3"
CLAIM_SCOPE = "simulated_nonclaim"


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SelfContainedClosureCandidateError(
            "candidate value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SelfContainedClosureCandidateError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SelfContainedClosureCandidateError(f"{label} must be non-empty text")
    if any(ord(character) < 32 for character in value):
        raise SelfContainedClosureCandidateError(
            f"{label} contains a control character"
        )
    return value


def _path_free_text(value: object, label: str) -> str:
    result = _text(value, label)
    if "/" in result or "\\" in result or result in {".", ".."}:
        raise SelfContainedClosureCandidateError(
            f"{label} must not contain a path separator"
        )
    return result


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise SelfContainedClosureCandidateError(
            f"{label} must be one opaque path-free identifier"
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


def _strict_mapping(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise SelfContainedClosureCandidateError(f"{label} fields are invalid")
    return value


def _decode_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise SelfContainedClosureCandidateError(f"{label} must be base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise SelfContainedClosureCandidateError(
            f"{label} is not strict base64"
        ) from error
    if not decoded:
        raise SelfContainedClosureCandidateError(f"{label} must not be empty")
    return decoded


def _decode_canonical_object(raw_bytes: bytes) -> Mapping[str, Any]:
    if type(raw_bytes) is not bytes:
        raise SelfContainedClosureCandidateError(
            "candidate archive must be supplied as exact bytes"
        )
    duplicate = False

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                duplicate = True
            result[key] = item
        return result

    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise SelfContainedClosureCandidateError(
            "candidate archive is not strict canonical JSON"
        ) from error
    if duplicate or _canonical_bytes(value) != raw_bytes:
        raise SelfContainedClosureCandidateError(
            "candidate archive is not canonical or contains duplicate fields"
        )
    if not isinstance(value, dict):
        raise SelfContainedClosureCandidateError(
            "candidate archive root must be an object"
        )
    return value


@dataclass(frozen=True)
class SimulatedDependencyArtifactV3:
    """One exact dependency artifact entry in the offline lock closure."""

    schema: str
    name: str
    version: str
    artifact_kind: str
    artifact_sha256: str
    artifact_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _DEPENDENCY_TOKEN:
            raise SelfContainedClosureCandidateError(
                "dependency artifact requires its factory"
            )
        if self.schema != "meas0.simulated-dependency-artifact.v3":
            raise SelfContainedClosureCandidateError(
                "dependency artifact schema is invalid"
            )
        _path_free_text(self.name, "dependency name")
        _path_free_text(self.version, "dependency version")
        if self.artifact_kind not in {"wheel", "sdist"}:
            raise SelfContainedClosureCandidateError(
                "dependency artifact kind is invalid"
            )
        _digest(self.artifact_sha256, "dependency artifact digest")
        expected = _canonical_hash(self._body_without_hash())
        if self.artifact_hash != expected:
            raise SelfContainedClosureCandidateError(
                "dependency artifact hash is not source-derived"
            )

    @classmethod
    def create(
        cls,
        *,
        name: str,
        version: str,
        artifact_kind: str,
        artifact_sha256: str,
    ) -> SimulatedDependencyArtifactV3:
        _path_free_text(name, "dependency name")
        _path_free_text(version, "dependency version")
        _digest(artifact_sha256, "dependency artifact digest")
        body = {
            "schema": "meas0.simulated-dependency-artifact.v3",
            "name": name,
            "version": version,
            "artifact_kind": artifact_kind,
            "artifact_sha256": artifact_sha256,
        }
        return cls(
            **body,
            artifact_hash=_canonical_hash(body),
            _factory_token=_DEPENDENCY_TOKEN,
        )

    def _body_without_hash(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "version": self.version,
            "artifact_kind": self.artifact_kind,
            "artifact_sha256": self.artifact_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body_without_hash(), "artifact_hash": self.artifact_hash}

    @classmethod
    def restore(cls, value: object) -> SimulatedDependencyArtifactV3:
        raw = _strict_mapping(
            value,
            {
                "schema",
                "name",
                "version",
                "artifact_kind",
                "artifact_sha256",
                "artifact_hash",
            },
            "dependency artifact",
        )
        try:
            restored = cls.create(
                name=raw["name"],
                version=raw["version"],
                artifact_kind=raw["artifact_kind"],
                artifact_sha256=raw["artifact_sha256"],
            )
        except (TypeError, SelfContainedClosureCandidateError) as error:
            raise SelfContainedClosureCandidateError(
                f"dependency artifact cannot be restored: {error}"
            ) from error
        if not _exact_equal(value, restored.to_dict()):
            raise SelfContainedClosureCandidateError(
                "dependency artifact differs from source-derived bytes"
            )
        return restored


@dataclass(frozen=True)
class SimulatedSelfContainedSourceClosureCandidateV3:
    """Exact-byte D12 candidate with all claim and replay authority disabled."""

    schema: str
    version: int
    closure_id: str
    source_lock_bytes: bytes = field(repr=False)
    source_lock_sha256: str
    wheel_bytes: bytes = field(repr=False)
    wheel_sha256: str
    sdist_bytes: bytes = field(repr=False)
    sdist_sha256: str
    dependency_lock_bytes: bytes = field(repr=False)
    dependency_lock_sha256: str
    dependency_artifacts: tuple[SimulatedDependencyArtifactV3, ...]
    environment_bytes: bytes = field(repr=False)
    environment_sha256: str
    build_metadata_bytes: bytes = field(repr=False)
    build_metadata_sha256: str
    resolver_id: str
    resolver_version: str
    claim_scope: str
    test_only: bool
    production_authorized: bool
    source_restoration_authorized: bool
    fresh_replay_ready: bool
    formal_eligible: bool
    artifact_closure_candidate: bool
    candidate_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _CANDIDATE_TOKEN:
            raise SelfContainedClosureCandidateError(
                "self-contained closure candidate requires its factory"
            )
        if self.schema != SCHEMA or type(self.version) is not int or self.version != 1:
            raise SelfContainedClosureCandidateError(
                "candidate schema/version is invalid"
            )
        _identifier(self.closure_id, "closure_id")
        bytes_fields = (
            (self.source_lock_bytes, "source lock bytes", self.source_lock_sha256),
            (self.wheel_bytes, "wheel bytes", self.wheel_sha256),
            (self.sdist_bytes, "sdist bytes", self.sdist_sha256),
            (
                self.dependency_lock_bytes,
                "dependency lock bytes",
                self.dependency_lock_sha256,
            ),
            (self.environment_bytes, "environment bytes", self.environment_sha256),
            (
                self.build_metadata_bytes,
                "build metadata bytes",
                self.build_metadata_sha256,
            ),
        )
        for raw_bytes, label, digest in bytes_fields:
            if type(raw_bytes) is not bytes or not raw_bytes:
                raise SelfContainedClosureCandidateError(
                    f"{label} must be non-empty bytes"
                )
            if digest != _bytes_hash(raw_bytes):
                raise SelfContainedClosureCandidateError(f"{label} hash mismatch")
            _digest(digest, f"{label} hash")
        artifacts = tuple(self.dependency_artifacts)
        if not artifacts or not all(
            isinstance(item, SimulatedDependencyArtifactV3) for item in artifacts
        ):
            raise SelfContainedClosureCandidateError(
                "dependency artifact closure must be non-empty and typed"
            )
        keys = tuple(
            (item.name, item.version, item.artifact_kind) for item in artifacts
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise SelfContainedClosureCandidateError(
                "dependency artifact closure must be canonically ordered and unique"
            )
        object.__setattr__(self, "dependency_artifacts", artifacts)
        _path_free_text(self.resolver_id, "resolver_id")
        _path_free_text(self.resolver_version, "resolver_version")
        if (
            self.claim_scope != CLAIM_SCOPE
            or self.test_only is not True
            or self.production_authorized is not False
            or self.source_restoration_authorized is not False
            or self.fresh_replay_ready is not False
            or self.formal_eligible is not False
            or self.artifact_closure_candidate is not True
        ):
            raise SelfContainedClosureCandidateError(
                "candidate authority flags are not the fixed nonclaim boundary"
            )
        _digest(self.candidate_hash, "candidate hash")
        if self.candidate_hash != _canonical_hash(self._body()):
            raise SelfContainedClosureCandidateError(
                "candidate hash is not source-derived"
            )

    @classmethod
    def create(
        cls,
        *,
        closure_id: str,
        source_lock_bytes: bytes,
        wheel_bytes: bytes,
        sdist_bytes: bytes,
        dependency_lock_bytes: bytes,
        dependency_artifacts: Sequence[SimulatedDependencyArtifactV3],
        environment_bytes: bytes,
        build_metadata_bytes: bytes,
        resolver_id: str,
        resolver_version: str,
    ) -> SimulatedSelfContainedSourceClosureCandidateV3:
        for raw_bytes, label in (
            (source_lock_bytes, "source lock bytes"),
            (wheel_bytes, "wheel bytes"),
            (sdist_bytes, "sdist bytes"),
            (dependency_lock_bytes, "dependency lock bytes"),
            (environment_bytes, "environment bytes"),
            (build_metadata_bytes, "build metadata bytes"),
        ):
            if type(raw_bytes) is not bytes or not raw_bytes:
                raise SelfContainedClosureCandidateError(
                    f"{label} must be non-empty bytes"
                )
        try:
            artifacts = tuple(dependency_artifacts)
        except TypeError as error:
            raise SelfContainedClosureCandidateError(
                "dependency artifact closure must be a typed sequence"
            ) from error
        if not artifacts or not all(
            isinstance(item, SimulatedDependencyArtifactV3) for item in artifacts
        ):
            raise SelfContainedClosureCandidateError(
                "dependency artifact closure must contain typed dependency artifacts"
            )
        values = {
            "schema": SCHEMA,
            "version": 1,
            "closure_id": closure_id,
            "source_lock_bytes": source_lock_bytes,
            "source_lock_sha256": _bytes_hash(source_lock_bytes),
            "wheel_bytes": wheel_bytes,
            "wheel_sha256": _bytes_hash(wheel_bytes),
            "sdist_bytes": sdist_bytes,
            "sdist_sha256": _bytes_hash(sdist_bytes),
            "dependency_lock_bytes": dependency_lock_bytes,
            "dependency_lock_sha256": _bytes_hash(dependency_lock_bytes),
            "dependency_artifacts": artifacts,
            "environment_bytes": environment_bytes,
            "environment_sha256": _bytes_hash(environment_bytes),
            "build_metadata_bytes": build_metadata_bytes,
            "build_metadata_sha256": _bytes_hash(build_metadata_bytes),
            "resolver_id": resolver_id,
            "resolver_version": resolver_version,
            "claim_scope": CLAIM_SCOPE,
            "test_only": True,
            "production_authorized": False,
            "source_restoration_authorized": False,
            "fresh_replay_ready": False,
            "formal_eligible": False,
            "artifact_closure_candidate": True,
        }
        hash_body = {
            "schema": values["schema"],
            "version": values["version"],
            "closure_id": values["closure_id"],
            "source_lock_bytes_base64": base64.b64encode(source_lock_bytes).decode(
                "ascii"
            ),
            "source_lock_sha256": values["source_lock_sha256"],
            "wheel_bytes_base64": base64.b64encode(wheel_bytes).decode("ascii"),
            "wheel_sha256": values["wheel_sha256"],
            "sdist_bytes_base64": base64.b64encode(sdist_bytes).decode("ascii"),
            "sdist_sha256": values["sdist_sha256"],
            "dependency_lock_bytes_base64": base64.b64encode(
                dependency_lock_bytes
            ).decode("ascii"),
            "dependency_lock_sha256": values["dependency_lock_sha256"],
            "dependency_artifacts": [item.to_dict() for item in artifacts],
            "environment_bytes_base64": base64.b64encode(environment_bytes).decode(
                "ascii"
            ),
            "environment_sha256": values["environment_sha256"],
            "build_metadata_bytes_base64": base64.b64encode(
                build_metadata_bytes
            ).decode("ascii"),
            "build_metadata_sha256": values["build_metadata_sha256"],
            "resolver_id": values["resolver_id"],
            "resolver_version": values["resolver_version"],
            "claim_scope": values["claim_scope"],
            "test_only": values["test_only"],
            "production_authorized": values["production_authorized"],
            "source_restoration_authorized": values["source_restoration_authorized"],
            "fresh_replay_ready": values["fresh_replay_ready"],
            "formal_eligible": values["formal_eligible"],
            "artifact_closure_candidate": values["artifact_closure_candidate"],
        }
        candidate = cls(
            **values,
            candidate_hash=_canonical_hash(hash_body),
            _factory_token=_CANDIDATE_TOKEN,
        )
        return candidate

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "closure_id": self.closure_id,
            "source_lock_bytes_base64": base64.b64encode(self.source_lock_bytes).decode(
                "ascii"
            ),
            "source_lock_sha256": self.source_lock_sha256,
            "wheel_bytes_base64": base64.b64encode(self.wheel_bytes).decode("ascii"),
            "wheel_sha256": self.wheel_sha256,
            "sdist_bytes_base64": base64.b64encode(self.sdist_bytes).decode("ascii"),
            "sdist_sha256": self.sdist_sha256,
            "dependency_lock_bytes_base64": base64.b64encode(
                self.dependency_lock_bytes
            ).decode("ascii"),
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "dependency_artifacts": [
                item.to_dict() for item in self.dependency_artifacts
            ],
            "environment_bytes_base64": base64.b64encode(self.environment_bytes).decode(
                "ascii"
            ),
            "environment_sha256": self.environment_sha256,
            "build_metadata_bytes_base64": base64.b64encode(
                self.build_metadata_bytes
            ).decode("ascii"),
            "build_metadata_sha256": self.build_metadata_sha256,
            "resolver_id": self.resolver_id,
            "resolver_version": self.resolver_version,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "source_restoration_authorized": self.source_restoration_authorized,
            "fresh_replay_ready": self.fresh_replay_ready,
            "formal_eligible": self.formal_eligible,
            "artifact_closure_candidate": self.artifact_closure_candidate,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "candidate_hash": self.candidate_hash}

    def to_canonical_bytes(self) -> bytes:
        """Return the exact JSON bytes accepted by fresh-process restore."""

        return _canonical_bytes(self.to_dict())

    @classmethod
    def restore(
        cls,
        value: object,
    ) -> SimulatedSelfContainedSourceClosureCandidateV3:
        raw = _strict_mapping(
            value,
            {
                "schema",
                "version",
                "closure_id",
                "source_lock_bytes_base64",
                "source_lock_sha256",
                "wheel_bytes_base64",
                "wheel_sha256",
                "sdist_bytes_base64",
                "sdist_sha256",
                "dependency_lock_bytes_base64",
                "dependency_lock_sha256",
                "dependency_artifacts",
                "environment_bytes_base64",
                "environment_sha256",
                "build_metadata_bytes_base64",
                "build_metadata_sha256",
                "resolver_id",
                "resolver_version",
                "claim_scope",
                "test_only",
                "production_authorized",
                "source_restoration_authorized",
                "fresh_replay_ready",
                "formal_eligible",
                "artifact_closure_candidate",
                "candidate_hash",
            },
            "self-contained closure candidate",
        )
        artifacts_raw = raw["dependency_artifacts"]
        if type(artifacts_raw) is not list:
            raise SelfContainedClosureCandidateError(
                "dependency artifact closure must be a list"
            )
        artifacts = tuple(
            SimulatedDependencyArtifactV3.restore(item) for item in artifacts_raw
        )
        try:
            candidate = cls.create(
                closure_id=raw["closure_id"],
                source_lock_bytes=_decode_bytes(
                    raw["source_lock_bytes_base64"], "source lock bytes"
                ),
                wheel_bytes=_decode_bytes(raw["wheel_bytes_base64"], "wheel bytes"),
                sdist_bytes=_decode_bytes(raw["sdist_bytes_base64"], "sdist bytes"),
                dependency_lock_bytes=_decode_bytes(
                    raw["dependency_lock_bytes_base64"], "dependency lock bytes"
                ),
                dependency_artifacts=artifacts,
                environment_bytes=_decode_bytes(
                    raw["environment_bytes_base64"], "environment bytes"
                ),
                build_metadata_bytes=_decode_bytes(
                    raw["build_metadata_bytes_base64"], "build metadata bytes"
                ),
                resolver_id=raw["resolver_id"],
                resolver_version=raw["resolver_version"],
            )
        except (TypeError, SelfContainedClosureCandidateError) as error:
            raise SelfContainedClosureCandidateError(
                f"self-contained closure candidate cannot be restored: {error}"
            ) from error
        if not _exact_equal(value, candidate.to_dict()):
            raise SelfContainedClosureCandidateError(
                "candidate differs from source-derived closure bytes or authority"
            )
        return candidate

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
    ) -> SimulatedSelfContainedSourceClosureCandidateV3:
        return cls.restore(_decode_canonical_object(raw_bytes))


__all__ = [
    "SCHEMA",
    "SelfContainedClosureCandidateError",
    "SimulatedDependencyArtifactV3",
    "SimulatedSelfContainedSourceClosureCandidateV3",
]
