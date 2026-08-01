from __future__ import annotations

from copy import deepcopy

import pytest

from biofield.meas0_formal_lifecycle import (
    FormalLifecycleError,
    PhaseCheckpointTarget,
    authorize_simulated_phase_checkpoint,
)
from biofield.meas0_phase_readiness import (
    PhaseCompletionDisposition,
    PhaseReadinessError,
    PhaseReadinessReceipt,
    PhaseReadinessStage,
    SimulatedPhaseCompletion,
    create_simulated_phase_readiness_receipt,
    record_simulated_phase_completion,
    validate_phase_readiness_chain,
)
from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)


def _hash(character: str) -> str:
    return character * 64


def _bindings(checkpoint: AuthorizationCheckpoint) -> dict[str, str]:
    names = {
        AuthorizationCheckpoint.PRE_JCAL: (
            "human_trust_policy",
            "jcal_manifest",
            "judge_identity_manifest",
            "judge_specification",
            "precalibration_lock",
            "price_manifest",
            "stage_budget_manifest",
            "transport_trust_policy",
        ),
        AuthorizationCheckpoint.PILOT_START: (
            "formal_oracle_authority",
            "gold_binding",
            "isolation_preflight",
            "jcal_invocation",
            "jcal_qualification",
            "jcal_stage_cost",
            "jcal_transport",
            "pilot_input_manifest",
            "pilot_lock",
            "precalibration_lock",
            "provider_manifest",
        ),
        AuthorizationCheckpoint.POST_PILOT_JAUDIT: (
            "confirmatory_lock",
            "jaudit_manifest",
            "pilot_package",
            "unchanged_design_surface",
        ),
        AuthorizationCheckpoint.CONFIRMATORY_START: (
            "confirmatory_lock",
            "confirmatory_input_manifest",
            "confirmatory_plan",
            "jaudit_invocation",
            "jaudit_qualification",
            "jaudit_stage_cost",
            "jaudit_transport",
            "provider_manifest",
        ),
    }[checkpoint]
    return {name: f"{index + 1:064x}" for index, name in enumerate(names)}


def _target(
    checkpoint: AuthorizationCheckpoint,
    *,
    previous: PhaseCheckpointTarget | None,
    ledger_head: str,
    comparison_block_id: str = "pytest.meas0.v3.block",
) -> PhaseCheckpointTarget:
    return PhaseCheckpointTarget.create(
        checkpoint=checkpoint,
        lifecycle_id="pytest.meas0.v3.lifecycle",
        comparison_block_id=comparison_block_id,
        authority_role_id="approval-authority-e",
        design_hash=_hash("a"),
        source_lock_hash=_hash("b"),
        common_ancestry_hash=_hash("c"),
        ledger_pre_head_hash=ledger_head,
        evidence_bindings=_bindings(checkpoint),
        previous_target=previous,
    )


def _authorization(target: PhaseCheckpointTarget):
    verification = VerificationResult(
        schema_version=1,
        verified=True,
        production_authorized=False,
        claim_scope="contract_only",
        mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        policy_hash=_hash("8"),
        root_manifest_hash=_hash("9"),
        payload_hash=target.target_hash,
        envelope_hash=_hash("7"),
        blockers=(),
    )
    return authorize_simulated_phase_checkpoint(
        target=target,
        verification=verification,
    )


def _chain():
    receipts: list[PhaseReadinessReceipt] = []
    completions: list[SimulatedPhaseCompletion] = []
    previous_target = None
    previous_receipt = None
    previous_completion = None
    ledger_heads = (_hash("d"), _hash("e"), _hash("f"), _hash("0"))
    for index, checkpoint in enumerate(AuthorizationCheckpoint):
        target = _target(
            checkpoint,
            previous=previous_target,
            ledger_head=ledger_heads[index],
        )
        receipt = create_simulated_phase_readiness_receipt(
            target=target,
            authorization=_authorization(target),
            stage_evidence_hashes=dict(target.evidence_bindings),
            previous_receipt=previous_receipt,
            previous_completion=previous_completion,
        )
        receipts.append(receipt)
        if index < len(ledger_heads) - 1:
            completion = record_simulated_phase_completion(
                receipt=receipt,
                disposition=PhaseCompletionDisposition.ADVANCED,
                evidence_hash=chr(ord("4") + index) * 64,
                ledger_head_hash=ledger_heads[index + 1],
            )
            completions.append(completion)
            previous_completion = completion
        previous_receipt = receipt
        previous_target = target
    return tuple(receipts), tuple(completions)


def test_phase_receipts_are_append_only_strict_and_simulated_nonclaim() -> None:
    receipts, completions = _chain()

    assert tuple(item.stage for item in receipts) == tuple(PhaseReadinessStage)
    assert tuple(item.authorized_next_action for item in receipts) == (
        "run_jcal",
        "run_pilot",
        "run_jaudit",
        "run_confirmatory",
    )
    assert all(item.claim_scope == "simulated_nonclaim" for item in receipts)
    assert all(item.production_authorized is False for item in receipts)
    assert all(item.test_only is True for item in receipts)
    assert all("formal_result" not in item.to_dict() for item in receipts)
    assert validate_phase_readiness_chain(receipts, completions) == receipts
    assert tuple(
        PhaseReadinessReceipt.from_dict(item.to_dict()) for item in receipts
    ) == (receipts)
    assert (
        tuple(
            SimulatedPhaseCompletion.from_dict(item.to_dict()) for item in completions
        )
        == completions
    )


