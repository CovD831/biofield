from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace

import pytest

from biofield.measurement import EvaluationStatus
from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_formal_runner import (
    FailureCode,
    FormalArmRequest,
    FormalFailureArtifact,
    JudgeCallCostArtifact,
    ResultValidity,
)
from biofield.meas0_input_manifest import FailurePolicyContract
from biofield.meas0_retained_failure_v3 import (
    RetainedFailureAttempt,
    RetainedFailureError,
    RetainedFailureOutcome,
    RetainedFailureOutcomeIndex,
    project_failure_disposition,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    PhaseBudget,
    StageBudgetManifest,
    StageCostEntry,
    StageCostLedger,
)
from biofield.meas0_trust import (
    SignatureEnvelope,
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportBatchEntry,
    TransportClaimScope,
    TransportOutcome,
    TransportReceiptPayload,
    TrustDomain,
)


def _hash(character: str) -> str:
    return character * 64


def _budget_manifest(*, max_retries: int = 2) -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id="pytest.retained-failure-budget.v3",
        version=1,
        phase_budgets=tuple(
            PhaseBudget(
                phase=phase,
                max_calls=10,
                max_input_tokens=1_000,
                max_output_tokens=1_000,
                max_wall_time_ms=10_000,
                max_bytes_transferred=100_000,
                max_retries=max_retries,
                max_monetary_microunits=0,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(category=category, max_calls=10)
                    for category in CostCategory
                ),
            )
            for phase in ("jcal", "pilot", "jaudit", "confirmatory")
        ),
    )


def _judge_attempt(
    *,
    sequence: int,
    authorization_hash: str,
    previous_receipt_hash: str | None,
    failure_reason: str,
    wall_time_ms: int = 5,
) -> JudgeCallCostArtifact:
    batch_entry = TransportBatchEntry(
        sequence_number=sequence,
        invocation_id=f"pytest.invocation.{sequence}",
        criterion_id=f"pytest.criterion.{sequence}",
        presentation_hash=_hash("1"),
        data_attestation_hash=_hash("2"),
        request_fingerprint=_hash("3"),
        request_bytes_hash=_hash("4"),
    )
    payload = TransportReceiptPayload(
        schema_version=1,
        receipt_id=f"pytest.receipt.{sequence}",
        claim_scope=TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION,
        provider_id="pytest.provider",
        endpoint_origin="https://provider.invalid",
        requested_model_id="pytest.model",
        observed_model_id="pytest.model",
        purpose="transport_receipt",
        phase="pilot",
        comparison_block_id="pytest.block.v3",
        comparison_lock_hash=_hash("5"),
        design_hash=_hash("6"),
        execution_authorization_hash=authorization_hash,
        invocation_id=batch_entry.invocation_id,
        criterion_id=batch_entry.criterion_id,
        presentation_hash=batch_entry.presentation_hash,
        data_attestation_hash=batch_entry.data_attestation_hash,
        request_fingerprint=batch_entry.request_fingerprint,
        request_bytes_hash=batch_entry.request_bytes_hash,
        outcome=TransportOutcome.FAILED,
        failure_code=failure_reason,
        response_hash=None,
        response_size=None,
        http_status=None,
        started_at=f"2026-07-31T00:00:0{sequence}Z",
        completed_at=f"2026-07-31T00:00:0{sequence}Z",
        nonce=f"pytest-receipt-{sequence}",
        batch_id="pytest.batch.v3",
        batch_manifest_hash=batch_entry.contract_hash,
        sequence_number=sequence,
        previous_receipt_hash=previous_receipt_hash,
        tls_peer_hostname="provider.invalid",
        tls_sni="provider.invalid",
        tls_certificate_sha256=None,
        tls_spki_sha256=None,
        tls_chain_sha256=None,
        tls_verification_result=TLSVerificationResult.NOT_ESTABLISHED,
        tls_trust_store_snapshot_hash=_hash("7"),
        tls_verification_policy_hash=_hash("8"),
    )
    receipt = SignedTransportReceipt(
        payload=payload,
        envelope=SignatureEnvelope(
            schema_version=1,
            envelope_id=f"pytest.envelope.{sequence}",
            trust_domain=TrustDomain.TRANSPORT,
            root_id="pytest.transport.root",
            root_manifest_hash=_hash("9"),
            key_fingerprint=_hash("a"),
            algorithm_id="pytest.test-only",
            role_id="pytest.transport",
            purpose=payload.purpose,
            phase=payload.phase,
            payload_hash=payload.contract_hash,
            sequence_number=sequence,
            nonce=payload.nonce,
            observed_signing_time=payload.completed_at,
            test_only=True,
            signature_hex=_hash("b"),
        ),
    )
    return JudgeCallCostArtifact(
        input_tokens=1 if wall_time_ms else 0,
        output_tokens=0,
        wall_time_ms=wall_time_ms,
        transport_batch_entry=batch_entry,
        transport_receipt=receipt,
    )


