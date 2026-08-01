"""Offline composite index for the public and protected MEAS0 V3 slices.

The composite is deliberately only a membership index.  It binds the two
already typed carriers to one package and ancestry, but it cannot upgrade
either carrier into source restoration, fresh replay, transport, or formal
evidence authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .meas0_protected_raw_bundle_v3 import SimulatedProtectedRawBundleV3
from .meas0_raw_package_closure_v3 import SimulatedPublicPackageClosure


class CompositeClosureError(ValueError):
    """Composite closure membership or replay boundary failed closed."""


_TOKEN = object()
_SCHEMA = "meas0.simulated-composite-closure.v3"
_MISSING = (
    "source_restoration_artifact",
    "transport_verifier",
    "human_signature_verifier",
    "authority_bound_package_seal",
)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CompositeClosureError("composite value is not canonical JSON") from error


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CompositeClosureError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_object(value: object, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CompositeClosureError("composite fields are invalid")
    return value


def _decode(raw_bytes: bytes) -> Mapping[str, Any]:
    if type(raw_bytes) is not bytes:
        raise CompositeClosureError("composite bytes must be exact bytes")
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
                ValueError(f"non-finite {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise CompositeClosureError("composite bytes are not strict JSON") from error
    if duplicate or _canonical(value) != raw_bytes:
        raise CompositeClosureError("composite bytes are not canonical")
    if not isinstance(value, dict):
        raise CompositeClosureError("composite bytes must contain an object")
    return value


@dataclass(frozen=True)
class SimulatedCompositeClosureV3:
    """Membership-only binding of public and protected offline carriers."""

    schema: str
    version: int
    package_id: str
    common_ancestry_hash: str
    public_closure_hash: str
    protected_bundle_hash: str
    membership_hash: str
    raw_package_closed: bool
    source_restoration_authorized: bool
    fresh_replay_ready: bool
    missing_replay_authorities: tuple[str, ...]
    claim_scope: str
    production_authorized: bool
    test_only: bool
    composite_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _TOKEN:
            raise CompositeClosureError("composite requires its factory")
        if self.schema != _SCHEMA or self.version != 1:
            raise CompositeClosureError("composite schema/version is invalid")
        if not isinstance(self.package_id, str) or not self.package_id:
            raise CompositeClosureError("composite package ID is invalid")
        for value, label in (
            (self.common_ancestry_hash, "common ancestry"),
            (self.public_closure_hash, "public closure"),
            (self.protected_bundle_hash, "protected bundle"),
            (self.membership_hash, "membership"),
            (self.composite_hash, "composite"),
        ):
            _digest(value, label)
        object.__setattr__(
            self, "missing_replay_authorities", tuple(self.missing_replay_authorities)
        )
        if (
            self.raw_package_closed is not False
            or self.source_restoration_authorized is not False
            or self.fresh_replay_ready is not False
            or self.missing_replay_authorities != _MISSING
            or self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise CompositeClosureError(
                "composite cannot carry replay or production authority"
            )
        if self.membership_hash != _hash(self._membership_body()):
            raise CompositeClosureError("composite membership hash mismatch")
        if self.composite_hash != _hash(self._body()):
            raise CompositeClosureError("composite hash mismatch")

    def _membership_body(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "public_closure_hash": self.public_closure_hash,
            "protected_bundle_hash": self.protected_bundle_hash,
        }

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "package_id": self.package_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "public_closure_hash": self.public_closure_hash,
            "protected_bundle_hash": self.protected_bundle_hash,
            "membership_hash": self.membership_hash,
            "raw_package_closed": self.raw_package_closed,
            "source_restoration_authorized": self.source_restoration_authorized,
            "fresh_replay_ready": self.fresh_replay_ready,
            "missing_replay_authorities": list(self.missing_replay_authorities),
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "composite_hash": self.composite_hash}

    def to_canonical_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def create_from_typed_sources(
        cls,
        *,
        public_closure: SimulatedPublicPackageClosure,
        protected_bundle: SimulatedProtectedRawBundleV3,
    ) -> SimulatedCompositeClosureV3:
        if not isinstance(public_closure, SimulatedPublicPackageClosure):
            raise CompositeClosureError("typed public closure is required")
        if not isinstance(protected_bundle, SimulatedProtectedRawBundleV3):
            raise CompositeClosureError("typed protected bundle is required")
        if (
            public_closure.package_id != protected_bundle.package_id
            or public_closure.common_ancestry_hash
            != protected_bundle.common_ancestry_hash
        ):
            raise CompositeClosureError(
                "public and protected carriers have mixed ancestry"
            )
        membership = {
            "package_id": public_closure.package_id,
            "common_ancestry_hash": public_closure.common_ancestry_hash,
            "public_closure_hash": public_closure.closure_hash,
            "protected_bundle_hash": protected_bundle.bundle_hash,
        }
        body = {
            "schema": _SCHEMA,
            "version": 1,
            **membership,
            "membership_hash": _hash(membership),
            "raw_package_closed": False,
            "source_restoration_authorized": False,
            "fresh_replay_ready": False,
            "missing_replay_authorities": list(_MISSING),
            "claim_scope": "simulated_nonclaim",
            "production_authorized": False,
            "test_only": True,
        }
        return cls(**body, composite_hash=_hash(body), _factory_token=_TOKEN)

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        public_closure: SimulatedPublicPackageClosure,
        protected_bundle: SimulatedProtectedRawBundleV3,
    ) -> SimulatedCompositeClosureV3:
        value = _decode(raw_bytes)
        expected = cls.create_from_typed_sources(
            public_closure=public_closure, protected_bundle=protected_bundle
        )
        raw = _strict_object(value, set(expected.to_dict()))
        if dict(raw) != expected.to_dict():
            raise CompositeClosureError(
                "composite differs from source-derived membership"
            )
        return expected


__all__ = ["CompositeClosureError", "SimulatedCompositeClosureV3"]
