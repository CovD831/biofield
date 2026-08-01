from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    AuthorizationCheckpointManifest,
    AuthorizationCheckpointRequirement,
    DETERMINISTIC_TEST_ALGORITHM,
    DeterministicTestSignatureVerifier,
    HumanTrustRootManifest,
    KeyAuthorization,
    ProductionVerificationResult,
    SignatureEnvelope,
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportBatchEntry,
    TransportBatchPlan,
    TransportBatchVerification,
    TransportClaimScope,
    TransportOutcome,
    TransportReceiptBatch,
    TransportReceiptPayload,
    TransportTrustRootManifest,
    TrustContractError,
    TrustDomain,
    TrustVerificationMode,
    VerificationBlocker,
    VerificationAuthority,
    VerificationPolicy,
    VerificationResultFactory,
)
from biofield.meas0_readiness import (
    ApprovalManifest,
    FormalReadinessBundle,
    FormalReadinessInputs,
    ReadinessBlockerCode,
)


def _hash(character: str) -> str:
    return character * 64


def test_production_verification_factory_is_not_publicly_constructible() -> None:
    authority = VerificationAuthority(
        schema_version=1,
        authority_id="candidate-production-verifier",
        implementation_id="external-verifier",
        trust_domain=TrustDomain.TRANSPORT,
        test_only=False,
    )

    with pytest.raises(TrustContractError, match="factory"):
        VerificationResultFactory(authority=authority)
    with pytest.raises(TrustContractError, match="factory"):
        ProductionVerificationResult(
            schema_version=1,
            authority=authority,
            policy_hash=_hash("1"),
            root_manifest_hash=_hash("2"),
            payload_hash=_hash("3"),
            evidence_hash=_hash("4"),
        )


def test_checkpoint_manifest_matches_exact_raw_envelope_membership() -> None:
    tuples = (
        (AuthorizationCheckpoint.PRE_JCAL, "jcal", "pre_jcal", "role-a", "1"),
        (AuthorizationCheckpoint.PILOT_START, "pilot", "pilot_start", "role-b", "2"),
        (
            AuthorizationCheckpoint.POST_PILOT_JAUDIT,
            "jaudit",
            "post_pilot_jaudit",
            "role-c",
            "3",
        ),
        (
            AuthorizationCheckpoint.CONFIRMATORY_START,
            "confirmatory",
            "confirmatory_start",
            "role-d",
            "4",
        ),
    )
    requirements = tuple(
        AuthorizationCheckpointRequirement(
            checkpoint=checkpoint,
            phase=phase,
            purpose=purpose,
            role_id=role,
            authorization_target_hash=_hash(character),
            ledger_pre_head_hash=_hash("f"),
        )
        for checkpoint, phase, purpose, role, character in tuples
    )
    manifest = AuthorizationCheckpointManifest(
        schema_version=1,
        manifest_id="candidate-checkpoints",
        requirements=requirements,
    )

    def envelope(index: int, requirement: AuthorizationCheckpointRequirement):
        return SignatureEnvelope(
            schema_version=1,
            envelope_id=f"candidate-{index}",
            trust_domain=TrustDomain.HUMAN_APPROVAL,
            root_id="candidate-root",
            root_manifest_hash=_hash("a"),
            key_fingerprint=_hash("b"),
            algorithm_id="candidate.algorithm",
            role_id=requirement.role_id,
            purpose=requirement.purpose,
            phase=requirement.phase,
            payload_hash=requirement.payload_hash,
            sequence_number=index,
            nonce=f"candidate-{index}",
            observed_signing_time="2026-07-31T00:00:00Z",
            test_only=True,
            signature_hex=_hash("c"),
        )

    envelopes = tuple(envelope(index, item) for index, item in enumerate(requirements))
    assert manifest.matches_raw_envelopes(envelopes)
    assert not manifest.matches_raw_envelopes(envelopes[:-1])
    altered = replace(
        requirements[0],
        ledger_pre_head_hash=_hash("e"),
    )
    assert not manifest.matches_raw_envelopes(
        (envelope(0, altered), *envelopes[1:]),
    )


def _transport_authorization() -> KeyAuthorization:
    return KeyAuthorization(
        key_fingerprint=_hash("1"),
        algorithm_id=DETERMINISTIC_TEST_ALGORITHM,
        role_id="transport-gateway",
        allowed_purposes=("transport_receipt",),
        allowed_phases=("jcal", "pilot", "jaudit", "confirmatory"),
    )