def test_receipt_codec_rejects_unknown_missing_and_hash_tamper() -> None:
    receipt = _chain()[0][1]

    unknown = deepcopy(receipt.to_dict())
    unknown["ready"] = True
    with pytest.raises(PhaseReadinessError, match="fields"):
        PhaseReadinessReceipt.from_dict(unknown)

    missing = deepcopy(receipt.to_dict())
    del missing["authorized_next_action"]
    with pytest.raises(PhaseReadinessError, match="fields"):
        PhaseReadinessReceipt.from_dict(missing)

    tampered = deepcopy(receipt.to_dict())
    tampered["ledger_head_hash"] = _hash("6")
    with pytest.raises(PhaseReadinessError, match="hash|ledger"):
        PhaseReadinessReceipt.from_dict(tampered)


def test_each_stage_rejects_future_missing_or_substituted_evidence() -> None:
    first_target = _target(
        AuthorizationCheckpoint.PRE_JCAL,
        previous=None,
        ledger_head=_hash("d"),
    )
    authorization = _authorization(first_target)

    future = dict(first_target.evidence_bindings)
    future["jcal_qualification"] = _hash("f")
    with pytest.raises(PhaseReadinessError, match="stage-available"):
        create_simulated_phase_readiness_receipt(
            target=first_target,
            authorization=authorization,
            stage_evidence_hashes=future,
            previous_receipt=None,
            previous_completion=None,
        )

    missing = dict(first_target.evidence_bindings)
    missing.pop("jcal_manifest")
    with pytest.raises(PhaseReadinessError, match="stage-available"):
        create_simulated_phase_readiness_receipt(
            target=first_target,
            authorization=authorization,
            stage_evidence_hashes=missing,
            previous_receipt=None,
            previous_completion=None,
        )

    substituted = dict(first_target.evidence_bindings)
    substituted["jcal_manifest"] = _hash("f")
    with pytest.raises(PhaseReadinessError, match="stage-available"):
        create_simulated_phase_readiness_receipt(
            target=first_target,
            authorization=authorization,
            stage_evidence_hashes=substituted,
            previous_receipt=None,
            previous_completion=None,
        )


def test_later_stage_rejects_jump_cross_block_and_wrong_ledger_parent() -> None:
    receipts, completions = _chain()
    first = receipts[0]
    first_completion = completions[0]
    pilot_target = receipts[1].target

    with pytest.raises(PhaseReadinessError, match="previous receipt"):
        create_simulated_phase_readiness_receipt(
            target=pilot_target,
            authorization=_authorization(pilot_target),
            stage_evidence_hashes=dict(pilot_target.evidence_bindings),
            previous_receipt=None,
            previous_completion=None,
        )

    other_first_target = _target(
        AuthorizationCheckpoint.PRE_JCAL,
        previous=None,
        ledger_head=_hash("d"),
        comparison_block_id="pytest.other.block",
    )
    other_first = create_simulated_phase_readiness_receipt(
        target=other_first_target,
        authorization=_authorization(other_first_target),
        stage_evidence_hashes=dict(other_first_target.evidence_bindings),
        previous_receipt=None,
        previous_completion=None,
    )
    other_completion = record_simulated_phase_completion(
        receipt=other_first,
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash("4"),
        ledger_head_hash=pilot_target.ledger_pre_head_hash,
    )
    with pytest.raises(PhaseReadinessError, match="ancestry|previous target"):
        create_simulated_phase_readiness_receipt(
            target=pilot_target,
            authorization=_authorization(pilot_target),
            stage_evidence_hashes=dict(pilot_target.evidence_bindings),
            previous_receipt=other_first,
            previous_completion=other_completion,
        )

    wrong_ledger = record_simulated_phase_completion(
        receipt=first,
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=first_completion.evidence_hash,
        ledger_head_hash=_hash("6"),
    )
    with pytest.raises(PhaseReadinessError, match="ledger"):
        create_simulated_phase_readiness_receipt(
            target=pilot_target,
            authorization=_authorization(pilot_target),
            stage_evidence_hashes=dict(pilot_target.evidence_bindings),
            previous_receipt=first,
            previous_completion=wrong_ledger,
        )


@pytest.mark.parametrize(
    "disposition",
    [
        PhaseCompletionDisposition.FAILED,
        PhaseCompletionDisposition.QUARANTINED,
    ],
)
def test_later_stage_rejects_failed_or_quarantined_parent(disposition) -> None:
    receipts, _ = _chain()
    first = receipts[0]
    parent = record_simulated_phase_completion(
        receipt=first,
        disposition=disposition,
        evidence_hash=_hash("4"),
        ledger_head_hash=receipts[1].target.ledger_pre_head_hash,
    )

    with pytest.raises(PhaseReadinessError, match="advanced"):
        create_simulated_phase_readiness_receipt(
            target=receipts[1].target,
            authorization=_authorization(receipts[1].target),
            stage_evidence_hashes=dict(receipts[1].target.evidence_bindings),
            previous_receipt=first,
            previous_completion=parent,
        )


def test_authorization_target_substitution_and_future_target_fail_closed() -> None:
    receipts, _ = _chain()
    target = receipts[0].target
    other_target = _target(
        AuthorizationCheckpoint.PRE_JCAL,
        previous=None,
        ledger_head=target.ledger_pre_head_hash,
        comparison_block_id="pytest.other.block",
    )
    with pytest.raises(PhaseReadinessError, match="authorization target"):
        create_simulated_phase_readiness_receipt(
            target=target,
            authorization=_authorization(other_target),
            stage_evidence_hashes=dict(target.evidence_bindings),
            previous_receipt=None,
            previous_completion=None,
        )

    with pytest.raises(FormalLifecycleError, match="previous target"):
        _target(
            AuthorizationCheckpoint.POST_PILOT_JAUDIT,
            previous=target,
            ledger_head=_hash("e"),
        )
