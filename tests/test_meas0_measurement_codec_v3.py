from __future__ import annotations

import json

import pytest

from biofield.measurement import (
    EvaluationStatus,
    fuse_evidence,
    seal_task_measurement_bundle,
)
from biofield.meas0_formal_runner import CanonicalEvaluationBinding
from biofield.meas0_measurement_codec_v3 import (
    MEASUREMENT_CODEC_BOUNDARY,
    MeasurementCodecError,
    restore_canonical_evaluation_binding,
    restore_canonical_evaluation_binding_bytes,
    restore_measurement_observation,
    restore_measurement_graph,
    restore_requirement_graph,
    restore_sealed_episode,
    restore_task_measurement_bundle,
)
from test_measurement import (
    _goal_graph,
    _measurement_graph,
    _observation,
    _requirement_graph,
    _sealed_episode,
    _sealed_task_measurement_bundle,
    _task_frame,
)


def _binding() -> CanonicalEvaluationBinding:
    bundle = _sealed_task_measurement_bundle()
    episode = _sealed_episode(bundle=bundle)
    observations = (_observation("state-check", EvaluationStatus.PASS),)
    result = fuse_evidence(
        result_id="pytest.codec.result",
        task_measurement_bundle=bundle,
        sealed_episode=episode,
        observations=observations,
    )
    return CanonicalEvaluationBinding(
        task_measurement_bundle=bundle,
        sealed_episode=episode,
        observations=observations,
        evaluation_result=result,
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_codec_restores_minimal_typed_closure_by_canonical_factories() -> None:
    binding = _binding()
    raw = binding.to_dict()

    bundle = restore_task_measurement_bundle(raw["task_measurement_bundle"])
    bundle_from_bytes = restore_task_measurement_bundle(
        _canonical_bytes(raw["task_measurement_bundle"])
    )
    episode = restore_sealed_episode(raw["sealed_episode"], bundle=bundle)
    observation = restore_measurement_observation(raw["observations"][0])
    restored = restore_canonical_evaluation_binding(raw)
    restored_from_bytes = restore_canonical_evaluation_binding_bytes(
        _canonical_bytes(raw)
    )

    assert bundle == binding.task_measurement_bundle
    assert bundle_from_bytes == bundle
    assert episode == binding.sealed_episode
    assert observation == binding.observations[0]
    assert restored == binding
    assert restored_from_bytes == binding
    assert MEASUREMENT_CODEC_BOUNDARY.claim_scope == "simulated_nonclaim"
    assert MEASUREMENT_CODEC_BOUNDARY.production_authorized is False
    assert MEASUREMENT_CODEC_BOUNDARY.test_only is True


def test_codec_rejects_unknown_missing_bool_int_enum_and_nonfinite() -> None:
    raw = _binding().to_dict()

    unknown = dict(raw)
    unknown["production_authorized"] = True
    with pytest.raises(MeasurementCodecError, match="fields"):
        restore_canonical_evaluation_binding(unknown)

    missing = dict(raw)
    missing.pop("evaluation_result")
    with pytest.raises(MeasurementCodecError, match="fields"):
        restore_canonical_evaluation_binding(missing)

    confused = json.loads(json.dumps(raw))
    confused["task_measurement_bundle"]["task_frame"]["version"] = True
    with pytest.raises(MeasurementCodecError):
        restore_canonical_evaluation_binding(confused)

    bad_enum = json.loads(json.dumps(raw))
    bad_enum["observations"][0]["status"] = "probably"
    with pytest.raises(MeasurementCodecError):
        restore_canonical_evaluation_binding(bad_enum)

    nonfinite = json.loads(json.dumps(raw))
    nonfinite["observations"][0]["cost"] = float("nan")
    with pytest.raises(MeasurementCodecError):
        restore_canonical_evaluation_binding(nonfinite)


def test_codec_preserves_legal_integer_numeric_values() -> None:
    requirement_raw = _requirement_graph().to_dict()
    for item in requirement_raw["requirements"]:
        item["weight"] = int(item["weight"])
    requirement_graph = restore_requirement_graph(requirement_raw)

    measurement_raw = _measurement_graph().to_dict()
    for item in measurement_raw["measurement_specs"]:
        item["expected_coverage"] = int(item["expected_coverage"])
        item["cost_estimate"] = int(item["cost_estimate"])
    measurement_raw["normal_coverage_threshold"] = 1
    measurement_graph = restore_measurement_graph(measurement_raw)

    bundle = seal_task_measurement_bundle(
        bundle_id="pytest.integer-numeric.bundle",
        version=1,
        task_frame=_task_frame(),
        goal_graph=_goal_graph(),
        requirement_graph=requirement_graph,
        measurement_graph=measurement_graph,
        acceptance_rules=("all decisive measurements pass",),
        deterministic_check_refs=tuple(
            item.evaluator_ref
            for item in measurement_graph.measurement_specs
            if item.kind.value == "deterministic"
        ),
        judge_refs=tuple(
            item.evaluator_ref
            for item in measurement_graph.measurement_specs
            if item.kind.value == "judge"
        ),
        metamorphic_relations=(),
        uncertainty_and_escalation_rules=("missing is unknown",),
        measurement_budget=10,
        provenance=("pytest",),
    )
    assert restore_task_measurement_bundle(bundle.to_dict()) == bundle

    observation_raw = _observation("state-check", EvaluationStatus.PASS).to_dict()
    observation_raw["coverage"] = 1
    observation_raw["uncertainty"] = 0
    observation_raw["cost"] = 1
    assert restore_measurement_observation(observation_raw).to_dict() == (
        observation_raw
    )


def test_codec_rejects_duplicate_noncanonical_and_order_tamper_bytes() -> None:
    raw = _binding().to_dict()
    canonical = _canonical_bytes(raw)

    duplicate = canonical[:-1] + b',"evaluation_result":{}}'
    with pytest.raises(MeasurementCodecError, match="duplicate|JSON"):
        restore_canonical_evaluation_binding_bytes(duplicate)

    with pytest.raises(MeasurementCodecError, match="canonical"):
        restore_canonical_evaluation_binding_bytes(json.dumps(raw, indent=2).encode())

    reordered = json.loads(json.dumps(raw))
    reordered["sealed_episode"]["episode_graph"]["evidence"].reverse()
    with pytest.raises(MeasurementCodecError):
        restore_canonical_evaluation_binding(reordered)


def test_bundle_episode_hash_and_persisted_evaluation_are_not_trusted() -> None:
    raw = json.loads(json.dumps(_binding().to_dict()))
    raw["task_measurement_bundle"]["bundle_hash"] = "f" * 64
    with pytest.raises(MeasurementCodecError, match="bundle|source-derived"):
        restore_canonical_evaluation_binding(raw)

    raw = json.loads(json.dumps(_binding().to_dict()))
    raw["sealed_episode"]["episode_hash"] = "f" * 64
    with pytest.raises(MeasurementCodecError, match="episode|source-derived"):
        restore_canonical_evaluation_binding(raw)

    raw = json.loads(json.dumps(_binding().to_dict()))
    raw["evaluation_result"]["outcome"] = "pass"
    with pytest.raises(MeasurementCodecError, match="fusion|source-derived"):
        restore_canonical_evaluation_binding(raw)