def _transport_root() -> TransportTrustRootManifest:
    return TransportTrustRootManifest(
        schema_version=1,
        root_id="transport-root-test-v1",
        operator_id="independent-gateway-operator",
        harness_administrative_domain="harness-admin-domain",
        administrative_domain="independent-admin-domain",
        harness_security_boundary_id="harness-security-boundary",
        security_boundary_id="independent-security-boundary",
        workload_identity="gateway-workload-test",
        key_custodian="test-kms-custodian",
        claim_scopes=(
            TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION,
            TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION,
        ),
        provider_id="deepseek",
        endpoint_origins=("https://api.deepseek.com",),
        model_ids=("deepseek-v4-pro",),
        key_authorizations=(_transport_authorization(),),
        valid_from="2026-07-31T00:00:00Z",
        valid_until="2026-08-31T00:00:00Z",
        revocation_snapshot_hash=_hash("2"),
        revoked_key_fingerprints=(),
        tls_verification_policy_hash=_hash("3"),
        reviewer_role_id="transport-root-reviewer",
        test_only=True,
    )


def _human_authorization() -> KeyAuthorization:
    return KeyAuthorization(
        key_fingerprint=_hash("4"),
        algorithm_id=DETERMINISTIC_TEST_ALGORITHM,
        role_id="lock-authority-e",
        allowed_purposes=("comparison_lock_approval",),
        allowed_phases=("pilot", "confirmatory"),
    )


def _human_root() -> HumanTrustRootManifest:
    return HumanTrustRootManifest(
        schema_version=1,
        root_id="human-root-test-v1",
        custodian_id="human-key-custodian",
        key_authorizations=(_human_authorization(),),
        valid_from="2026-07-31T00:00:00Z",
        valid_until="2026-08-31T00:00:00Z",
        revocation_snapshot_hash=_hash("5"),
        revoked_key_fingerprints=(),
        reviewer_role_id="human-root-reviewer",
        test_only=True,
    )


def _success_payload(
    *,
    sequence_number: int = 0,
    previous_receipt_hash: str | None = None,
) -> TransportReceiptPayload:
    return TransportReceiptPayload(
        schema_version=1,
        receipt_id=f"transport-receipt-{sequence_number}",
        claim_scope=(TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION),
        provider_id="deepseek",
        endpoint_origin="https://api.deepseek.com",
        requested_model_id="deepseek-v4-pro",
        observed_model_id="deepseek-v4-pro",
        purpose="transport_receipt",
        phase="jcal",
        comparison_block_id="jcal-block-v1",
        comparison_lock_hash=_hash("6"),
        design_hash=_hash("5"),
        execution_authorization_hash=_hash("4"),
        invocation_id=f"jcal-invocation-{sequence_number}",
        criterion_id=f"criterion-{sequence_number}",
        presentation_hash=_hash("7"),
        data_attestation_hash=_hash("8"),
        request_fingerprint=_hash("9"),
        request_bytes_hash=_hash("a"),
        outcome=TransportOutcome.SUCCESS,
        failure_code=None,
        response_hash=_hash("b"),
        response_size=123,
        http_status=200,
        started_at="2026-07-31T01:00:00Z",
        completed_at="2026-07-31T01:00:01Z",
        nonce=f"nonce-{sequence_number}",
        batch_id="jcal-batch-v1",
        batch_manifest_hash=_hash("c"),
        sequence_number=sequence_number,
        previous_receipt_hash=previous_receipt_hash,
        tls_peer_hostname="api.deepseek.com",
        tls_sni="api.deepseek.com",
        tls_certificate_sha256=_hash("d"),
        tls_spki_sha256=_hash("e"),
        tls_chain_sha256=_hash("f"),
        tls_verification_result=TLSVerificationResult.VERIFIED,
        tls_trust_store_snapshot_hash=_hash("0"),
        tls_verification_policy_hash=_hash("3"),
    )


def _signed_transport(
    payload: TransportReceiptPayload,
    *,
    root: TransportTrustRootManifest | None = None,
) -> SignedTransportReceipt:
    root = root or _transport_root()
    signer = DeterministicTestSignatureVerifier()
    envelope = signer.sign_test_only(
        payload_hash=payload.contract_hash,
        root_manifest=root,
        key_fingerprint=_transport_authorization().key_fingerprint,
        role_id="transport-gateway",
        purpose=payload.purpose,
        phase=payload.phase,
        sequence_number=payload.sequence_number,
        nonce=payload.nonce,
        observed_signing_time="2026-07-31T01:00:02Z",
    )
    return SignedTransportReceipt(payload=payload, envelope=envelope)


