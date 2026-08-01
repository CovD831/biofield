from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_formal_lifecycle import (
    ExperimentClaimState,
    FormalLifecycleError,
    GateMClaimState,
    LifecycleEvidenceClass,
    LifecycleStage,
    LifecycleTerminalStatus,
    StageAuthorizationReceipt,
    StageQualificationReceipt,
    advance_lifecycle,
    fail_lifecycle,
    replay_lifecycle,
    replay_lifecycle_from_canonical_bytes,
    start_lifecycle,
)
from biofield.meas0_readiness import JudgeQualification, RateEstimate
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    PHASES,
    PhaseBudget,
    StageBudgetManifest,
    StageCostEntry,
    StageCostLedger,
)
from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    AuthorizationCheckpointManifest,
    AuthorizationCheckpointRequirement,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)


def _hash(character: str) -> str:
    return character * 64


def _budgets(*, stopped_phase: str | None = None) -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id="pytest.lifecycle-budget.v1",
        version=1,
        phase_budgets=tuple(
            PhaseBudget(
                phase=phase,
                max_calls=0 if phase == stopped_phase else 100,
                max_input_tokens=1_000,
                max_output_tokens=1_000,
                max_wall_time_ms=10_000,
                max_bytes_transferred=10_000,
                max_retries=10,
                max_monetary_microunits=10_000,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(
                        category=category,
                        max_calls=0
                        if phase == stopped_phase and category is CostCategory.JUDGE
                        else 100,
                    )
                    for category in CostCategory
                ),
            )
            for phase in PHASES
        ),
    )


def _ledgers(
    *,
    stopped_phase: str | None = None,
    failed_phase: str | None = None,
) -> tuple[StageCostLedger, ...]:
    budget = _budgets(stopped_phase=stopped_phase)
    entries: list[StageCostEntry] = []
    ledgers = [
        StageCostLedger(
            ledger_id="pytest.lifecycle-ledger.v1",
            version=1,
            price_manifest_hash=_hash("a"),
            budget_manifest=budget,
            entries=(),
        )
    ]
    for sequence, phase in enumerate(PHASES):
        outcome = CostOutcome.FAILED if phase == failed_phase else CostOutcome.SUCCEEDED
        entry = StageCostEntry(
            entry_id=f"{phase}-attempt",
            sequence=sequence,
            phase=phase,
            category=CostCategory.JUDGE,
            outcome=outcome,
            failure_code="provider_error" if outcome is CostOutcome.FAILED else None,
            request_hash=("b", "c", "d", "e")[sequence] * 64,
            call_hash=("5", "6", "7", "8")[sequence] * 64,
            raw_receipt_hash=("9", "a", "b", "c")[sequence] * 64,
            calls=1,
            input_tokens=1,
            output_tokens=1,
            wall_time_ms=1,
            bytes_transferred=1,
            retry_count=0,
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=phase in {"pilot", "confirmatory"},
            arm_id="judge_only" if phase in {"pilot", "confirmatory"} else None,
            provider_id="pytest-judge",
            model_id="pytest-model",
            cost_class="judge",
            retry_of_entry_hash=None,
            previous_entry_hash=(entries[-1].contract_hash if entries else None),
        )
        entries.append(entry)
        ledgers.append(
            StageCostLedger(
                ledger_id="pytest.lifecycle-ledger.v1",
                version=1,
                price_manifest_hash=_hash("a"),
                budget_manifest=budget,
                entries=tuple(entries),
            )
        )
        if stopped_phase == phase:
            break
    return tuple(ledgers)


def _manifest(ledgers: tuple[StageCostLedger, ...]) -> AuthorizationCheckpointManifest:
    checkpoints = (
        AuthorizationCheckpoint.PRE_JCAL,
        AuthorizationCheckpoint.PILOT_START,
        AuthorizationCheckpoint.POST_PILOT_JAUDIT,
        AuthorizationCheckpoint.CONFIRMATORY_START,
    )
    phases = ("jcal", "pilot", "jaudit", "confirmatory")
    return AuthorizationCheckpointManifest(
        schema_version=1,
        manifest_id="pytest.lifecycle-checkpoints.v1",
        requirements=tuple(
            AuthorizationCheckpointRequirement(
                checkpoint=checkpoint,
                phase=phase,
                purpose=checkpoint.value,
                role_id=f"authority-{index}",
                authorization_target_hash=chr(ord("a") + index) * 64,
                ledger_pre_head_hash=ledgers[index].contract_hash,
            )
            for index, (checkpoint, phase) in enumerate(
                zip(checkpoints, phases, strict=True)
            )
        ),
    )