def _attempts_and_ledger(
    *,
    request: FormalArmRequest,
    stage_cost_pre_ledger: StageCostLedger,
    failure_reason: str,
    count: int = 1,
    zero_cost: bool = False,
):
    attempts = []
    entries = []
    previous_receipt_hash = None
    previous_entry_hash = (
        stage_cost_pre_ledger.entries[-1].contract_hash
        if stage_cost_pre_ledger.entries
        else None
    )
    first_entry_hash = None
    for attempt_index in range(count):
        judge_attempt = _judge_attempt(
            sequence=attempt_index,
            authorization_hash=request.authorization_hash,
            previous_receipt_hash=previous_receipt_hash,
            failure_reason=failure_reason,
            wall_time_ms=0 if zero_cost else 5,
        )
        receipt = judge_attempt.transport_receipt
        entry = StageCostEntry(
            entry_id=f"pytest.pilot.attempt.{attempt_index}",
            sequence=len(stage_cost_pre_ledger.entries) + attempt_index,
            phase="pilot",
            category=CostCategory.JUDGE,
            outcome=CostOutcome.FAILED,
            failure_code=receipt.payload.failure_code,
            request_hash=request.request_hash,
            call_hash=receipt.payload.contract_hash,
            raw_receipt_hash=receipt.contract_hash,
            calls=1,
            input_tokens=judge_attempt.input_tokens,
            output_tokens=judge_attempt.output_tokens,
            wall_time_ms=judge_attempt.wall_time_ms,
            bytes_transferred=0,
            retry_count=int(attempt_index > 0),
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=True,
            arm_id=request.arm_id,
            provider_id=receipt.payload.provider_id,
            model_id=receipt.payload.observed_model_id,
            cost_class="judge",
            retry_of_entry_hash=first_entry_hash if attempt_index > 0 else None,
            previous_entry_hash=previous_entry_hash,
        )
        if first_entry_hash is None:
            first_entry_hash = entry.contract_hash
        attempts.append(
            RetainedFailureAttempt.create(
                attempt_index=attempt_index,
                judge_attempt=judge_attempt,
                stage_cost_entry=entry,
            )
        )
        entries.append(entry)
        previous_receipt_hash = receipt.contract_hash
        previous_entry_hash = entry.contract_hash
    ledger = StageCostLedger(
        ledger_id=stage_cost_pre_ledger.ledger_id,
        version=stage_cost_pre_ledger.version,
        price_manifest_hash=stage_cost_pre_ledger.price_manifest_hash,
        budget_manifest=stage_cost_pre_ledger.budget_manifest,
        entries=(*stage_cost_pre_ledger.entries, *entries),
    )
    return tuple(attempts), ledger


def _pre_ledger(
    budget_manifest: StageBudgetManifest,
    *,
    price_manifest_hash: str = "c" * 64,
    ledger_id: str = "pytest.retained-failure-ledger.v3",
) -> StageCostLedger:
    return StageCostLedger(
        ledger_id=ledger_id,
        version=1,
        price_manifest_hash=price_manifest_hash,
        budget_manifest=budget_manifest,
        entries=(),
    )


def _request(
    *,
    failure_policy: FailurePolicyContract,
    stage_cost_pre_ledger: StageCostLedger,
) -> FormalArmRequest:
    return FormalArmRequest(
        authorization_hash=_hash("d"),
        execution_index=0,
        case=formal_attack_manifest("pilot").cases[0],
        arm_id="judge_only",
        task_hash=_hash("1"),
        episode_hash=_hash("2"),
        failure_policy_hash=failure_policy.contract_hash,
        semantic_leaf_count=1,
        measurement_count=2,
        budget_policy_hash=_hash("3"),
        price_manifest_hash=stage_cost_pre_ledger.price_manifest_hash,
        stage_budget_manifest_hash=(
            stage_cost_pre_ledger.budget_manifest.contract_hash
        ),
        stage_cost_pre_ledger_hash=stage_cost_pre_ledger.contract_hash,
    )