def _batch_plan(*, entry_count: int = 2) -> TransportBatchPlan:
    return TransportBatchPlan(
        schema_version=1,
        plan_id="jcal-transport-plan-v1",
        batch_id="jcal-batch-v1",
        phase="jcal",
        comparison_block_id="jcal-block-v1",
        comparison_lock_hash=_hash("6"),
        design_hash=_hash("5"),
        execution_authorization_hash=_hash("4"),
        provider_id="deepseek",
        endpoint_origin="https://api.deepseek.com",
        requested_model_id="deepseek-v4-pro",
        expected_observed_model_id="deepseek-v4-pro",
        entries=tuple(
            TransportBatchEntry(
                sequence_number=index,
                invocation_id=f"jcal-invocation-{index}",
                criterion_id=f"criterion-{index}",
                presentation_hash=_hash("7"),
                data_attestation_hash=_hash("8"),
                request_fingerprint=_hash("9"),
                request_bytes_hash=_hash("a"),
            )
            for index in range(entry_count)
        ),
    )


def _receipt_batch(
    plan: TransportBatchPlan | None = None,
) -> tuple[
    TransportBatchPlan,
    TransportReceiptBatch,
    TransportTrustRootManifest,
    VerificationPolicy,
]:
    selected_plan = plan or _batch_plan()
    root = _transport_root()
    receipts = []
    previous = None
    for entry in selected_plan.entries:
        payload = replace(
            _success_payload(
                sequence_number=entry.sequence_number,
                previous_receipt_hash=(
                    previous.contract_hash if previous is not None else None
                ),
            ),
            batch_manifest_hash=selected_plan.contract_hash,
        )
        receipt = _signed_transport(payload, root=root)
        receipts.append(receipt)
        previous = receipt
    policy = replace(
        _test_policy(root, domain=TrustDomain.TRANSPORT),
        expected_batch_manifest_hash=selected_plan.contract_hash,
    )
    return (
        selected_plan,
        TransportReceiptBatch(
            schema_version=1,
            plan=selected_plan,
            receipts=tuple(receipts),
        ),
        root,
        policy,
    )


def _test_policy(
    root: TransportTrustRootManifest | HumanTrustRootManifest,
    *,
    domain: TrustDomain,
) -> VerificationPolicy:
    return VerificationPolicy(
        schema_version=1,
        policy_id=f"{domain.value}-test-policy",
        mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
        trust_domain=domain,
        allowed_root_manifest_hashes=(root.contract_hash,),
        allowed_claim_scopes=(
            (
                TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION.value,
                TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION.value,
            )
            if domain is TrustDomain.TRANSPORT
            else ()
        ),
        expected_batch_manifest_hash=(
            _hash("c") if domain is TrustDomain.TRANSPORT else None
        ),
        allow_test_only=True,
    )


def test_trust_root_manifests_are_canonical_hash_bound_and_round_trip() -> None:
    transport = _transport_root()
    human = _human_root()

    assert TransportTrustRootManifest.from_dict(transport.to_dict()) == transport
    assert HumanTrustRootManifest.from_dict(human.to_dict()) == human
    assert transport.trust_domain is TrustDomain.TRANSPORT
    assert human.trust_domain is TrustDomain.HUMAN_APPROVAL
    assert transport.contract_hash != human.contract_hash
    assert transport.to_dict()["contract_hash"] == transport.contract_hash


def test_transport_root_requires_an_independent_administrative_security_boundary() -> (
    None
):
    root = _transport_root()

    with pytest.raises(TrustContractError, match="independent"):
        replace(
            root,
            administrative_domain=root.harness_administrative_domain,
        )
    with pytest.raises(TrustContractError, match="independent"):
        replace(
            root,
            security_boundary_id=root.harness_security_boundary_id,
        )


def test_one_key_cannot_be_authorized_for_multiple_roles() -> None:
    root = _human_root()
    reused = replace(
        _human_authorization(),
        role_id="independent-lock-reviewer-f",
        allowed_purposes=("comparison_lock_review",),
    )

    with pytest.raises(TrustContractError, match="fingerprint"):
        replace(
            root,
            key_authorizations=(_human_authorization(), reused),
        )