def _authorization_receipts(
    manifest: AuthorizationCheckpointManifest,
) -> tuple[StageAuthorizationReceipt, ...]:
    return tuple(
        StageAuthorizationReceipt.from_verification(
            requirement=requirement,
            verification=VerificationResult(
                schema_version=1,
                verified=True,
                production_authorized=False,
                claim_scope="contract_only",
                mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
                trust_domain=TrustDomain.HUMAN_APPROVAL,
                policy_hash=_hash("5"),
                root_manifest_hash=_hash("6"),
                payload_hash=requirement.payload_hash,
                envelope_hash=("5", "6", "7", "8")[index] * 64,
                blockers=(),
            ),
        )
        for index, requirement in enumerate(manifest.requirements)
    )


def _qualification(
    set_kind: str,
    *,
    qualified: bool = True,
) -> StageQualificationReceipt:
    good = RateEstimate(value=0.0, lower=0.0, upper=0.0, denominator=48)
    perfect = RateEstimate(value=1.0, lower=1.0, upper=1.0, denominator=48)
    qualification = JudgeQualification(
        qualification_id=f"pytest-{set_kind}",
        judge_card_hash=_hash("8"),
        set_kind=set_kind,
        set_hash=_hash("9"),
        schema_valid=perfect,
        false_accept=(
            good
            if qualified
            else RateEstimate(value=0.2, lower=0.2, upper=0.2, denominator=48)
        ),
        false_reject=good,
        unknown_rate=good,
        order_flip=good,
        style_flip=good,
        repeat_disagreement=good,
        evidence_reference_validity=perfect,
        evaluated_at="2026-07-31T00:00:00Z",
    )
    return StageQualificationReceipt.from_test_qualification(
        qualification=qualification,
        source_evidence_hash=_hash("e"),
    )


def _closed_lifecycle():
    ledgers = _ledgers()
    manifest = _manifest(ledgers)
    authorizations = _authorization_receipts(manifest)
    jcal = _qualification("J-CAL-v1")
    jaudit = _qualification("J-AUDIT-v1")
    lifecycle = start_lifecycle(
        lifecycle_id="pytest-lifecycle",
        checkpoint_manifest=manifest,
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[0],
        authorization_receipt=authorizations[0],
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[1],
        authorization_receipt=authorizations[1],
        qualification_receipt=jcal,
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[2],
        authorization_receipt=authorizations[2],
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[3],
        authorization_receipt=authorizations[3],
        qualification_receipt=jaudit,
    )
    lifecycle = advance_lifecycle(lifecycle, ledger=ledgers[4])
    return lifecycle, manifest, ledgers, authorizations, (jcal, jaudit)


def test_full_test_only_lifecycle_closes_without_formal_claims() -> None:
    lifecycle, _, _, _, _ = _closed_lifecycle()

    assert lifecycle.stage is LifecycleStage.CLOSED
    assert lifecycle.terminal_status is LifecycleTerminalStatus.CLOSED
    assert tuple(record.to_stage for record in lifecycle.records) == (
        LifecycleStage.JCAL,
        LifecycleStage.PILOT,
        LifecycleStage.JAUDIT,
        LifecycleStage.CONFIRMATORY,
        LifecycleStage.CLOSED,
    )
    assert lifecycle.gate_m_claim is GateMClaimState.NOT_EVALUATED
    assert lifecycle.pilot_claim is ExperimentClaimState.CONTRACT_ONLY
    assert lifecycle.confirmatory_claim is ExperimentClaimState.CONTRACT_ONLY
    assert lifecycle.formal_evidence is False
    assert all(
        record.authorization_evidence_class in {None, LifecycleEvidenceClass.TEST_ONLY}
        for record in lifecycle.records
    )
    assert all(
        record.qualification_evidence_class in {None, LifecycleEvidenceClass.TEST_ONLY}
        for record in lifecycle.records
    )