def _outcome(
    code: FailureCode,
    *,
    attempt_count: int = 1,
    max_retries: int = 2,
    zero_cost: bool = False,
    successful_result: object | None = None,
):
    return RetainedFailureOutcome.create(
        **_outcome_sources(
            code,
            attempt_count=attempt_count,
            max_retries=max_retries,
            zero_cost=zero_cost,
            successful_result=successful_result,
        )
    )


def _outcome_sources(
    code: FailureCode,
    *,
    attempt_count: int = 1,
    max_retries: int = 2,
    zero_cost: bool = False,
    successful_result: object | None = None,
):
    failure_policy = FailurePolicyContract.frozen_v1()
    budget_manifest = _budget_manifest(max_retries=max_retries)
    pre_ledger = _pre_ledger(budget_manifest)
    request = _request(
        failure_policy=failure_policy,
        stage_cost_pre_ledger=pre_ledger,
    )
    attempts, ledger = _attempts_and_ledger(
        request=request,
        stage_cost_pre_ledger=pre_ledger,
        failure_reason=code.value,
        count=attempt_count,
        zero_cost=zero_cost,
    )
    failure = FormalFailureArtifact(
        code=code,
        message=f"terminal {code.value}",
    )
    return {
        "request": request,
        "failure": failure,
        "failure_policy": failure_policy,
        "attempts": attempts,
        "stage_cost_pre_ledger": pre_ledger,
        "stage_cost_ledger": ledger,
        "terminal_reason": failure.message,
        "successful_result": successful_result,
    }


@pytest.mark.parametrize(
    "code",
    (
        FailureCode.TIMEOUT,
        FailureCode.PROVIDER_ERROR,
    ),
)
def test_unavailable_failures_project_to_unknown_without_verdicts(
    code: FailureCode,
) -> None:
    outcome = _outcome(code)
    assert outcome.result_validity is ResultValidity.VALID
    assert outcome.automatic_status is EvaluationStatus.UNKNOWN
    assert outcome.not_observed_fields == (
        "accepted",
        "detected",
        "judge_verdict",
    )
    assert outcome.accepted is None
    assert outcome.detected is None
    assert outcome.judge_verdict is None
    assert outcome.denominator_retained is True
    assert outcome.claim_scope == "simulated_nonclaim"
    assert outcome.production_authorized is False