def test_success_receipt_verifies_only_as_test_only_contract_evidence() -> None:
    root = _transport_root()
    receipt = _signed_transport(_success_payload(), root=root)
    policy = _test_policy(root, domain=TrustDomain.TRANSPORT)

    result = DeterministicTestSignatureVerifier().verify_transport_receipt(
        receipt=receipt,
        root_manifest=root,
        policy=policy,
    )

    assert result.verified is True
    assert result.production_authorized is False
    assert result.claim_scope == "contract_only"
    assert result.blockers == ()
    assert type(result).from_dict(result.to_dict()) == result
    assert SignedTransportReceipt.from_dict(receipt.to_dict()) == receipt


def test_transport_signature_tamper_and_wrong_role_fail_closed() -> None:
    root = _transport_root()
    receipt = _signed_transport(_success_payload(), root=root)
    policy = _test_policy(root, domain=TrustDomain.TRANSPORT)
    verifier = DeterministicTestSignatureVerifier()

    bad_signature = replace(
        receipt,
        envelope=replace(receipt.envelope, signature_hex="00" * 32),
    )
    bad_signature_result = verifier.verify_transport_receipt(
        receipt=bad_signature,
        root_manifest=root,
        policy=policy,
    )
    assert bad_signature_result.verified is False
    assert VerificationBlocker.SIGNATURE_INVALID in bad_signature_result.blockers

    unauthorized_root = replace(
        root,
        key_authorizations=(replace(_transport_authorization(), role_id="other-role"),),
    )
    unauthorized_policy = _test_policy(
        unauthorized_root,
        domain=TrustDomain.TRANSPORT,
    )
    unauthorized = verifier.verify_transport_receipt(
        receipt=receipt,
        root_manifest=unauthorized_root,
        policy=unauthorized_policy,
    )
    assert unauthorized.verified is False
    assert VerificationBlocker.KEY_NOT_AUTHORIZED in unauthorized.blockers


def test_transport_and_human_trust_domains_cannot_be_substituted() -> None:
    human_root = _human_root()
    receipt = _signed_transport(_success_payload())
    policy = _test_policy(human_root, domain=TrustDomain.HUMAN_APPROVAL)

    result = DeterministicTestSignatureVerifier().verify_transport_receipt(
        receipt=receipt,
        root_manifest=human_root,
        policy=policy,
    )

    assert result.verified is False
    assert VerificationBlocker.TRUST_DOMAIN_MISMATCH in result.blockers


def test_success_requires_verified_tls_and_complete_response_identity() -> None:
    payload = _success_payload()

    with pytest.raises(TrustContractError, match="TLS"):
        replace(payload, tls_verification_result=TLSVerificationResult.FAILED)
    with pytest.raises(TrustContractError, match="response"):
        replace(payload, response_hash=None)
    with pytest.raises(TrustContractError, match="response"):
        replace(payload, response_size=None)


def test_failed_call_has_explicit_absent_response_variant() -> None:
    failed = replace(
        _success_payload(),
        receipt_id="transport-receipt-failed",
        claim_scope=TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION,
        invocation_id="jcal-invocation-failed",
        outcome=TransportOutcome.FAILED,
        failure_code="connect_timeout",
        response_hash=None,
        response_size=None,
        http_status=None,
        tls_certificate_sha256=None,
        tls_spki_sha256=None,
        tls_chain_sha256=None,
        tls_verification_result=TLSVerificationResult.NOT_ESTABLISHED,
    )

    restored = TransportReceiptPayload.from_dict(failed.to_dict())

    assert restored == failed
    assert restored.response_present is False
    with pytest.raises(TrustContractError, match="absent response"):
        replace(failed, response_hash=_hash("b"), response_size=1)


def test_chain_sequence_and_batch_ancestry_are_enforced() -> None:
    root = _transport_root()
    first = _signed_transport(_success_payload(), root=root)
    second_payload = _success_payload(
        sequence_number=1,
        previous_receipt_hash=first.contract_hash,
    )
    second = _signed_transport(second_payload, root=root)
    policy = _test_policy(root, domain=TrustDomain.TRANSPORT)
    verifier = DeterministicTestSignatureVerifier()

    valid = verifier.verify_transport_receipt(
        receipt=second,
        root_manifest=root,
        policy=policy,
        previous_receipt=first,
    )
    assert valid.verified is True

    missing_previous = verifier.verify_transport_receipt(
        receipt=second,
        root_manifest=root,
        policy=policy,
        previous_receipt=None,
    )
    assert missing_previous.verified is False
    assert VerificationBlocker.CHAIN_ANCESTRY_INVALID in missing_previous.blockers

    with pytest.raises(TrustContractError, match="previous"):
        _success_payload(sequence_number=1, previous_receipt_hash=None)


