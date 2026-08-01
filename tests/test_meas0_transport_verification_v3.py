from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    PhaseBudget,
    StageBudgetManifest,
    StageCostEntry,
    StageCostLedger,
)
from biofield.meas0_transport_verification_v3 import (
    LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP,
    UNVERIFIED_STAGE_COST_MEASURANDS_GAP,
    PhaseTransportPolicyV3,
    SimulatedTransportReverificationV3,
    TransportVerificationV3Error,
    require_production_transport_verification_v3,
    reverify_simulated_transport_phase_v3,
)
from biofield.meas0_trust import (
    DETERMINISTIC_TEST_ALGORITHM,
    DeterministicTestSignatureVerifier,
    KeyAuthorization,
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportBatchEntry,
    TransportBatchPlan,
    TransportClaimScope,
    TransportOutcome,
    TransportReceiptBatch,
    TransportReceiptPayload,
    TransportTrustRootManifest,
    TrustDomain,
    TrustVerificationMode,
    VerificationPolicy,
)


def _hash(character: str) -> str:
    return character * 64


def _request(index: int) -> bytes:
    return f'{{"attempt":{index},"task":"pytest"}}'.encode()


def _response() -> bytes:
    return b'{"verdict":"pass"}'


def _root(*, phase: str = "pilot") -> TransportTrustRootManifest:
    return TransportTrustRootManifest(
        schema_version=1,
        root_id=f"pytest.transport.{phase}.root.v3",
        operator_id="pytest-independent-gateway",
        harness_administrative_domain="pytest-harness-admin",
        administrative_domain="pytest-gateway-admin",
        harness_security_boundary_id="pytest-harness-boundary",
        security_boundary_id="pytest-gateway-boundary",
        workload_identity="pytest-gateway-workload",
        key_custodian="pytest-test-kms",
        claim_scopes=(
            TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION,
            TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION,
        ),
        provider_id="pytest.provider",
        endpoint_origins=("https://provider.invalid",),
        model_ids=("pytest.model",),
        key_authorizations=(
            KeyAuthorization(
                key_fingerprint=_hash("1"),
                algorithm_id=DETERMINISTIC_TEST_ALGORITHM,
                role_id="pytest.transport.gateway",
                allowed_purposes=("transport_receipt",),
                allowed_phases=(phase,),
            ),
        ),
        valid_from="2026-07-31T00:00:00Z",
        valid_until="2026-08-31T00:00:00Z",
        revocation_snapshot_hash=_hash("2"),
        revoked_key_fingerprints=(),
        tls_verification_policy_hash=_hash("3"),
        reviewer_role_id="pytest-independent-root-reviewer",
        test_only=True,
    )