def test_budget_decision_stops_and_terminal_lifecycle_cannot_reopen() -> None:
    ledgers = _ledgers(stopped_phase="jcal")
    manifest = _manifest((ledgers[0], ledgers[1], ledgers[1], ledgers[1]))
    receipt = _authorization_receipts(manifest)[0]
    lifecycle = start_lifecycle(
        lifecycle_id="pytest-stopped",
        checkpoint_manifest=manifest,
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[0],
        authorization_receipt=receipt,
    )
    stopped = advance_lifecycle(
        lifecycle,
        ledger=ledgers[1],
        qualification_receipt=_qualification("J-CAL-v1"),
        authorization_receipt=_authorization_receipts(manifest)[1],
    )

    assert stopped.terminal_status is LifecycleTerminalStatus.STOPPED
    assert stopped.records[-1].budget_trigger_entry_hash is not None
    with pytest.raises(FormalLifecycleError, match="terminal"):
        advance_lifecycle(stopped, ledger=ledgers[1])


def test_unqualified_receipt_derives_quarantine_without_caller_status() -> None:
    ledgers = _ledgers()
    manifest = _manifest(ledgers)
    receipts = _authorization_receipts(manifest)
    lifecycle = start_lifecycle(
        lifecycle_id="pytest-quarantine",
        checkpoint_manifest=manifest,
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[0],
        authorization_receipt=receipts[0],
    )
    quarantined = advance_lifecycle(
        lifecycle,
        ledger=ledgers[1],
        authorization_receipt=receipts[1],
        qualification_receipt=_qualification(
            "J-CAL-v1",
            qualified=False,
        ),
    )

    assert quarantined.terminal_status is LifecycleTerminalStatus.QUARANTINED
    assert quarantined.stage is LifecycleStage.JCAL
    assert quarantined.formal_evidence is False


def test_failed_status_is_derived_from_failed_stage_cost_entry() -> None:
    ledgers = _ledgers(failed_phase="pilot")
    manifest = _manifest(ledgers)
    receipts = _authorization_receipts(manifest)
    lifecycle = start_lifecycle(
        lifecycle_id="pytest-failed",
        checkpoint_manifest=manifest,
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[0],
        authorization_receipt=receipts[0],
    )
    lifecycle = advance_lifecycle(
        lifecycle,
        ledger=ledgers[1],
        authorization_receipt=receipts[1],
        qualification_receipt=_qualification("J-CAL-v1"),
    )
    failed_entry = ledgers[2].entries[-1]
    failed = fail_lifecycle(
        lifecycle,
        ledger=ledgers[2],
        failure_entry_hash=failed_entry.contract_hash,
    )

    assert failed.terminal_status is LifecycleTerminalStatus.FAILED
    assert failed.records[-1].failure_entry_hash == failed_entry.contract_hash
    with pytest.raises(FormalLifecycleError, match="failed StageCost"):
        fail_lifecycle(
            lifecycle,
            ledger=ledgers[2],
            failure_entry_hash=ledgers[2].entries[0].contract_hash,
        )


def test_checkpoint_order_skip_and_wrong_ledger_ancestry_fail_closed() -> None:
    ledgers = _ledgers()
    manifest = _manifest(ledgers)
    receipts = _authorization_receipts(manifest)
    lifecycle = start_lifecycle(
        lifecycle_id="pytest-order",
        checkpoint_manifest=manifest,
    )

    with pytest.raises(FormalLifecycleError, match="checkpoint"):
        advance_lifecycle(
            lifecycle,
            ledger=ledgers[0],
            authorization_receipt=receipts[1],
        )
    with pytest.raises(FormalLifecycleError, match="ledger pre-head"):
        advance_lifecycle(
            lifecycle,
            ledger=ledgers[1],
            authorization_receipt=receipts[0],
        )
    with pytest.raises(FormalLifecycleError, match="qualification"):
        advance_lifecycle(
            lifecycle,
            ledger=ledgers[0],
            authorization_receipt=receipts[0],
            qualification_receipt=_qualification("J-CAL-v1"),
        )


