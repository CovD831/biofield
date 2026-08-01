from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_formal_runner import (
    FailureCode,
    FormalArmRequest,
    FormalFailureArtifact,
)
from biofield.meas0_gold_outcome_adapter_v3 import (
    derive_v3_gold_bound_arm_case_outcome,
)
from biofield.meas0_input_manifest import FailurePolicyContract
from biofield.meas0_v3_outcome_package import (
    SimulatedRetainedFailureBoundOutcomeV3,
    SimulatedV3OutcomePackage,
    V3OutcomePackageError,
    compose_simulated_v3_outcome_package,
    derive_simulated_retained_failure_bound_outcome,
)
from test_meas0_formal_outcomes import _build_formal_fixture
from test_meas0_gold_facts_v3 import _derive, _gold_sources
from test_meas0_retained_failure_v3 import (
    _attempts_and_ledger,
    _budget_manifest,
    _pre_ledger,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@pytest.fixture(scope="module")
def gold_leaves(tmp_path_factory: pytest.TempPathFactory):
    _, _, _, legacy_package = _build_formal_fixture(tmp_path_factory)
    gold_sources = _gold_sources()
    leaves = []
    for artifact_facts, detection_record in zip(
        legacy_package.artifact_facts,
        legacy_package.detection_records,
        strict=True,
    ):
        case = next(
            item
            for item in formal_attack_manifest("pilot").cases
            if item.case_id == artifact_facts.case_id
        )
        facts = _derive({**gold_sources, "case_identity": case})
        leaves.append(
            derive_v3_gold_bound_arm_case_outcome(
                artifact_facts=artifact_facts,
                detection_record=detection_record,
                gold_facts=facts,
                gold_artifact=gold_sources["gold_artifact"],
                pilot_readiness=gold_sources["pilot_readiness"],
                input_manifest=gold_sources["input_manifest"],
            )
        )
    return tuple(leaves)


def test_v3_package_closes_exact_180_nonclaim_gold_leaves(gold_leaves) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)

    assert isinstance(package, SimulatedV3OutcomePackage)
    assert package.case_count == 36
    assert package.arm_case_count == 180
    assert package.claim_scope == "simulated_nonclaim"
    assert package.test_only is True
    assert package.formal_eligible is False
    assert package.production_authorized is False
    assert "formal_result" not in package.to_dict()


def test_v3_package_strict_restore_and_resigning_fail(gold_leaves) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)
    restored = SimulatedV3OutcomePackage.restore_from_typed_sources(
        package.to_dict(),
        leaves=gold_leaves,
    )
    assert restored == package

    forged = deepcopy(package.to_dict())
    forged["leaves"][0]["gold_status"] = "fail"
    with pytest.raises(V3OutcomePackageError, match="typed|source|package"):
        SimulatedV3OutcomePackage.restore_from_typed_sources(
            forged,
            leaves=gold_leaves,
        )

    with pytest.raises(V3OutcomePackageError, match="factory|coverage|order"):
        replace(package, leaves=package.leaves[1:] + package.leaves[:1])


def test_v3_package_canonical_bytes_round_trip_requires_typed_leaves(
    gold_leaves,
) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)
    raw = package.to_canonical_bytes()

    restored = SimulatedV3OutcomePackage.restore_from_canonical_bytes(
        raw,
        leaves=gold_leaves,
    )

    assert isinstance(raw, bytes)
    assert restored == package
    assert raw == json.dumps(
        package.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_v3_package_canonical_bytes_file_round_trip_is_typed_source_bound(
    gold_leaves,
    tmp_path,
) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)
    path = tmp_path / "simulated-v3-outcome-package.json"
    path.write_bytes(package.to_canonical_bytes())

    restored = SimulatedV3OutcomePackage.restore_from_canonical_bytes(
        path.read_bytes(),
        leaves=tuple(gold_leaves),
    )

    assert restored == package
    assert path.read_bytes() == package.to_canonical_bytes()


def test_v3_package_canonical_bytes_rejects_duplicate_noncanonical_and_nonfinite(
    gold_leaves,
) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)
    raw = package.to_canonical_bytes()

    duplicate = raw[:-1] + b',"package_hash":"' + package.package_hash.encode() + b'"}'
    with pytest.raises(V3OutcomePackageError, match="duplicate|JSON|canonical"):
        SimulatedV3OutcomePackage.restore_from_canonical_bytes(
            duplicate,
            leaves=gold_leaves,
        )

    with pytest.raises(V3OutcomePackageError, match="canonical"):
        SimulatedV3OutcomePackage.restore_from_canonical_bytes(
            json.dumps(package.to_dict(), indent=2).encode("utf-8"),
            leaves=gold_leaves,
        )

    nonfinite = raw.replace(
        b'"case_count":36',
        b'"case_count":NaN',
        1,
    )
    with pytest.raises(V3OutcomePackageError, match="finite|JSON|canonical"):
        SimulatedV3OutcomePackage.restore_from_canonical_bytes(
            nonfinite,
            leaves=gold_leaves,
        )


def test_v3_package_canonical_bytes_rederives_authority_and_hash(gold_leaves) -> None:
    package = compose_simulated_v3_outcome_package(gold_leaves)
    encoded = json.loads(package.to_canonical_bytes())

    for field, value in (
        ("production_authorized", True),
        ("formal_eligible", True),
        ("claim_scope", "formal_result"),
        ("package_hash", "f" * 64),
    ):
        tampered = dict(encoded)
        tampered[field] = value
        tampered_bytes = json.dumps(
            tampered,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        with pytest.raises(V3OutcomePackageError, match="typed|source|package|hash"):
            SimulatedV3OutcomePackage.restore_from_canonical_bytes(
                tampered_bytes,
                leaves=gold_leaves,
            )


def test_v3_package_rejects_missing_duplicate_or_cross_case_leaf(gold_leaves) -> None:
    with pytest.raises(V3OutcomePackageError, match="180|coverage"):
        compose_simulated_v3_outcome_package(gold_leaves[:-1])
    with pytest.raises(V3OutcomePackageError, match="coverage|order"):
        compose_simulated_v3_outcome_package(
            (gold_leaves[0], gold_leaves[0], *gold_leaves[2:])
        )
    with pytest.raises(V3OutcomePackageError, match="coverage|order"):
        compose_simulated_v3_outcome_package(
            (gold_leaves[1], gold_leaves[0], *gold_leaves[2:])
        )


def test_retained_failure_leaf_is_nonclaim_and_never_detected() -> None:
    assert SimulatedRetainedFailureBoundOutcomeV3.__name__.endswith("V3")
    # A raw retained-failure object is not enough to enter the package: the
    # package boundary requires the extra typed input/readiness ancestry.
    from test_meas0_retained_failure_v3 import _outcome_sources
    from biofield.meas0_retained_failure_v3 import RetainedFailureOutcome

    outcome = RetainedFailureOutcome.create(**_outcome_sources(FailureCode.TIMEOUT))
    with pytest.raises(V3OutcomePackageError, match="leaf type"):
        compose_simulated_v3_outcome_package((outcome,) * 180)


def test_typed_retained_failure_leaf_can_mix_with_gold(gold_leaves) -> None:
    gold_sources = _gold_sources()
    gold_leaf = gold_leaves[0]
    artifact_facts = gold_leaf.artifact_facts
    failure_policy = FailurePolicyContract.frozen_v1()
    budget_manifest = _budget_manifest()
    pre_ledger = _pre_ledger(budget_manifest)
    request = FormalArmRequest(
        authorization_hash=artifact_facts.authorization_hash,
        execution_index=0,
        case=gold_leaf.case,
        arm_id=gold_leaf.arm_id,
        task_hash=artifact_facts.canonical_bundle_hash,
        episode_hash=artifact_facts.canonical_episode_hash,
        failure_policy_hash=failure_policy.contract_hash,
        semantic_leaf_count=max(1, artifact_facts.all_formal_leaves),
        measurement_count=2,
        budget_policy_hash="3" * 64,
        price_manifest_hash=pre_ledger.price_manifest_hash,
        stage_budget_manifest_hash=pre_ledger.budget_manifest.contract_hash,
        stage_cost_pre_ledger_hash=pre_ledger.contract_hash,
    )
    attempts, ledger = _attempts_and_ledger(
        request=request,
        stage_cost_pre_ledger=pre_ledger,
        failure_reason=FailureCode.PROVIDER_ERROR.value,
    )
    failure = FormalFailureArtifact(
        code=FailureCode.PROVIDER_ERROR,
        message="terminal provider_error",
    )
    from biofield.meas0_retained_failure_v3 import RetainedFailureOutcome

    retained = RetainedFailureOutcome.create(
        request=request,
        failure=failure,
        failure_policy=failure_policy,
        attempts=attempts,
        stage_cost_pre_ledger=pre_ledger,
        stage_cost_ledger=ledger,
        terminal_reason=failure.message,
        successful_result=None,
    )
    retained_leaf = derive_simulated_retained_failure_bound_outcome(
        artifact_facts=artifact_facts,
        detection_record=None,
        retained_failure=retained,
        pilot_readiness=gold_sources["pilot_readiness"],
        input_manifest=gold_sources["input_manifest"],
    )
    mixed = compose_simulated_v3_outcome_package((retained_leaf, *gold_leaves[1:]))
    assert mixed.leaves[0].variant == "retained_failure"
    assert mixed.leaves[0].formal_eligible is False
    assert mixed.leaves[0].retained_failure.detected is None