def test_production_policy_is_explicit_deny_all_even_for_valid_test_signature() -> None:
    root = _transport_root()
    receipt = _signed_transport(_success_payload(), root=root)
    policy = VerificationPolicy(
        schema_version=1,
        policy_id="production-deny-all-v1",
        mode=TrustVerificationMode.PRODUCTION_DENY_ALL,
        trust_domain=TrustDomain.TRANSPORT,
        allowed_root_manifest_hashes=(root.contract_hash,),
        allowed_claim_scopes=(
            TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION.value,
        ),
        expected_batch_manifest_hash=_hash("c"),
        allow_test_only=False,
    )

    result = DeterministicTestSignatureVerifier().verify_transport_receipt(
        receipt=receipt,
        root_manifest=root,
        policy=policy,
    )

    assert result.verified is False
    assert result.production_authorized is False
    assert result.mode is TrustVerificationMode.PRODUCTION_DENY_ALL
    assert VerificationBlocker.PRODUCTION_TRUST_NOT_IMPLEMENTED in result.blockers


def test_revoked_test_key_is_retained_but_cannot_verify() -> None:
    root = _transport_root()
    receipt = _signed_transport(_success_payload(), root=root)
    revoked_root = replace(
        root,
        revoked_key_fingerprints=(receipt.envelope.key_fingerprint,),
    )
    policy = _test_policy(revoked_root, domain=TrustDomain.TRANSPORT)

    result = DeterministicTestSignatureVerifier().verify_transport_receipt(
        receipt=receipt,
        root_manifest=revoked_root,
        policy=policy,
    )

    assert result.verified is False
    assert VerificationBlocker.KEY_REVOKED in result.blockers


def test_human_signature_enforces_key_role_purpose_and_phase() -> None:
    root = _human_root()
    policy = _test_policy(root, domain=TrustDomain.HUMAN_APPROVAL)
    verifier = DeterministicTestSignatureVerifier()
    payload_hash = _hash("a")
    envelope = verifier.sign_test_only(
        payload_hash=payload_hash,
        root_manifest=root,
        key_fingerprint=_human_authorization().key_fingerprint,
        role_id="lock-authority-e",
        purpose="comparison_lock_approval",
        phase="pilot",
        sequence_number=0,
        nonce="human-signature-nonce",
        observed_signing_time="2026-07-31T02:00:00Z",
    )

    valid = verifier.verify_signature_envelope(
        envelope=envelope,
        payload_hash=payload_hash,
        root_manifest=root,
        policy=policy,
    )
    assert valid.verified is True

    wrong_purpose = replace(envelope, purpose="transport_receipt")
    invalid = verifier.verify_signature_envelope(
        envelope=wrong_purpose,
        payload_hash=payload_hash,
        root_manifest=root,
        policy=policy,
    )
    assert invalid.verified is False
    assert VerificationBlocker.KEY_NOT_AUTHORIZED in invalid.blockers


def test_signature_envelope_round_trip_does_not_self_sign_its_signature() -> None:
    root = _human_root()
    verifier = DeterministicTestSignatureVerifier()
    envelope = verifier.sign_test_only(
        payload_hash=_hash("a"),
        root_manifest=root,
        key_fingerprint=_human_authorization().key_fingerprint,
        role_id="lock-authority-e",
        purpose="comparison_lock_approval",
        phase="pilot",
        sequence_number=0,
        nonce="envelope-roundtrip",
        observed_signing_time="2026-07-31T02:00:00Z",
    )

    restored = SignatureEnvelope.from_dict(envelope.to_dict())

    assert restored == envelope
    assert "signature_hex" not in restored.signed_metadata
    assert restored.contract_hash == envelope.contract_hash