def test_roundtrip_replays_typed_ancestry_and_rejects_tamper() -> None:
    lifecycle, manifest, ledgers, authorizations, qualifications = _closed_lifecycle()
    restored = replay_lifecycle(
        lifecycle.to_dict(),
        checkpoint_manifest=manifest,
        ledgers=ledgers,
        authorization_receipts=authorizations,
        qualification_receipts=qualifications,
    )
    assert restored == lifecycle
    assert restored.lifecycle_hash == lifecycle.lifecycle_hash

    tampered = lifecycle.to_dict()
    tampered["records"][2]["previous_record_hash"] = _hash("f")
    with pytest.raises(FormalLifecycleError, match="hash|ancestry"):
        replay_lifecycle(
            tampered,
            checkpoint_manifest=manifest,
            ledgers=ledgers,
            authorization_receipts=authorizations,
            qualification_receipts=qualifications,
        )

    relabeled = lifecycle.to_dict()
    relabeled["records"][0]["authorization_evidence_class"] = "production"
    with pytest.raises(FormalLifecycleError, match="hash|derived|state"):
        replay_lifecycle(
            relabeled,
            checkpoint_manifest=manifest,
            ledgers=ledgers,
            authorization_receipts=authorizations,
            qualification_receipts=qualifications,
        )

    reordered = lifecycle.to_dict()
    reordered["records"][1], reordered["records"][2] = (
        reordered["records"][2],
        reordered["records"][1],
    )
    with pytest.raises(FormalLifecycleError, match="order|stage|hash"):
        replay_lifecycle(
            reordered,
            checkpoint_manifest=manifest,
            ledgers=ledgers,
            authorization_receipts=authorizations,
            qualification_receipts=qualifications,
        )


def test_canonical_bytes_roundtrip_supports_fresh_process_boundary(tmp_path) -> None:
    lifecycle, manifest, ledgers, authorizations, qualifications = _closed_lifecycle()
    path = tmp_path / "lifecycle.json"
    raw_bytes = lifecycle.to_canonical_bytes()
    path.write_bytes(raw_bytes)

    restored = replay_lifecycle_from_canonical_bytes(
        path.read_bytes(),
        checkpoint_manifest=manifest,
        ledgers=ledgers,
        authorization_receipts=authorizations,
        qualification_receipts=qualifications,
    )
    assert restored == lifecycle
    assert restored.to_canonical_bytes() == raw_bytes

    tampered = bytearray(raw_bytes)
    tampered[-2] = ord("0") if tampered[-2] != ord("0") else ord("1")
    with pytest.raises(FormalLifecycleError, match="canonical|hash|derived|strict"):
        replay_lifecycle_from_canonical_bytes(
            bytes(tampered),
            checkpoint_manifest=manifest,
            ledgers=ledgers,
            authorization_receipts=authorizations,
            qualification_receipts=qualifications,
        )

    with pytest.raises(FormalLifecycleError, match="canonical"):
        replay_lifecycle_from_canonical_bytes(
            raw_bytes + b"\n",
            checkpoint_manifest=manifest,
            ledgers=ledgers,
            authorization_receipts=authorizations,
            qualification_receipts=qualifications,
        )


def test_receipts_and_lifecycle_cannot_be_directly_forged() -> None:
    qualification = _qualification("J-CAL-v1")
    with pytest.raises(FormalLifecycleError, match="factory"):
        replace(qualification, _derivation_token=None)
    with pytest.raises(FormalLifecycleError, match="production"):
        replace(qualification, test_only=False)

    _, manifest, _, authorizations, _ = _closed_lifecycle()
    with pytest.raises(FormalLifecycleError, match="derived|production"):
        StageQualificationReceipt.from_derived_qualification(
            evidence=object(),
            production_attestation=authorizations[0].verification,
        )

    lifecycle, _, _, _, _ = _closed_lifecycle()
    with pytest.raises(FormalLifecycleError, match="derived"):
        replace(lifecycle, _derivation_token=None)
