from __future__ import annotations

import base64
from copy import deepcopy
import json

import pytest

from biofield.meas0_source_closure_candidate_v3 import (
    SelfContainedClosureCandidateError,
    SimulatedDependencyArtifactV3,
    SimulatedSelfContainedSourceClosureCandidateV3,
)


def _digest(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _candidate() -> SimulatedSelfContainedSourceClosureCandidateV3:
    dependency = SimulatedDependencyArtifactV3.create(
        name="jsonschema",
        version="4.23.0",
        artifact_kind="wheel",
        artifact_sha256="a" * 64,
    )
    return SimulatedSelfContainedSourceClosureCandidateV3.create(
        closure_id="pytest-d12-candidate-v3",
        source_lock_bytes=b'{"lock":"source-v2"}\n',
        wheel_bytes=b"exact wheel bytes",
        sdist_bytes=b"exact sdist bytes",
        dependency_lock_bytes=b"jsonschema==4.23.0\\n",
        dependency_artifacts=(dependency,),
        environment_bytes=b'{"python":"3.11.9","platform":"test"}\n',
        build_metadata_bytes=b'{"backend":"setuptools.build_meta","version":"0.0.1"}\n',
        resolver_id="offline-pip-lock",
        resolver_version="1",
    )


def test_candidate_binds_all_artifact_and_environment_bytes_without_authority() -> None:
    candidate = _candidate()

    assert candidate.source_lock_sha256 == _digest(b'{"lock":"source-v2"}\n')
    assert candidate.wheel_sha256 == _digest(b"exact wheel bytes")
    assert candidate.sdist_sha256 == _digest(b"exact sdist bytes")
    assert candidate.dependency_lock_sha256 == _digest(b"jsonschema==4.23.0\\n")
    assert candidate.environment_sha256 == _digest(
        b'{"python":"3.11.9","platform":"test"}\n'
    )
    assert candidate.build_metadata_sha256 == _digest(
        b'{"backend":"setuptools.build_meta","version":"0.0.1"}\n'
    )
    assert candidate.claim_scope == "simulated_nonclaim"
    assert candidate.test_only is True
    assert candidate.production_authorized is False
    assert candidate.source_restoration_authorized is False
    assert candidate.fresh_replay_ready is False
    assert candidate.formal_eligible is False
    assert candidate.artifact_closure_candidate is True


def test_candidate_strict_restore_rederives_hashes_and_rejects_forgery() -> None:
    candidate = _candidate()
    restored = SimulatedSelfContainedSourceClosureCandidateV3.restore(
        candidate.to_dict()
    )
    assert restored == candidate

    forged = deepcopy(candidate.to_dict())
    forged["wheel_bytes_base64"] = base64.b64encode(b"changed").decode("ascii")
    with pytest.raises(SelfContainedClosureCandidateError, match="hash|source"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)

    for field, value in (
        ("production_authorized", True),
        ("source_restoration_authorized", True),
        ("fresh_replay_ready", True),
        ("formal_eligible", True),
        ("claim_scope", "formal_result"),
        ("candidate_hash", "b" * 64),
    ):
        forged = candidate.to_dict()
        forged[field] = value
        with pytest.raises(
            SelfContainedClosureCandidateError, match="derived|authority|hash"
        ):
            SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)


def test_candidate_rejects_unknown_fields_noncanonical_entries_and_path_ids() -> None:
    candidate = _candidate()

    forged = candidate.to_dict()
    forged["unexpected"] = 1
    with pytest.raises(SelfContainedClosureCandidateError, match="fields"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)

    forged = candidate.to_dict()
    forged["closure_id"] = "../checkout"
    with pytest.raises(SelfContainedClosureCandidateError, match="closure_id"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)

    forged = candidate.to_dict()
    forged["resolver_id"] = "/tmp/current-checkout"
    with pytest.raises(SelfContainedClosureCandidateError, match="resolver_id"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)

    forged = candidate.to_dict()
    forged["dependency_artifacts"] = [
        {**forged["dependency_artifacts"][0], "name": "../current-checkout"},
    ]
    with pytest.raises(SelfContainedClosureCandidateError, match="dependency name"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)

    dependency = candidate.to_dict()["dependency_artifacts"][0]
    forged = candidate.to_dict()
    forged["dependency_artifacts"] = [
        {**dependency, "artifact_sha256": 1},
    ]
    with pytest.raises(SelfContainedClosureCandidateError, match="digest"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore(forged)


def test_candidate_does_not_serialize_paths_or_raw_runtime_secrets() -> None:
    encoded = str(_candidate().to_dict())
    assert "/Users/" not in encoded
    assert "access_token" not in encoded
    assert "secret" not in encoded


def test_candidate_factory_rejects_untyped_dependency_entries_cleanly() -> None:
    base = _candidate()
    with pytest.raises(SelfContainedClosureCandidateError, match="dependency artifact"):
        SimulatedSelfContainedSourceClosureCandidateV3.create(
            closure_id=base.closure_id,
            source_lock_bytes=base.source_lock_bytes,
            wheel_bytes=base.wheel_bytes,
            sdist_bytes=base.sdist_bytes,
            dependency_lock_bytes=base.dependency_lock_bytes,
            dependency_artifacts=(object(),),
            environment_bytes=base.environment_bytes,
            build_metadata_bytes=base.build_metadata_bytes,
            resolver_id=base.resolver_id,
            resolver_version=base.resolver_version,
        )


def test_candidate_canonical_bytes_codec_rejects_duplicate_and_noncanonical_json() -> (
    None
):
    candidate = _candidate()
    raw = candidate.to_canonical_bytes()
    assert (
        SimulatedSelfContainedSourceClosureCandidateV3.restore_from_canonical_bytes(raw)
        == candidate
    )

    with pytest.raises(SelfContainedClosureCandidateError, match="canonical"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore_from_canonical_bytes(
            raw + b"\n"
        )

    duplicate = b'{"schema":"x","schema":"y"}'
    with pytest.raises(SelfContainedClosureCandidateError, match="duplicate|canonical"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore_from_canonical_bytes(
            duplicate
        )

    forged = json.loads(raw)
    forged["fresh_replay_ready"] = True
    forged_raw = json.dumps(forged, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(SelfContainedClosureCandidateError, match="derived|authority"):
        SimulatedSelfContainedSourceClosureCandidateV3.restore_from_canonical_bytes(
            forged_raw
        )