def _budget() -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id="pytest.transport-budget.v3",
        version=1,
        phase_budgets=tuple(
            PhaseBudget(
                phase=phase,
                max_calls=10,
                max_input_tokens=1_000,
                max_output_tokens=1_000,
                max_wall_time_ms=10_000,
                max_bytes_transferred=100_000,
                max_retries=2,
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


def _fixture() -> tuple[
    PhaseTransportPolicyV3,
    TransportReceiptBatch,
    TransportTrustRootManifest,
    StageCostLedger,
    tuple[bytes, ...],
    tuple[bytes | None, ...],
]:
    request_bytes = (_request(0), _request(0))
    request_fingerprint = _hash("4")
    plan = TransportBatchPlan(
        schema_version=1,
        plan_id="pytest.pilot.transport-plan.v3",
        batch_id="pytest.pilot.transport-batch.v3",
        phase="pilot",
        comparison_block_id="pytest.pilot.block.v3",
        comparison_lock_hash=_hash("5"),
        design_hash=_hash("6"),
        execution_authorization_hash=_hash("7"),
        provider_id="pytest.provider",
        endpoint_origin="https://provider.invalid",
        requested_model_id="pytest.model",
        expected_observed_model_id="pytest.model",
        entries=tuple(
            TransportBatchEntry(
                sequence_number=index,
                invocation_id=f"pytest.pilot.invocation.{index}",
                criterion_id="pytest.criterion",
                presentation_hash=_hash("8"),
                data_attestation_hash=_hash("9"),
                request_fingerprint=request_fingerprint,
                request_bytes_hash=hashlib.sha256(raw).hexdigest(),
            )
            for index, raw in enumerate(request_bytes)
        ),
    )
    root = _root()
    signer = DeterministicTestSignatureVerifier()
    receipts: list[SignedTransportReceipt] = []
    response_bytes = (None, _response())
    for index, (entry, raw_response) in enumerate(
        zip(plan.entries, response_bytes, strict=True)
    ):
        absent = raw_response is None
        payload = TransportReceiptPayload(
            schema_version=1,
            receipt_id=f"pytest.pilot.receipt.{index}",
            claim_scope=(
                TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION
                if absent
                else TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
            ),
            provider_id=plan.provider_id,
            endpoint_origin=plan.endpoint_origin,
            requested_model_id=plan.requested_model_id,
            observed_model_id=plan.expected_observed_model_id,
            purpose="transport_receipt",
            phase=plan.phase,
            comparison_block_id=plan.comparison_block_id,
            comparison_lock_hash=plan.comparison_lock_hash,
            design_hash=plan.design_hash,
            execution_authorization_hash=plan.execution_authorization_hash,
            invocation_id=entry.invocation_id,
            criterion_id=entry.criterion_id,
            presentation_hash=entry.presentation_hash,
            data_attestation_hash=entry.data_attestation_hash,
            request_fingerprint=entry.request_fingerprint,
            request_bytes_hash=entry.request_bytes_hash,
            outcome=TransportOutcome.FAILED if absent else TransportOutcome.SUCCESS,
            failure_code="timeout" if absent else None,
            response_hash=(
                hashlib.sha256(raw_response).hexdigest()
                if raw_response is not None
                else None
            ),
            response_size=len(raw_response) if raw_response is not None else None,
            http_status=200 if raw_response is not None else None,
            started_at=f"2026-07-31T00:00:0{index}Z",
            completed_at=f"2026-07-31T00:00:0{index}Z",
            nonce=f"pytest.pilot.nonce.{index}",
            batch_id=plan.batch_id,
            batch_manifest_hash=plan.contract_hash,
            sequence_number=index,
            previous_receipt_hash=(receipts[-1].contract_hash if receipts else None),
            tls_peer_hostname="provider.invalid",
            tls_sni="provider.invalid",
            tls_certificate_sha256=None if absent else _hash("a"),
            tls_spki_sha256=None if absent else _hash("b"),
            tls_chain_sha256=None if absent else _hash("c"),
            tls_verification_result=(
                TLSVerificationResult.NOT_ESTABLISHED
                if absent
                else TLSVerificationResult.VERIFIED
            ),
            tls_trust_store_snapshot_hash=_hash("d"),
            tls_verification_policy_hash=root.tls_verification_policy_hash,
        )
        envelope = signer.sign_test_only(
            payload_hash=payload.contract_hash,
            root_manifest=root,
            key_fingerprint=root.key_authorizations[0].key_fingerprint,
            role_id=root.key_authorizations[0].role_id,
            purpose=payload.purpose,
            phase=payload.phase,
            sequence_number=index,
            nonce=payload.nonce,
            observed_signing_time=payload.completed_at,
        )
        receipts.append(SignedTransportReceipt(payload=payload, envelope=envelope))
    batch = TransportReceiptBatch(
        schema_version=1,
        plan=plan,
        receipts=tuple(receipts),
    )
    verification_policy = VerificationPolicy(
        schema_version=1,
        policy_id="pytest.pilot.transport-verification.v3",
        mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
        trust_domain=TrustDomain.TRANSPORT,
        allowed_root_manifest_hashes=(root.contract_hash,),
        allowed_claim_scopes=tuple(item.value for item in root.claim_scopes),
        expected_batch_manifest_hash=plan.contract_hash,
        allow_test_only=True,
    )
    phase_policy = PhaseTransportPolicyV3.create_simulated(
        policy_id="pytest.pilot.phase-transport.v3",
        phase="pilot",
        transport_policy=verification_policy,
        root_manifest=root,
        batch_plan=plan,
        expected_nonces=tuple(receipt.payload.nonce for receipt in batch.receipts),
        retry_parent_sequences=(None, 0),
        stage_cost_start_sequence=0,
    )
    entries: list[StageCostEntry] = []
    for index, receipt in enumerate(receipts):
        payload = receipt.payload
        entry = StageCostEntry(
            entry_id=f"pytest.pilot.judge.{index}",
            sequence=index,
            phase="pilot",
            category=CostCategory.JUDGE,
            outcome=(
                CostOutcome.FAILED
                if payload.outcome is TransportOutcome.FAILED
                else CostOutcome.SUCCEEDED
            ),
            failure_code=payload.failure_code,
            request_hash=payload.request_fingerprint,
            call_hash=payload.contract_hash,
            raw_receipt_hash=receipt.contract_hash,
            calls=1,
            input_tokens=1,
            output_tokens=0 if index == 0 else 1,
            wall_time_ms=1,
            bytes_transferred=payload.response_size or 0,
            retry_count=int(index > 0),
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=True,
            arm_id="judge_only",
            provider_id=payload.provider_id,
            model_id=payload.observed_model_id,
            cost_class="judge",
            retry_of_entry_hash=entries[0].contract_hash if entries else None,
            previous_entry_hash=entries[-1].contract_hash if entries else None,
        )
        entries.append(entry)
    ledger = StageCostLedger(
        ledger_id="pytest.transport-ledger.v3",
        version=1,
        price_manifest_hash=_hash("e"),
        budget_manifest=_budget(),
        entries=tuple(entries),
    )
    return (
        phase_policy,
        batch,
        root,
        ledger,
        request_bytes,
        response_bytes,
    )


def _reverify(**overrides: object) -> SimulatedTransportReverificationV3:
    policy, batch, root, ledger, requests, responses = _fixture()
    values = {
        "phase_policy": policy,
        "batch": batch,
        "root_manifest": root,
        "stage_cost_ledger": ledger,
        "request_bytes": requests,
        "response_bytes": responses,
        "verifier": DeterministicTestSignatureVerifier(),
    }
    values.update(overrides)
    return reverify_simulated_transport_phase_v3(**values)


def test_simulated_reverification_cross_binds_exact_attempt_transport_and_cost() -> (
    None
):
    result = _reverify()

    assert result.claim_scope == "simulated_nonclaim"
    assert result.evidence_class == "test_only"
    assert result.transport_membership_verified is True
    assert result.cost_verified is False
    assert result.production_authorized is False
    assert result.formal_result is False
    assert result.formal_eligible is False
    assert len(result.attempts) == 2
    assert tuple(item.stage_cost_sequence for item in result.attempts) == (0, 1)
    assert result.attempts[1].retry_parent_sequence == 0
    assert (
        result.attempts[1].retry_parent_invocation_id
        == result.attempts[0].invocation_id
    )
    assert result.schema_gaps == (
        LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP,
        UNVERIFIED_STAGE_COST_MEASURANDS_GAP,
    )

    with pytest.raises(TransportVerificationV3Error, match="factory-derived"):
        replace(result, production_authorized=True)


def test_simulated_reverification_canonical_bytes_round_trip_requires_typed_sources() -> (
    None
):
    result = _reverify()
    policy, batch, root, ledger, requests, responses = _fixture()
    raw = result.to_canonical_bytes()

    restored = SimulatedTransportReverificationV3.restore_from_canonical_bytes(
        raw,
        phase_policy=policy,
        batch=batch,
        root_manifest=root,
        stage_cost_ledger=ledger,
        request_bytes=requests,
        response_bytes=responses,
        verifier=DeterministicTestSignatureVerifier(),
    )

    assert restored == result
    assert raw == result.to_canonical_bytes()


def test_simulated_reverification_canonical_bytes_reject_tampering() -> None:
    result = _reverify()
    policy, batch, root, ledger, requests, responses = _fixture()

    with pytest.raises(TransportVerificationV3Error, match="canonical|JSON"):
        SimulatedTransportReverificationV3.restore_from_canonical_bytes(
            result.to_canonical_bytes() + b"\n",
            phase_policy=policy,
            batch=batch,
            root_manifest=root,
            stage_cost_ledger=ledger,
            request_bytes=requests,
            response_bytes=responses,
            verifier=DeterministicTestSignatureVerifier(),
        )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("request", "request bytes"),
        ("response", "response bytes"),
        ("nonce", "nonce"),
        ("receipt_order", "batch"),
        ("stage_receipt", "StageCost"),
        ("retry", "retry"),
        ("revocation", "root"),
    ),
)
def test_simulated_reverification_fails_closed_on_cross_binding_drift(
    field: str,
    expected: str,
) -> None:
    policy, batch, root, ledger, requests, responses = _fixture()
    kwargs: dict[str, object] = {}
    if field == "request":
        kwargs["request_bytes"] = (b"tampered", requests[1])
    elif field == "response":
        kwargs["response_bytes"] = (responses[0], b"tampered")
    elif field == "nonce":
        kwargs["phase_policy"] = replace(
            policy,
            expected_nonces=("tampered", policy.expected_nonces[1]),
        )
    elif field == "receipt_order":
        kwargs["batch"] = replace(batch, receipts=tuple(reversed(batch.receipts)))
    elif field == "stage_receipt":
        bad = replace(ledger.entries[0], raw_receipt_hash=_hash("f"))
        second = replace(
            ledger.entries[1],
            previous_entry_hash=bad.contract_hash,
            retry_of_entry_hash=bad.contract_hash,
        )
        kwargs["stage_cost_ledger"] = replace(ledger, entries=(bad, second))
    elif field == "retry":
        kwargs["phase_policy"] = replace(
            policy,
            retry_parent_sequences=(None, None),
        )
    elif field == "revocation":
        kwargs["root_manifest"] = replace(
            root,
            revocation_snapshot_hash=_hash("f"),
        )

    with pytest.raises(TransportVerificationV3Error, match=expected):
        _reverify(**kwargs)