@pytest.mark.parametrize(
    ("code", "validity", "status"),
    (
        (
            FailureCode.TIMEOUT,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        (
            FailureCode.PROVIDER_ERROR,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        (
            FailureCode.MALFORMED_RESPONSE,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        (
            FailureCode.BUDGET_EXHAUSTED,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        (
            FailureCode.STAGE_BUDGET_EXHAUSTED,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
        ),
        (FailureCode.BACKEND_INVALID, ResultValidity.INVALID, None),
        (FailureCode.PROTOCOL_VIOLATION, ResultValidity.INVALID, None),
    ),
)
def test_d8_projection_is_defined_for_every_frozen_failure_code(
    code: FailureCode,
    validity: ResultValidity,
    status: EvaluationStatus | None,
) -> None:
    projection = project_failure_disposition(
        FailurePolicyContract.frozen_v1(),
        code,
    )
    assert projection.result_validity is validity
    assert projection.automatic_status is status


def test_attempt_binds_receipt_stage_cost_and_ledger_ancestry() -> None:
    outcome = _outcome(FailureCode.PROVIDER_ERROR, attempt_count=2)
    assert outcome.failure_artifact.code is FailureCode.PROVIDER_ERROR
    assert outcome.failure_artifact_hash
    assert len(outcome.attempts) == 2
    assert outcome.attempts[0].stage_cost_entry_hash in outcome.stage_cost_entry_hashes
    assert outcome.attempts[1].retry_of_entry_hash == (
        outcome.attempts[0].stage_cost_entry_hash
    )
    assert outcome.retry_count == 1
    assert {
        "case",
        "arm_id",
        "authorization_hash",
        "request_hash",
    }.isdisjoint(inspect.signature(RetainedFailureOutcome.create).parameters)


def test_rejects_success_coexistence_and_missing_evidence() -> None:
    with pytest.raises(RetainedFailureError):
        _outcome(FailureCode.TIMEOUT, successful_result=object())
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            request=_request(
                failure_policy=FailurePolicyContract.frozen_v1(),
                stage_cost_pre_ledger=_pre_ledger(_budget_manifest()),
            ),
            failure=FormalFailureArtifact(
                code=FailureCode.TIMEOUT,
                message="terminal timeout",
            ),
            failure_policy=FailurePolicyContract.frozen_v1(),
            attempts=(),
            stage_cost_pre_ledger=object(),
            stage_cost_ledger=object(),
            terminal_reason="terminal timeout",
            successful_result=None,
        )
    valid = _outcome(FailureCode.TIMEOUT)
    with pytest.raises(RetainedFailureError):
        replace(valid, terminal_reason="different terminal reason")


def test_zero_numeric_cost_failed_attempt_is_still_retained() -> None:
    outcome = _outcome(FailureCode.TIMEOUT, zero_cost=True)
    entry = outcome.attempts[0].stage_cost_entry
    assert entry.calls == 1
    assert entry.outcome is CostOutcome.FAILED
    assert (
        entry.input_tokens,
        entry.output_tokens,
        entry.wall_time_ms,
        entry.bytes_transferred,
        entry.monetary_microunits,
    ) == (0, 0, 0, 0, 0)
    assert outcome.denominator_retained is True
    assert outcome.accepted is None
    assert outcome.detected is None
    assert outcome.judge_verdict is None


def test_rejects_retry_over_cap_and_tampered_receipt_or_stage_cost() -> None:
    with pytest.raises(RetainedFailureError):
        _outcome(FailureCode.PROVIDER_ERROR, attempt_count=2, max_retries=0)

    failure_policy = FailurePolicyContract.frozen_v1()
    budget_manifest = _budget_manifest()
    pre_ledger = _pre_ledger(budget_manifest)
    request = _request(
        failure_policy=failure_policy,
        stage_cost_pre_ledger=pre_ledger,
    )
    attempts, ledger = _attempts_and_ledger(
        request=request,
        stage_cost_pre_ledger=pre_ledger,
        failure_reason=FailureCode.PROVIDER_ERROR.value,
    )
    with pytest.raises(RetainedFailureError):
        replace(
            attempts[0],
            receipt_hash=_hash("f"),
        )
    successful_entry = replace(
        attempts[0].stage_cost_entry,
        outcome=CostOutcome.SUCCEEDED,
        failure_code=None,
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureAttempt.create(
            attempt_index=0,
            judge_attempt=attempts[0].judge_attempt,
            stage_cost_entry=successful_entry,
        )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            request=replace(request, task_hash=_hash("f")),
            failure=FormalFailureArtifact(
                code=FailureCode.PROVIDER_ERROR,
                message="terminal provider_error",
            ),
            failure_policy=FailurePolicyContract.frozen_v1(),
            attempts=attempts,
            stage_cost_pre_ledger=pre_ledger,
            stage_cost_ledger=ledger,
            terminal_reason="terminal provider_error",
            successful_result=None,
        )


def test_rejects_price_manifest_and_pre_ledger_substitution() -> None:
    failure_policy = FailurePolicyContract.frozen_v1()
    budget_manifest = _budget_manifest()
    pre_ledger = _pre_ledger(budget_manifest)
    request = _request(
        failure_policy=failure_policy,
        stage_cost_pre_ledger=pre_ledger,
    )
    attempts, final_ledger = _attempts_and_ledger(
        request=request,
        stage_cost_pre_ledger=pre_ledger,
        failure_reason=FailureCode.TIMEOUT.value,
    )
    failure = FormalFailureArtifact(
        code=FailureCode.TIMEOUT,
        message="terminal timeout",
    )
    kwargs = {
        "failure": failure,
        "failure_policy": failure_policy,
        "attempts": attempts,
        "stage_cost_ledger": final_ledger,
        "terminal_reason": failure.message,
        "successful_result": None,
    }
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            request=replace(request, price_manifest_hash=_hash("f")),
            stage_cost_pre_ledger=pre_ledger,
            **kwargs,
        )

    substituted_pre_ledger = _pre_ledger(
        budget_manifest,
        ledger_id="pytest.other-pre-ledger.v3",
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            request=replace(
                request,
                stage_cost_pre_ledger_hash=substituted_pre_ledger.contract_hash,
            ),
            stage_cost_pre_ledger=substituted_pre_ledger,
            **kwargs,
        )


def test_rejects_duplicate_outcome_and_unapproved_failure_value() -> None:
    outcome = _outcome(FailureCode.TIMEOUT)
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcomeIndex.create((outcome, outcome))
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            request=_request(
                failure_policy=FailurePolicyContract.frozen_v1(),
                stage_cost_pre_ledger=_pre_ledger(_budget_manifest()),
            ),
            failure=object(),
            failure_policy=FailurePolicyContract.frozen_v1(),
            attempts=outcome.attempts,
            stage_cost_pre_ledger=object(),
            stage_cost_ledger=object(),
            terminal_reason="unknown failure",
            successful_result=None,
        )


@pytest.mark.parametrize(
    "code",
    (
        FailureCode.MALFORMED_RESPONSE,
        FailureCode.BUDGET_EXHAUSTED,
        FailureCode.STAGE_BUDGET_EXHAUSTED,
        FailureCode.BACKEND_INVALID,
        FailureCode.PROTOCOL_VIOLATION,
    ),
)
def test_tagged_outcome_rejects_codes_not_proven_by_failed_transport_attempt(
    code: FailureCode,
) -> None:
    with pytest.raises(RetainedFailureError, match="cannot prove"):
        _outcome(code)


def _typed_restore_kwargs(sources: dict[str, object]) -> dict[str, object]:
    attempts = sources["attempts"]
    assert isinstance(attempts, tuple)
    return {
        "request": sources["request"],
        "failure": sources["failure"],
        "failure_policy": sources["failure_policy"],
        "judge_attempts": tuple(item.judge_attempt for item in attempts),
        "stage_cost_entries": tuple(item.stage_cost_entry for item in attempts),
        "stage_cost_pre_ledger": sources["stage_cost_pre_ledger"],
        "stage_cost_ledger": sources["stage_cost_ledger"],
    }


def _resign_outcome(value: dict[str, object]) -> None:
    body = dict(value)
    body.pop("outcome_hash")
    value["outcome_hash"] = _canonical_hash(body)


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


def test_strict_typed_source_restore_round_trip_for_attempt_outcome_and_index() -> None:
    sources = _outcome_sources(FailureCode.PROVIDER_ERROR, attempt_count=2)
    outcome = RetainedFailureOutcome.create(**sources)
    attempt = outcome.attempts[0]

    assert (
        RetainedFailureAttempt.restore_from_typed_sources(
            attempt.to_dict(),
            attempt_index=0,
            judge_attempt=attempt.judge_attempt,
            stage_cost_entry=attempt.stage_cost_entry,
        )
        == attempt
    )
    restored = RetainedFailureOutcome.restore_from_typed_sources(
        outcome.to_dict(),
        **_typed_restore_kwargs(sources),
    )
    assert restored == outcome

    index = RetainedFailureOutcomeIndex.create((outcome,))
    assert (
        RetainedFailureOutcomeIndex.restore_from_typed_sources(
            index.to_dict(),
            outcomes=(restored,),
        )
        == index
    )


def test_outcome_restore_rejects_bool_integer_retry_count_confusion() -> None:
    sources = _outcome_sources(FailureCode.PROVIDER_ERROR, attempt_count=2)
    outcome = RetainedFailureOutcome.create(**sources)
    raw = outcome.to_dict()
    raw["retry_count"] = True
    with pytest.raises(RetainedFailureError, match="exact serialization"):
        RetainedFailureOutcome.restore_from_typed_sources(
            raw,
            **_typed_restore_kwargs(sources),
        )


@pytest.mark.parametrize("mutation", ("unknown", "missing", "type_confusion"))
def test_attempt_restore_rejects_non_exact_serialized_value(mutation: str) -> None:
    attempt = _outcome(FailureCode.TIMEOUT).attempts[0]
    raw = attempt.to_dict()
    if mutation == "unknown":
        raw["unknown"] = True
    elif mutation == "missing":
        raw.pop("receipt_hash")
    else:
        raw["attempt_index"] = "0"

    with pytest.raises(RetainedFailureError):
        RetainedFailureAttempt.restore_from_typed_sources(
            raw,
            attempt_index=0,
            judge_attempt=attempt.judge_attempt,
            stage_cost_entry=attempt.stage_cost_entry,
        )
    with pytest.raises(RetainedFailureError):
        RetainedFailureAttempt.restore_from_typed_sources(
            attempt.to_dict(),
            attempt_index=0,
            judge_attempt=attempt.judge_attempt.to_dict(),
            stage_cost_entry=attempt.stage_cost_entry,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("failure_code", FailureCode.TIMEOUT.value),
        ("result_validity", ResultValidity.INVALID.value),
        ("automatic_status", None),
        ("accepted", True),
        ("detected", False),
        ("judge_verdict", "accept"),
        ("claim_scope", "production"),
    ),
)
def test_outcome_restore_rejects_self_consistent_resigned_projection_tampering(
    field: str,
    replacement: object,
) -> None:
    sources = _outcome_sources(FailureCode.PROVIDER_ERROR)
    outcome = RetainedFailureOutcome.create(**sources)
    raw = outcome.to_dict()
    raw[field] = replacement
    _resign_outcome(raw)

    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.restore_from_typed_sources(
            raw,
            **_typed_restore_kwargs(sources),
        )