def test_batch_verification_is_exact_but_never_grants_production_authority() -> None:
    plan, batch, root, policy = _receipt_batch()

    result = DeterministicTestSignatureVerifier().verify_transport_batch(
        batch=batch,
        root_manifest=root,
        policy=policy,
    )

    assert result.contract_verified is True
    assert result.production_authorized is False
    assert result.blockers == ()
    assert result.plan_hash == plan.contract_hash
    assert TransportBatchPlan.from_dict(plan.to_dict()) == plan
    assert TransportReceiptBatch.from_dict(batch.to_dict()) == batch
    assert TransportBatchVerification.from_dict(result.to_dict()) == result
    with pytest.raises(TrustContractError, match="derived"):
        replace(result, production_authorized=True)


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "extra", "reordered", "tail_truncated"),
)
def test_batch_verification_rejects_non_exact_membership_and_order(
    mutation: str,
) -> None:
    _, batch, root, policy = _receipt_batch()
    receipts = list(batch.receipts)
    if mutation == "missing":
        receipts = receipts[1:]
    elif mutation == "duplicate":
        receipts[1] = receipts[0]
    elif mutation == "extra":
        receipts.append(receipts[-1])
    elif mutation == "reordered":
        receipts.reverse()
    elif mutation == "tail_truncated":
        receipts.pop()

    result = DeterministicTestSignatureVerifier().verify_transport_batch(
        batch=replace(batch, receipts=tuple(receipts)),
        root_manifest=root,
        policy=policy,
    )

    assert result.contract_verified is False
    assert result.production_authorized is False
    assert result.blockers


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("criterion_id", "wrong-criterion"),
        ("design_hash", _hash("1")),
        ("execution_authorization_hash", _hash("2")),
        ("requested_model_id", "deepseek-other"),
        ("observed_model_id", "deepseek-other"),
    ),
)
def test_batch_verification_rejects_cross_call_and_lock_binding(
    field_name: str,
    bad_value: str,
) -> None:
    _, batch, root, policy = _receipt_batch()
    payload = replace(batch.receipts[0].payload, **{field_name: bad_value})
    forged = _signed_transport(payload, root=root)
    tampered = replace(
        batch,
        receipts=(forged, batch.receipts[1]),
    )

    result = DeterministicTestSignatureVerifier().verify_transport_batch(
        batch=tampered,
        root_manifest=root,
        policy=policy,
    )

    assert result.contract_verified is False
    assert result.production_authorized is False


def test_readiness_reverifies_raw_batch_and_keeps_test_trust_nonformal() -> None:
    _, batch, root, policy = _receipt_batch()
    bundle = FormalReadinessBundle.create(
        FormalReadinessInputs(
            transport_trust_root=root,
            transport_verification_policy=policy,
            transport_receipt_batch=batch,
        )
    )

    assert ReadinessBlockerCode.TRANSPORT_RECEIPTS_MISSING not in bundle.report.blockers
    assert ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID not in bundle.report.blockers
    assert (
        ReadinessBlockerCode.TRANSPORT_PRODUCTION_TRUST_UNAVAILABLE
        in bundle.report.blockers
    )
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle

    tampered = replace(
        batch,
        receipts=batch.receipts[:-1],
    )
    invalid = FormalReadinessBundle.create(
        FormalReadinessInputs(
            transport_trust_root=root,
            transport_verification_policy=policy,
            transport_receipt_batch=tampered,
        )
    )
    assert ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID in invalid.report.blockers


def test_readiness_reverifies_human_envelope_without_granting_authority() -> None:
    root = _human_root()
    policy = _test_policy(root, domain=TrustDomain.HUMAN_APPROVAL)
    approval = ApprovalManifest(
        manifest_id="approval-test-v1",
        version=1,
        lock_sha256=_hash("4"),
        approved=True,
        approver_role_id="lock-authority-e",
        approved_at="2026-07-31T02:00:00Z",
    )
    envelope = DeterministicTestSignatureVerifier().sign_test_only(
        payload_hash=approval.contract_hash,
        root_manifest=root,
        key_fingerprint=_human_authorization().key_fingerprint,
        role_id="lock-authority-e",
        purpose="comparison_lock_approval",
        phase="pilot",
        sequence_number=0,
        nonce="readiness-human-signature",
        observed_signing_time="2026-07-31T02:00:00Z",
    )
    bundle = FormalReadinessBundle.create(
        FormalReadinessInputs(
            human_trust_root=root,
            human_signature_policy=policy,
            human_signature_envelopes=(envelope,),
            approval_manifest=approval,
        )
    )

    assert ReadinessBlockerCode.HUMAN_SIGNATURES_MISSING not in bundle.report.blockers
    assert ReadinessBlockerCode.HUMAN_SIGNATURES_INVALID not in bundle.report.blockers
    assert (
        ReadinessBlockerCode.HUMAN_SIGNATURE_PRODUCTION_TRUST_UNAVAILABLE
        in bundle.report.blockers
    )
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle
