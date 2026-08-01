from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace

import pytest

from biofield.meas0 import Meas0Arm
from biofield.meas0_budget import (
    BudgetFailureArtifact,
    BudgetFailureCode,
    BudgetScope,
)
from biofield.meas0_failure_evidence_v3 import (
    BackendInvalidEvidenceV3,
    FailureEvidenceV3Error,
    MalformedResponseEvidenceV3,
    ProtocolViolationEvidenceV3,
    StageBudgetExhaustedEvidenceV3,
    BudgetExhaustedEvidenceV3,
)
from biofield.meas0_formal_runner import FailureCode, FormalFailureArtifact
from biofield.meas0_retained_failure_v3 import (
    RetainedFailureAttempt,
    RetainedFailureError,
    RetainedFailureOutcome,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    StageBudgetManifest,
    StageCostLedger,
)
from biofield.meas0_trust import (
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportClaimScope,
    TransportOutcome,
)

from test_meas0_retained_failure_v3 import (
    _attempts_and_ledger,
    _budget_manifest,
    _outcome_sources,
    _pre_ledger,
    _request,
)
from biofield.meas0_input_manifest import FailurePolicyContract


def _failure(code: FailureCode) -> FormalFailureArtifact:
    return FormalFailureArtifact(code=code, message=f"terminal {code.value}")


def _response_bearing_malformed_sources(raw_response: bytes):
    sources = _outcome_sources(FailureCode.MALFORMED_RESPONSE)
    old_attempt = sources["attempts"][0]
    judge = old_attempt.judge_attempt
    old_receipt = judge.transport_receipt
    payload = replace(
        old_receipt.payload,
        claim_scope=TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION,
        outcome=TransportOutcome.SUCCESS,
        failure_code=None,
        response_hash=hashlib.sha256(raw_response).hexdigest(),
        response_size=len(raw_response),
        http_status=200,
        tls_certificate_sha256="c" * 64,
        tls_spki_sha256="d" * 64,
        tls_chain_sha256="e" * 64,
        tls_verification_result=TLSVerificationResult.VERIFIED,
    )
    receipt = SignedTransportReceipt(
        payload=payload,
        envelope=replace(
            old_receipt.envelope,
            payload_hash=payload.contract_hash,
        ),
    )
    judge = replace(judge, transport_receipt=receipt)
    entry = replace(
        old_attempt.stage_cost_entry,
        outcome=CostOutcome.SUCCEEDED,
        failure_code=None,
        call_hash=payload.contract_hash,
        raw_receipt_hash=receipt.contract_hash,
        bytes_transferred=len(raw_response),
    )
    attempt = RetainedFailureAttempt.create(
        attempt_index=0,
        judge_attempt=judge,
        stage_cost_entry=entry,
    )
    pre = sources["stage_cost_pre_ledger"]
    ledger = StageCostLedger(
        ledger_id=pre.ledger_id,
        version=pre.version,
        price_manifest_hash=pre.price_manifest_hash,
        budget_manifest=pre.budget_manifest,
        entries=(entry,),
    )
    return {
        **sources,
        "attempts": (attempt,),
        "stage_cost_ledger": ledger,
    }


def _stage_stopped_sources():
    original = _budget_manifest()
    phase_budgets = tuple(
        replace(
            item,
            max_calls=0,
            category_call_caps=tuple(
                CategoryCallCap(
                    category=category,
                    max_calls=0 if category is CostCategory.JUDGE else 10,
                )
                for category in CostCategory
            ),
        )
        if item.phase == "pilot"
        else item
        for item in original.phase_budgets
    )
    manifest = StageBudgetManifest(
        manifest_id="pytest.stage-stop-budget.v3",
        version=1,
        phase_budgets=phase_budgets,
    )
    empty = _pre_ledger(manifest, ledger_id="pytest.stage-stop-ledger.v3")
    policy = FailurePolicyContract.frozen_v1()
    trigger_request = _request(
        failure_policy=policy,
        stage_cost_pre_ledger=empty,
    )
    _, stopped = _attempts_and_ledger(
        request=trigger_request,
        stage_cost_pre_ledger=empty,
        failure_reason=FailureCode.PROVIDER_ERROR.value,
    )
    assert stopped.phase_decision("pilot").stopped
    request = _request(
        failure_policy=policy,
        stage_cost_pre_ledger=stopped,
    )
    return policy, request, stopped


def test_each_p0_c_code_has_one_exact_tagged_typed_evidence() -> None:
    raw_response = b"{not-json"
    malformed_sources = _response_bearing_malformed_sources(raw_response)
    malformed_attempt = malformed_sources["attempts"][0]
    malformed = MalformedResponseEvidenceV3.create(
        request=malformed_sources["request"],
        failure=malformed_sources["failure"],
        judge_attempt=malformed_attempt.judge_attempt,
        stage_cost_entry=malformed_attempt.stage_cost_entry,
        raw_response=raw_response,
        parser_id="strict-json",
        parser_version="1",
        parser_error_code="invalid_json",
    )

    budget_sources = _outcome_sources(
        FailureCode.BUDGET_EXHAUSTED,
        attempt_count=0,
    )
    request = budget_sources["request"]
    budget = BudgetExhaustedEvidenceV3.create(
        request=request,
        failure=budget_sources["failure"],
        budget_failure=BudgetFailureArtifact(
            case_id=request.case.case_id,
            task_id=request.case.task_id,
            arm=Meas0Arm(request.arm_id),
            code=BudgetFailureCode.BUDGET_EXHAUSTED,
            scope=BudgetScope.ARM_CASE,
            metric="judge_calls",
            limit=2,
            observed=3,
        ),
    )

    _, stage_request, stopped = _stage_stopped_sources()
    stage = StageBudgetExhaustedEvidenceV3.create(
        request=stage_request,
        failure=_failure(FailureCode.STAGE_BUDGET_EXHAUSTED),
        stage_cost_ledger=stopped,
    )
    protocol = ProtocolViolationEvidenceV3.create(
        request=request,
        failure=_failure(FailureCode.PROTOCOL_VIOLATION),
        violated_invariant="request_ancestry",
        observed_request=replace(request, task_hash="f" * 64),
    )

    assert [item.tag for item in (malformed, budget, stage, protocol)] == [
        "malformed_response",
        "budget_exhausted",
        "stage_budget_exhausted",
        "protocol_violation",
    ]
    for item in (malformed, budget, stage, protocol):
        assert item.failure_code.value == item.tag
        assert item.claim_scope == "simulated_nonclaim"
        assert item.production_authorized is False
        assert item.test_only is True
        assert item.terminal_reason_is_detection is False
        assert item.evidence_hash


def test_failure_evidence_rejects_code_tag_and_request_substitution() -> None:
    sources = _outcome_sources(
        FailureCode.BUDGET_EXHAUSTED,
        attempt_count=0,
    )
    request = sources["request"]
    artifact = BudgetFailureArtifact(
        case_id=request.case.case_id,
        task_id=request.case.task_id,
        arm=Meas0Arm(request.arm_id),
        code=BudgetFailureCode.BUDGET_EXHAUSTED,
        scope=BudgetScope.ARM_CASE,
        metric="judge_calls",
        limit=2,
        observed=3,
    )
    with pytest.raises(FailureEvidenceV3Error):
        BudgetExhaustedEvidenceV3.create(
            request=request,
            failure=_failure(FailureCode.PROTOCOL_VIOLATION),
            budget_failure=artifact,
        )
    evidence = BudgetExhaustedEvidenceV3.create(
        request=request,
        failure=sources["failure"],
        budget_failure=artifact,
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            **{
                **sources,
                "request": replace(request, task_hash="f" * 64),
            },
            failure_evidence=evidence,
        )


@pytest.mark.parametrize(
    ("code", "factory"),
    (
        (
            FailureCode.BUDGET_EXHAUSTED,
            lambda request, failure, ledger: BudgetExhaustedEvidenceV3.create(
                request=request,
                failure=failure,
                budget_failure=BudgetFailureArtifact(
                    case_id=request.case.case_id,
                    task_id=request.case.task_id,
                    arm=Meas0Arm(request.arm_id),
                    code=BudgetFailureCode.BUDGET_EXHAUSTED,
                    scope=BudgetScope.ARM_CASE,
                    metric="judge_calls",
                    limit=2,
                    observed=3,
                ),
            ),
        ),
        (
            FailureCode.PROTOCOL_VIOLATION,
            lambda request, failure, ledger: ProtocolViolationEvidenceV3.create(
                request=request,
                failure=failure,
                violated_invariant="request_ancestry",
                observed_request=replace(request, task_hash="f" * 64),
            ),
        ),
    ),
)
def test_legal_no_attempt_failure_is_retained_without_fake_receipt_or_zero_cost(
    code: FailureCode,
    factory,
) -> None:
    sources = _outcome_sources(code, attempt_count=0)
    evidence = factory(
        sources["request"],
        sources["failure"],
        sources["stage_cost_pre_ledger"],
    )
    outcome = RetainedFailureOutcome.create(
        **sources,
        failure_evidence=evidence,
    )
    assert outcome.attempts == ()
    assert outcome.receipt_hashes == ()
    assert outcome.stage_cost_entry_hashes == ()
    assert outcome.stage_cost_ledger_hash == outcome.stage_cost_pre_ledger_hash
    assert outcome.failure_evidence_hash == evidence.evidence_hash
    assert outcome.accepted is outcome.detected is outcome.judge_verdict is None


def test_stage_budget_no_attempt_requires_a_typed_stopped_preledger() -> None:
    policy, request, stopped = _stage_stopped_sources()
    failure = _failure(FailureCode.STAGE_BUDGET_EXHAUSTED)
    evidence = StageBudgetExhaustedEvidenceV3.create(
        request=request,
        failure=failure,
        stage_cost_ledger=stopped,
    )
    outcome = RetainedFailureOutcome.create(
        request=request,
        failure=failure,
        failure_policy=policy,
        attempts=(),
        stage_cost_pre_ledger=stopped,
        stage_cost_ledger=stopped,
        terminal_reason=failure.message,
        successful_result=None,
        failure_evidence=evidence,
    )
    assert outcome.attempts == ()
    assert evidence.trigger_entry_hash
    assert evidence.exceeded_dimensions

    with pytest.raises(FailureEvidenceV3Error):
        StageBudgetExhaustedEvidenceV3.create(
            request=request,
            failure=failure,
            stage_cost_ledger=StageCostLedger(
                ledger_id=stopped.ledger_id,
                version=stopped.version,
                price_manifest_hash=stopped.price_manifest_hash,
                budget_manifest=_budget_manifest(),
                entries=(),
            ),
        )


def test_malformed_evidence_binds_real_attempt_and_cannot_be_no_attempt() -> None:
    raw_response = b"{not-json"
    sources = _response_bearing_malformed_sources(raw_response)
    attempt = sources["attempts"][0]
    evidence = MalformedResponseEvidenceV3.create(
        request=sources["request"],
        failure=sources["failure"],
        judge_attempt=attempt.judge_attempt,
        stage_cost_entry=attempt.stage_cost_entry,
        raw_response=raw_response,
        parser_id="strict-json",
        parser_version="1",
        parser_error_code="invalid_json",
    )
    outcome = RetainedFailureOutcome.create(
        **sources,
        failure_evidence=evidence,
    )
    assert evidence.no_attempt is False
    assert outcome.receipt_hashes == (attempt.receipt_hash,)
    assert outcome.stage_cost_entry_hashes == (attempt.stage_cost_entry_hash,)


def test_malformed_rejects_failed_response_absent_receipt_plus_arbitrary_bytes() -> (
    None
):
    sources = _outcome_sources(FailureCode.MALFORMED_RESPONSE)
    attempt = sources["attempts"][0]
    assert attempt.judge_attempt.transport_receipt.payload.response_hash is None
    with pytest.raises(FailureEvidenceV3Error):
        MalformedResponseEvidenceV3.create(
            request=sources["request"],
            failure=sources["failure"],
            judge_attempt=attempt.judge_attempt,
            stage_cost_entry=attempt.stage_cost_entry,
            raw_response=b"caller-selected unrelated bytes",
            parser_id="strict-json",
            parser_version="1",
            parser_error_code="invalid_json",
        )


def test_malformed_rejects_bytes_not_identical_to_signed_response_hash_and_size() -> (
    None
):
    sources = _response_bearing_malformed_sources(b"{signed-response")
    attempt = sources["attempts"][0]
    with pytest.raises(FailureEvidenceV3Error):
        MalformedResponseEvidenceV3.create(
            request=sources["request"],
            failure=sources["failure"],
            judge_attempt=attempt.judge_attempt,
            stage_cost_entry=attempt.stage_cost_entry,
            raw_response=b"{different-parser-input",
            parser_id="strict-json",
            parser_version="1",
            parser_error_code="invalid_json",
        )


def test_protocol_expected_authority_is_derived_from_request_not_caller_hash() -> None:
    sources = _outcome_sources(
        FailureCode.PROTOCOL_VIOLATION,
        attempt_count=0,
    )
    parameters = inspect.signature(ProtocolViolationEvidenceV3.create).parameters
    assert "expected_contract_hash" not in parameters
    evidence = ProtocolViolationEvidenceV3.create(
        request=sources["request"],
        failure=sources["failure"],
        violated_invariant="request_ancestry",
        observed_request=replace(sources["request"], task_hash="f" * 64),
    )
    assert evidence.expected_contract_hash == sources["request"].request_hash


def test_protocol_fails_closed_without_supported_typed_authorities() -> None:
    sources = _outcome_sources(
        FailureCode.PROTOCOL_VIOLATION,
        attempt_count=0,
    )
    with pytest.raises(FailureEvidenceV3Error):
        ProtocolViolationEvidenceV3.create(
            request=sources["request"],
            failure=sources["failure"],
            violated_invariant="evaluator_binding",
            observed_request=replace(sources["request"], task_hash="f" * 64),
        )
    with pytest.raises(FailureEvidenceV3Error):
        ProtocolViolationEvidenceV3.create(
            request=sources["request"],
            failure=sources["failure"],
            violated_invariant="request_ancestry",
            observed_request=b"caller bytes",
        )


def test_backend_invalid_fails_closed_without_request_bound_expected_authority() -> (
    None
):
    sources = _outcome_sources(
        FailureCode.BACKEND_INVALID,
        attempt_count=0,
    )
    with pytest.raises(FailureEvidenceV3Error, match="schema gap"):
        BackendInvalidEvidenceV3.create(
            request=sources["request"],
            failure=sources["failure"],
            invalid_surface="backend_descriptor",
            expected_contract_hash="a" * 64,
            observed_artifact=b"caller-selected backend bytes",
        )


def test_terminal_reason_never_becomes_detection_and_success_cannot_coexist() -> None:
    sources = _outcome_sources(
        FailureCode.PROTOCOL_VIOLATION,
        attempt_count=0,
    )
    evidence = ProtocolViolationEvidenceV3.create(
        request=sources["request"],
        failure=sources["failure"],
        violated_invariant="request_ancestry",
        observed_request=replace(sources["request"], task_hash="f" * 64),
    )
    with pytest.raises(RetainedFailureError):
        RetainedFailureOutcome.create(
            **{**sources, "successful_result": object()},
            failure_evidence=evidence,
        )
    outcome = RetainedFailureOutcome.create(
        **sources,
        failure_evidence=evidence,
    )
    assert outcome.terminal_reason == sources["failure"].message
    assert outcome.detected is None
    assert "detected" in outcome.not_observed_fields


def test_failure_evidence_restore_is_exact_and_rejects_resigned_tag_tamper() -> None:
    sources = _outcome_sources(
        FailureCode.PROTOCOL_VIOLATION,
        attempt_count=0,
    )
    typed_sources = {
        "request": sources["request"],
        "failure": sources["failure"],
        "violated_invariant": "request_ancestry",
        "observed_request": replace(sources["request"], task_hash="f" * 64),
    }
    evidence = ProtocolViolationEvidenceV3.create(**typed_sources)
    assert (
        ProtocolViolationEvidenceV3.restore_from_typed_sources(
            evidence.to_dict(),
            **typed_sources,
        )
        == evidence
    )
    raw = evidence.to_dict()
    raw["tag"] = FailureCode.BACKEND_INVALID.value
    with pytest.raises(FailureEvidenceV3Error):
        ProtocolViolationEvidenceV3.restore_from_typed_sources(
            raw,
            **typed_sources,
        )


def test_no_attempt_outcome_strict_restore_rederives_typed_failure_evidence() -> None:
    sources = _outcome_sources(
        FailureCode.PROTOCOL_VIOLATION,
        attempt_count=0,
    )
    evidence = ProtocolViolationEvidenceV3.create(
        request=sources["request"],
        failure=sources["failure"],
        violated_invariant="request_ancestry",
        observed_request=replace(sources["request"], task_hash="f" * 64),
    )
    outcome = RetainedFailureOutcome.create(
        **sources,
        failure_evidence=evidence,
    )
    restored = RetainedFailureOutcome.restore_from_typed_sources(
        outcome.to_dict(),
        request=sources["request"],
        failure=sources["failure"],
        failure_policy=sources["failure_policy"],
        judge_attempts=(),
        stage_cost_entries=(),
        stage_cost_pre_ledger=sources["stage_cost_pre_ledger"],
        stage_cost_ledger=sources["stage_cost_ledger"],
        failure_evidence=evidence,
    )
    assert restored == outcome