def test_outcome_restore_rejects_unknown_missing_and_successful_upgrade() -> None:
    sources = _outcome_sources(FailureCode.TIMEOUT)
    outcome = RetainedFailureOutcome.create(**sources)
    for raw in (
        {**outcome.to_dict(), "unknown": True},
        {key: value for key, value in outcome.to_dict().items() if key != "tag"},
        {**outcome.to_dict(), "successful_result": {"accepted": True}},
    ):
        with pytest.raises(RetainedFailureError):
            RetainedFailureOutcome.restore_from_typed_sources(
                raw,
                **_typed_restore_kwargs(sources),
            )


def test_outcome_restore_rejects_receipt_entry_order_and_ledger_substitution() -> None:
    sources = _outcome_sources(FailureCode.PROVIDER_ERROR, attempt_count=2)
    outcome = RetainedFailureOutcome.create(**sources)
    raw = outcome.to_dict()
    raw["attempts"] = list(reversed(raw["attempts"]))
    raw["receipt_hashes"] = list(reversed(raw["receipt_hashes"]))
    raw["stage_cost_entry_hashes"] = list(reversed(raw["stage_cost_entry_hashes"]))
    _resign_outcome(raw)
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.restore_from_typed_sources(
            raw,
            **_typed_restore_kwargs(sources),
        )

    substituted_sources = dict(sources)
    substituted_sources["stage_cost_pre_ledger"] = _pre_ledger(
        _budget_manifest(),
        ledger_id="pytest.codec-substitution.v3",
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.restore_from_typed_sources(
            outcome.to_dict(),
            **_typed_restore_kwargs(substituted_sources),
        )

    substituted_sources = dict(sources)
    substituted_sources["stage_cost_ledger"] = _pre_ledger(
        _budget_manifest(),
        ledger_id="pytest.codec-final-substitution.v3",
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.restore_from_typed_sources(
            outcome.to_dict(),
            **_typed_restore_kwargs(substituted_sources),
        )


@pytest.mark.parametrize(
    "code",
    (
        FailureCode.MALFORMED_RESPONSE,
        FailureCode.BUDGET_EXHAUSTED,
        FailureCode.STAGE_BUDGET_EXHAUSTED,
        FailureCode.BACKEND_INVALID,
        FailureCode.PROTOCOL_VIOLATION,
    ),
)
def test_restore_cannot_codec_upgrade_unrepresentable_failure(
    code: FailureCode,
) -> None:
    sources = _outcome_sources(FailureCode.TIMEOUT)
    outcome = RetainedFailureOutcome.create(**sources)
    sources["failure"] = FormalFailureArtifact(
        code=code,
        message=f"terminal {code.value}",
    )
    with pytest.raises(RetainedFailureError, match="cannot prove"):
        RetainedFailureOutcome.restore_from_typed_sources(
            outcome.to_dict(),
            **_typed_restore_kwargs(sources),
        )


def test_index_restore_rejects_tamper_and_type_confusion() -> None:
    outcome = _outcome(FailureCode.TIMEOUT)
    index = RetainedFailureOutcomeIndex.create((outcome,))
    raw = index.to_dict()
    raw["index_hash"] = _hash("f")
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcomeIndex.restore_from_typed_sources(
            raw,
            outcomes=(outcome,),
        )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcomeIndex.restore_from_typed_sources(
            index.to_dict(),
            outcomes=(outcome.to_dict(),),
        )