def test_phase_policy_and_root_scope_cannot_be_reused_across_phases() -> None:
    policy, batch, root, ledger, requests, responses = _fixture()
    jaudit_plan = replace(
        batch.plan,
        plan_id="pytest.jaudit.transport-plan.v3",
        batch_id="pytest.jaudit.transport-batch.v3",
        phase="jaudit",
    )
    jaudit_root = _root(phase="jaudit")

    with pytest.raises(TransportVerificationV3Error, match="phase"):
        PhaseTransportPolicyV3.create_simulated(
            policy_id="pytest.reused-policy.v3",
            phase="jaudit",
            transport_policy=policy.transport_policy,
            root_manifest=jaudit_root,
            batch_plan=jaudit_plan,
            expected_nonces=policy.expected_nonces,
            retry_parent_sequences=policy.retry_parent_sequences,
            stage_cost_start_sequence=0,
        )

    with pytest.raises(TransportVerificationV3Error, match="root"):
        reverify_simulated_transport_phase_v3(
            phase_policy=policy,
            batch=batch,
            root_manifest=jaudit_root,
            stage_cost_ledger=ledger,
            request_bytes=requests,
            response_bytes=responses,
            verifier=DeterministicTestSignatureVerifier(),
        )


def test_retry_parent_must_share_frozen_request_and_presentation_ancestry() -> None:
    policy, batch, root, _, _, _ = _fixture()
    mismatched_retry = replace(
        batch.plan.entries[1],
        presentation_hash=_hash("f"),
    )
    bad_plan = replace(
        batch.plan,
        entries=(batch.plan.entries[0], mismatched_retry),
    )
    bad_transport_policy = replace(
        policy.transport_policy,
        expected_batch_manifest_hash=bad_plan.contract_hash,
    )

    with pytest.raises(TransportVerificationV3Error, match="retry ancestry"):
        PhaseTransportPolicyV3.create_simulated(
            policy_id="pytest.bad-retry-ancestry.v3",
            phase="pilot",
            transport_policy=bad_transport_policy,
            root_manifest=root,
            batch_plan=bad_plan,
            expected_nonces=policy.expected_nonces,
            retry_parent_sequences=policy.retry_parent_sequences,
            stage_cost_start_sequence=0,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing_receipt", "extra_receipt", "missing_stage", "wrong_stage_slice"),
)
def test_attempt_receipt_and_stage_cost_membership_must_be_exact(
    mutation: str,
) -> None:
    policy, batch, _, ledger, _, _ = _fixture()
    kwargs: dict[str, object] = {}
    if mutation == "missing_receipt":
        kwargs["batch"] = replace(batch, receipts=batch.receipts[:-1])
    elif mutation == "extra_receipt":
        kwargs["batch"] = replace(
            batch,
            receipts=(*batch.receipts, batch.receipts[-1]),
        )
    elif mutation == "missing_stage":
        kwargs["stage_cost_ledger"] = replace(
            ledger,
            entries=ledger.entries[:-1],
        )
    elif mutation == "wrong_stage_slice":
        kwargs["phase_policy"] = replace(
            policy,
            stage_cost_start_sequence=1,
        )

    with pytest.raises(TransportVerificationV3Error, match="membership"):
        _reverify(**kwargs)


def test_used_transport_key_must_have_one_exact_phase_scope() -> None:
    policy, batch, root, ledger, requests, responses = _fixture()
    broad_root = replace(
        root,
        key_authorizations=(
            replace(
                root.key_authorizations[0],
                allowed_phases=("pilot", "confirmatory"),
            ),
        ),
    )
    broad_transport_policy = replace(
        policy.transport_policy,
        allowed_root_manifest_hashes=(broad_root.contract_hash,),
    )
    broad_phase_policy = PhaseTransportPolicyV3.create_simulated(
        policy_id="pytest.broad-root-policy.v3",
        phase="pilot",
        transport_policy=broad_transport_policy,
        root_manifest=broad_root,
        batch_plan=batch.plan,
        expected_nonces=policy.expected_nonces,
        retry_parent_sequences=policy.retry_parent_sequences,
        stage_cost_start_sequence=0,
    )

    with pytest.raises(TransportVerificationV3Error, match="phase-specific"):
        reverify_simulated_transport_phase_v3(
            phase_policy=broad_phase_policy,
            batch=batch,
            root_manifest=broad_root,
            stage_cost_ledger=ledger,
            request_bytes=requests,
            response_bytes=responses,
            verifier=DeterministicTestSignatureVerifier(),
        )


def test_missing_or_test_verifier_cannot_reach_production_verification() -> None:
    with pytest.raises(TransportVerificationV3Error, match="not implemented"):
        require_production_transport_verification_v3(verifier=None)
    with pytest.raises(TransportVerificationV3Error, match="not implemented"):
        require_production_transport_verification_v3(
            verifier=DeterministicTestSignatureVerifier()
        )

    result = _reverify()
    assert "ProductionVerificationResult" not in type(result).__name__
    assert not hasattr(result, "gate_m")


def test_unverifiable_stage_cost_measurands_remain_an_explicit_gap() -> None:
    _, _, _, ledger, _, _ = _fixture()
    first = replace(
        ledger.entries[0],
        input_tokens=2,
        wall_time_ms=2,
        arm_id="self_eval",
        cost_class="attacker-controlled-cost-class",
    )
    second = replace(
        ledger.entries[1],
        arm_id="self_eval",
        cost_class="attacker-controlled-cost-class",
        previous_entry_hash=first.contract_hash,
        retry_of_entry_hash=first.contract_hash,
    )

    result = _reverify(
        stage_cost_ledger=replace(ledger, entries=(first, second)),
    )

    assert result.transport_membership_verified is True
    assert result.cost_verified is False
    assert UNVERIFIED_STAGE_COST_MEASURANDS_GAP in result.schema_gaps
