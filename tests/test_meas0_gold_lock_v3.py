from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from biofield.meas0_gold_lock_v3 import (
    GoldOrderLockError,
    SimulatedGoldOrderLockReceipt,
    create_simulated_gold_order_lock_receipt,
)
from biofield.meas0_phase_readiness import PhaseReadinessStage
from test_meas0_gold_facts_v3 import _gold_sources


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _receipt(sources=None) -> SimulatedGoldOrderLockReceipt:
    values = sources or _gold_sources(include_gold_order_lock=False)
    return create_simulated_gold_order_lock_receipt(
        pre_jcal_readiness=values["pre_jcal_readiness"],
        pilot_readiness=values["pilot_readiness"],
        gold_scope=values["gold_scope"],
        gold_artifact=values["gold_artifact"],
        gold_records=values["gold_records"],
        reviewer_records=values["reviewer_records"],
        adjudication_records=values["adjudication_records"],
    )


def _restore(payload, sources):
    return SimulatedGoldOrderLockReceipt.restore_from_sources(
        payload,
        pre_jcal_readiness=sources["pre_jcal_readiness"],
        pilot_readiness=sources["pilot_readiness"],
        gold_scope=sources["gold_scope"],
        gold_artifact=sources["gold_artifact"],
        gold_records=sources["gold_records"],
        reviewer_records=sources["reviewer_records"],
        adjudication_records=sources["adjudication_records"],
    )


def test_receipt_binds_exact_gold_membership_and_readiness_order() -> None:
    sources = _gold_sources(include_gold_order_lock=False)
    receipt = _receipt(sources)

    assert receipt.pre_jcal_readiness_hash == sources["pre_jcal_readiness"].receipt_hash
    assert (
        receipt.pre_jcal_target_hash == sources["pre_jcal_readiness"].target.target_hash
    )
    assert receipt.pilot_readiness_hash == sources["pilot_readiness"].receipt_hash
    assert receipt.pilot_target_hash == sources["pilot_readiness"].target.target_hash
    assert receipt.gold_scope_hash == sources["gold_scope"].contract_hash
    assert receipt.gold_artifact_manifest_hash == sources["gold_artifact"].contract_hash
    assert receipt.gold_record_hashes == tuple(
        item.contract_hash for item in sources["gold_records"]
    )
    assert receipt.reviewer_record_hashes == tuple(
        item.contract_hash for item in sources["reviewer_records"]
    )
    assert receipt.adjudication_record_hashes == tuple(
        item.contract_hash for item in sources["adjudication_records"]
    )
    assert receipt.structural_order == (
        "pre_jcal_readiness",
        "gold_scope",
        "gold_records",
        "blind_reviews",
        "adjudications",
        "gold_artifact",
        "pilot_target",
        "pilot_readiness",
        "gold_order_lock_receipt",
    )
    assert receipt.append_only_structural_order_only is True
    assert receipt.trusted_time_verified is False
    assert receipt.signature_verified is False
    assert receipt.production_authorized is False
    assert receipt.claim_scope == "simulated_nonclaim"
    assert receipt.test_only is True
    assert _restore(receipt.to_dict(), sources) == receipt


def test_direct_construction_and_replace_rehash_fail_closed() -> None:
    sources = _gold_sources(include_gold_order_lock=False)
    receipt = _receipt(sources)

    with pytest.raises(GoldOrderLockError, match="factory"):
        SimulatedGoldOrderLockReceipt(
            **{
                field_name: getattr(receipt, field_name)
                for field_name in receipt.__dataclass_fields__
                if not field_name.startswith("_")
            }
        )

    with pytest.raises(GoldOrderLockError, match="typed sources|factory-derived"):
        replace(receipt, comparison_block_id="other-block")

    payload = deepcopy(receipt.to_dict())
    payload["gold_record_hashes"][0] = "f" * 64
    body = dict(payload)
    body.pop("receipt_hash")
    payload["receipt_hash"] = _canonical_hash(body)
    with pytest.raises(GoldOrderLockError, match="typed sources"):
        _restore(payload, sources)


def test_strict_restore_rejects_shape_and_scalar_type_confusion() -> None:
    sources = _gold_sources(include_gold_order_lock=False)
    payload = _receipt(sources).to_dict()

    unknown = {**payload, "unknown": "field"}
    with pytest.raises(GoldOrderLockError, match="typed sources"):
        _restore(unknown, sources)

    missing = dict(payload)
    missing.pop("pilot_target_hash")
    with pytest.raises(GoldOrderLockError, match="typed sources"):
        _restore(missing, sources)

    confused = {**payload, "test_only": 1}
    with pytest.raises(GoldOrderLockError, match="typed sources"):
        _restore(confused, sources)


@pytest.mark.parametrize(
    ("name", "collection_name"),
    (
        ("Gold", "gold_records"),
        ("review", "reviewer_records"),
        ("adjudication", "adjudication_records"),
    ),
)
def test_missing_extra_reordered_or_cross_membership_fails_closed(
    name,
    collection_name,
) -> None:
    sources = _gold_sources(include_gold_order_lock=False)
    values = sources[collection_name]

    attacks = [values[:-1], (*values, values[-1])]
    if len(values) > 1:
        attacks.append(tuple(reversed(values)))
    for changed in attacks:
        attacked = dict(sources)
        attacked[collection_name] = changed
        with pytest.raises(GoldOrderLockError, match=f"{name}|membership|artifact"):
            _receipt(attacked)


def test_cross_block_and_cross_readiness_chain_fail_closed() -> None:
    sources = _gold_sources(include_gold_order_lock=False)
    cross_block = dict(sources)
    cross_block["gold_artifact"] = replace(
        sources["gold_artifact"],
        comparison_block_id="other-block",
    )
    with pytest.raises(GoldOrderLockError, match="comparison block"):
        _receipt(cross_block)

    wrong_order = dict(sources)
    wrong_order["pre_jcal_readiness"] = sources["pilot_readiness"]
    with pytest.raises(GoldOrderLockError, match="PRE_JCAL_READY"):
        _receipt(wrong_order)

    wrong_order = dict(sources)
    wrong_order["pilot_readiness"] = sources["pre_jcal_readiness"]
    with pytest.raises(GoldOrderLockError, match="PILOT_READY"):
        _receipt(wrong_order)

    forged_parent = replace(
        sources["pilot_readiness"],
        previous_receipt_hash="f" * 64,
        _expected_previous_receipt_hash="f" * 64,
    )
    wrong_chain = dict(sources)
    wrong_chain["pilot_readiness"] = forged_parent
    with pytest.raises(GoldOrderLockError, match="append-only|previous"):
        _receipt(wrong_chain)


def test_receipt_has_no_trusted_time_or_signature_claim() -> None:
    receipt = _receipt()
    payload = receipt.to_dict()

    assert receipt.pre_jcal_stage is PhaseReadinessStage.PRE_JCAL_READY
    assert receipt.pilot_stage is PhaseReadinessStage.PILOT_READY
    assert "timestamp" not in " ".join(payload).lower()
    assert "signed_at" not in payload
    assert payload["trusted_time_verified"] is False
    assert payload["signature_verified"] is False
    assert payload["production_authorized"] is False
