from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_protected_artifacts import (
    ProtectedRawArtifactStore,
    RawArtifactHandlingManifest,
)
from biofield.meas0_providers import (
    CodexSubjectRequest,
    DEEPSEEK_V4_PRO_JUDGE_CARD_ID,
    DataHandlingAttestation,
    DeepSeekTransportResponse,
    DeepSeekV4ProJudgeAdapter,
    ProviderContractError,
    build_codex_subscription_command,
    deepseek_input_sha256,
    require_production_deepseek_evidence,
    seal_protected_deepseek_evidence,
    seal_codex_subject_execution,
    verify_protected_deepseek_evidence,
)
from biofield.meas0_trust import (
    DETERMINISTIC_TEST_ALGORITHM,
    DeterministicTestSignatureVerifier,
    KeyAuthorization,
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportClaimScope,
    TransportOutcome,
    TransportReceiptPayload,
    TransportTrustRootManifest,
)


SUBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
    },
    "required": ["answer", "evidence_refs"],
    "additionalProperties": False,
}


JUDGE_OUTPUT = {
    "criterion_id": "semantic-01",
    "verdict": "pass",
    "evidence_refs": ["response:final"],
    "rationale": "The response contains the required actionable step.",
    "confidence_0_1": 0.9,
    "p_pass_0_1": 0.85,
    "judge_version": DEEPSEEK_V4_PRO_JUDGE_CARD_ID,
}


def _subject_request(tmp_path: Path) -> CodexSubjectRequest:
    return CodexSubjectRequest(
        prompt=b"Produce the frozen task response.",
        model="gpt-5.6-terra",
        working_directory=str(tmp_path.resolve()),
        output_schema_path=str((tmp_path / "subject.schema.json").resolve()),
        output_path=str((tmp_path / "subject.output.json").resolve()),
        output_schema=SUBJECT_SCHEMA,
        sandbox="workspace-write",
    )


def _deepseek_attestation(
    *,
    system_prompt: str,
    user_content: str,
    deidentified: bool = True,
    non_sensitive: bool = True,
) -> DataHandlingAttestation:
    return DataHandlingAttestation(
        attestation_id="data-attestation-v1",
        attestor_id="privacy-reviewer",
        attested_at="2026-07-30T12:00:00Z",
        input_sha256=deepseek_input_sha256(
            system_prompt=system_prompt,
            user_content=user_content,
            criterion_id="semantic-01",
            allowed_evidence_refs=("response:final",),
        ),
        deidentified=deidentified,
        non_sensitive=non_sensitive,
    )


def _deepseek_response(
    *,
    output: dict[str, object] | None = None,
    model: str = "deepseek-v4-pro",
    fingerprint: str = "fp_backend_v4_pro",
) -> bytes:
    payload = {
        "id": "chatcmpl-deepseek-001",
        "object": "chat.completion",
        "created": 1785400000,
        "model": model,
        "system_fingerprint": fingerprint,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        output or JUDGE_OUTPUT,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "reasoning_content": "Private model reasoning is sealed, not exposed.",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "completion_tokens": 25,
            "total_tokens": 125,
            "completion_tokens_details": {"reasoning_tokens": 15},
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _transport_root() -> TransportTrustRootManifest:
    authorization = KeyAuthorization(
        key_fingerprint="1" * 64,
        algorithm_id=DETERMINISTIC_TEST_ALGORITHM,
        role_id="transport-gateway",
        allowed_purposes=("transport_receipt",),
        allowed_phases=("jcal",),
    )
    return TransportTrustRootManifest(
        schema_version=1,
        root_id="provider-test-root",
        operator_id="independent-gateway",
        harness_administrative_domain="harness-admin",
        administrative_domain="gateway-admin",
        harness_security_boundary_id="harness-boundary",
        security_boundary_id="gateway-boundary",
        workload_identity="gateway-workload",
        key_custodian="test-kms",
        claim_scopes=(TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION,),
        provider_id="deepseek",
        endpoint_origins=("https://api.deepseek.com",),
        model_ids=("deepseek-v4-pro",),
        key_authorizations=(authorization,),
        valid_from="2026-07-30T00:00:00Z",
        valid_until="2026-08-30T00:00:00Z",
        revocation_snapshot_hash="2" * 64,
        revoked_key_fingerprints=(),
        tls_verification_policy_hash="3" * 64,
        reviewer_role_id="transport-root-reviewer",
        test_only=True,
    )


def _signed_transport_receipt(
    *,
    request,
    raw_response: bytes,
    payload_changes: dict[str, object] | None = None,
) -> SignedTransportReceipt:
    payload = TransportReceiptPayload(
        schema_version=1,
        receipt_id="deepseek-receipt-001",
        claim_scope=(TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION),
        provider_id="deepseek",
        endpoint_origin="https://api.deepseek.com",
        requested_model_id="deepseek-v4-pro",
        observed_model_id="deepseek-v4-pro",
        purpose="transport_receipt",
        phase="jcal",
        comparison_block_id="jcal-block-v1",
        comparison_lock_hash="4" * 64,
        design_hash="5" * 64,
        execution_authorization_hash="6" * 64,
        invocation_id="jcal.item-01.normal",
        criterion_id=request.criterion_id,
        presentation_hash="7" * 64,
        data_attestation_hash=request.data_attestation.contract_hash,
        request_fingerprint=request.request_fingerprint,
        request_bytes_hash=hashlib.sha256(request.body_bytes).hexdigest(),
        outcome=TransportOutcome.SUCCESS,
        failure_code=None,
        response_hash=hashlib.sha256(raw_response).hexdigest(),
        response_size=len(raw_response),
        http_status=200,
        started_at="2026-07-30T12:00:00Z",
        completed_at="2026-07-30T12:00:01Z",
        nonce="deepseek-receipt-nonce",
        batch_id="jcal-batch-v1",
        batch_manifest_hash="8" * 64,
        sequence_number=0,
        previous_receipt_hash=None,
        tls_peer_hostname="api.deepseek.com",
        tls_sni="api.deepseek.com",
        tls_certificate_sha256="9" * 64,
        tls_spki_sha256="a" * 64,
        tls_chain_sha256="b" * 64,
        tls_verification_result=TLSVerificationResult.VERIFIED,
        tls_trust_store_snapshot_hash="c" * 64,
        tls_verification_policy_hash="3" * 64,
    )
    if payload_changes:
        payload = replace(payload, **payload_changes)
    root = _transport_root()
    envelope = DeterministicTestSignatureVerifier().sign_test_only(
        payload_hash=payload.contract_hash,
        root_manifest=root,
        key_fingerprint="1" * 64,
        role_id="transport-gateway",
        purpose="transport_receipt",
        phase="jcal",
        sequence_number=0,
        nonce=payload.nonce,
        observed_signing_time="2026-07-30T12:00:02Z",
    )
    return SignedTransportReceipt(payload=payload, envelope=envelope)


def test_formal_provider_modules_are_in_meas0_source_closure() -> None:
    pilot_run_source = (
        Path(__file__).parents[1] / "src" / "biofield" / "meas0_pilot_run.py"
    ).read_text(encoding="utf-8")

    assert '"meas0_formal_metrics.py": package / "meas0_formal_metrics.py"' in (
        pilot_run_source
    )
    assert '"meas0_formal_runner.py": package / "meas0_formal_runner.py"' in (
        pilot_run_source
    )
    assert '"meas0_providers.py": package / "meas0_providers.py"' in pilot_run_source


class _TestOnlyTransport:
    transport_id = "pytest-deepseek-transport"
    test_only = True

    def __init__(
        self,
        raw_response: bytes,
        receipt: SignedTransportReceipt | None = None,
    ) -> None:
        self.raw_response = raw_response
        self.receipt = receipt
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return DeepSeekTransportResponse(
            status_code=200,
            raw_response=self.raw_response,
            received_at="2026-07-30T12:00:01Z",
            transport_receipt=self.receipt,
        )


class _ProductionLabeledTransport(_TestOnlyTransport):
    test_only = False


def test_codex_subscription_command_is_stdin_only_and_has_no_auth_material(
    tmp_path: Path,
) -> None:
    request = _subject_request(tmp_path)

    command = build_codex_subscription_command(request)

    assert command.argv == (
        "codex",
        "exec",
        "--ephemeral",
        "--json",
        "--ignore-user-config",
        "--model",
        "gpt-5.6-terra",
        "--sandbox",
        "workspace-write",
        "--output-schema",
        request.output_schema_path,
        "--output-last-message",
        request.output_path,
        "-",
    )
    assert command.stdin_bytes == request.prompt
    assert command.environment == ()
    assert command.authentication == "existing_chatgpt_subscription_session"
    serialized = json.dumps(command.to_dict(), sort_keys=True)
    assert request.prompt.decode() not in serialized
    assert "auth.json" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "CODEX_ACCESS_TOKEN" not in serialized
    assert len(command.command_hash) == 64


def test_codex_command_rejects_unsafe_or_unsealed_inputs(tmp_path: Path) -> None:
    request = _subject_request(tmp_path)

    with pytest.raises(ProviderContractError, match="sandbox"):
        build_codex_subscription_command(replace(request, sandbox="danger-full-access"))
    with pytest.raises(ProviderContractError, match="model"):
        replace(request, model="gpt-5.4")
    with pytest.raises(ProviderContractError, match="absolute"):
        build_codex_subscription_command(
            replace(request, output_path="relative-output.json")
        )
    with pytest.raises(ProviderContractError, match="working directory"):
        build_codex_subscription_command(
            replace(
                request,
                output_path=str(
                    (tmp_path / ".." / "outside-subject-output.json").resolve()
                ),
            )
        )
    with pytest.raises(ProviderContractError, match="normalized"):
        build_codex_subscription_command(
            replace(
                request,
                output_path=str(tmp_path / "nested" / ".." / "subject.output.json"),
            )
        )
    with pytest.raises(ProviderContractError, match="schema"):
        build_codex_subscription_command(
            replace(
                request,
                output_schema={
                    **SUBJECT_SCHEMA,
                    "additionalProperties": True,
                },
            )
        )


def test_codex_command_requires_exact_build_only_argv(tmp_path: Path) -> None:
    command = build_codex_subscription_command(_subject_request(tmp_path))

    with pytest.raises(ProviderContractError, match="exact"):
        replace(
            command,
            argv=(
                *command.argv[:-1],
                "--dangerously-bypass-approvals-and-sandbox",
                "-",
            ),
        )

    serialized = command.to_dict()
    assert serialized["build_only"] is True
    assert serialized["schema_file_bytes_verified"] is False
    assert serialized["parent_environment_verified"] is False
    assert serialized["claim_scope"] == "subject_probe_nonformal"


def test_codex_execution_seal_validates_jsonl_and_structured_output(
    tmp_path: Path,
) -> None:
    command = build_codex_subscription_command(_subject_request(tmp_path))
    raw_jsonl = b"\n".join(
        (
            b'{"type":"thread.started","thread_id":"thread-001"}',
            b'{"type":"turn.started"}',
            (
                b'{"type":"turn.completed","usage":{"input_tokens":20,'
                b'"cached_input_tokens":5,"output_tokens":8,'
                b'"reasoning_output_tokens":2}}'
            ),
        )
    )
    final_output = b'{"answer":"Ready.","evidence_refs":["artifact:1"]}'

    sealed = seal_codex_subject_execution(
        command=command,
        exit_code=0,
        raw_jsonl=raw_jsonl,
        final_output=final_output,
        cli_version="codex-cli-test",
        completed_at="2026-07-30T12:00:01Z",
    )

    assert sealed.command_hash == command.command_hash
    assert sealed.thread_id == "thread-001"
    assert sealed.input_tokens == 20
    assert sealed.cached_input_tokens == 5
    assert sealed.output_tokens == 8
    assert sealed.reasoning_output_tokens == 2
    assert sealed.subscription_black_box is True
    assert sealed.replay_capability == "output_and_metadata_only"
    assert sealed.claim_scope == "subject_probe_nonformal"
    assert len(sealed.raw_jsonl_sha256) == 64
    assert len(sealed.final_output_sha256) == 64
    assert "raw_jsonl" not in sealed.to_dict()

    with pytest.raises(ProviderContractError, match="schema"):
        seal_codex_subject_execution(
            command=command,
            exit_code=0,
            raw_jsonl=raw_jsonl,
            final_output=b'{"answer":"missing evidence refs"}',
            cli_version="codex-cli-test",
            completed_at="2026-07-30T12:00:01Z",
        )


def test_deepseek_request_requires_bound_deidentified_nonsensitive_input() -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    attestation = _deepseek_attestation(
        system_prompt=system_prompt,
        user_content=user_content,
    )

    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=attestation,
        temperature=0.2,
    )

    assert request.url == "https://api.deepseek.com/chat/completions"
    assert request.body["model"] == "deepseek-v4-pro"
    assert request.body["thinking"] == {"type": "enabled"}
    assert request.body["reasoning_effort"] == "high"
    assert request.body["response_format"] == {"type": "json_object"}
    assert request.body["stream"] is False
    assert "temperature" not in request.body
    assert "seed" not in request.body
    assert request.effective_seed == "unsupported"
    assert request.temperature_disposition == ("ignored_unsupported_in_thinking_mode")
    assert request.requested_temperature == 0.2
    assert request.headers == (("Content-Type", "application/json"),)
    assert request.judge_output_schema_sha256

    fingerprint = request.request_fingerprint
    body_copy = request.body
    body_copy["messages"][1]["content"] = "mutated after construction"
    assert request.body["messages"][1]["content"] == user_content
    assert request.request_fingerprint == fingerprint

    with pytest.raises(ProviderContractError, match="deidentified"):
        replace(
            request,
            data_attestation=replace(attestation, deidentified=False),
        )
    with pytest.raises(ProviderContractError, match="schema hash"):
        replace(request, judge_output_schema_sha256="0" * 64)

    with pytest.raises(ProviderContractError, match="deidentified"):
        adapter.build_request(
            system_prompt=system_prompt,
            user_content=user_content,
            criterion_id="semantic-01",
            allowed_evidence_refs=("response:final",),
            data_attestation=replace(attestation, deidentified=False),
        )
    with pytest.raises(ProviderContractError, match="non_sensitive"):
        adapter.build_request(
            system_prompt=system_prompt,
            user_content=user_content,
            criterion_id="semantic-01",
            allowed_evidence_refs=("response:final",),
            data_attestation=replace(attestation, non_sensitive=False),
        )


def test_deepseek_attestation_cannot_be_reused_for_different_input() -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    attestation = _deepseek_attestation(
        system_prompt=system_prompt,
        user_content=user_content,
    )

    with pytest.raises(ProviderContractError, match="input hash"):
        adapter.build_request(
            system_prompt=system_prompt,
            user_content=user_content + " changed",
            criterion_id="semantic-01",
            allowed_evidence_refs=("response:final",),
            data_attestation=attestation,
        )


def test_deepseek_execute_revalidates_canonical_request_bytes() -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    tampered_body = request.body
    tampered_body["messages"][1]["content"] = "changed after attestation"
    object.__setattr__(
        request,
        "body_bytes",
        json.dumps(
            tampered_body,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    )
    transport = _TestOnlyTransport(_deepseek_response())

    with pytest.raises(ProviderContractError, match="input hash"):
        adapter.execute(request=request, transport=transport)
    assert transport.requests == []


def test_deepseek_test_transport_parses_and_seals_external_judge_response() -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    raw_response = _deepseek_response()
    transport = _TestOnlyTransport(raw_response)
    transport_response = DeepSeekTransportResponse(
        status_code=200,
        raw_response=raw_response,
        received_at="2026-07-30T12:00:01Z",
    )
    assert "Private model reasoning" not in repr(transport_response)

    evidence = adapter.execute(request=request, transport=transport)

    assert len(transport.requests) == 1
    assert evidence.response_id == "chatcmpl-deepseek-001"
    assert evidence.model == "deepseek-v4-pro"
    assert evidence.system_fingerprint == "fp_backend_v4_pro"
    assert evidence.raw_response == raw_response
    assert evidence.raw_response_sha256
    assert evidence.transport_test_only is True
    assert evidence.transport_receipt is None
    assert evidence.usage.prompt_tokens == 100
    assert evidence.usage.prompt_cache_hit_tokens == 40
    assert evidence.usage.prompt_cache_miss_tokens == 60
    assert evidence.usage.completion_tokens == 25
    assert evidence.usage.reasoning_tokens == 15
    assert evidence.output == JUDGE_OUTPUT
    detached_output = evidence.output
    detached_output["evidence_refs"].append("mutated")
    assert evidence.output == JUDGE_OUTPUT
    assert evidence.reasoning_content_present is True
    assert evidence.reasoning_content_sha256
    public_evidence = evidence.to_dict()
    assert public_evidence["claim_scope"] == "contract_only"
    assert public_evidence["transport_receipt"] is None
    assert "raw_response" not in public_evidence
    assert "raw_response_base64" not in public_evidence
    assert public_evidence["raw_artifact_handling"] == (
        "in_memory_not_in_public_serialization"
    )
    assert "Private model reasoning" not in json.dumps(public_evidence)
    assert b"Private model reasoning" in evidence.raw_response
    assert "Private model reasoning" not in repr(evidence)

    with pytest.raises(ProviderContractError, match="raw response"):
        replace(evidence, response_id="forged-response-id")
    with pytest.raises(ProviderContractError, match="test_only"):
        require_production_deepseek_evidence(evidence)
    with pytest.raises(
        ProviderContractError,
        match="aggregate production.*batch authorization",
    ):
        require_production_deepseek_evidence(
            replace(evidence, transport_test_only=False)
        )


def test_deepseek_transport_receipt_is_bound_and_survives_protected_sealing(
    tmp_path: Path,
) -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    raw_response = _deepseek_response()
    receipt = _signed_transport_receipt(
        request=request,
        raw_response=raw_response,
    )
    evidence = adapter.execute(
        request=request,
        transport=_TestOnlyTransport(raw_response, receipt),
    )

    assert evidence.transport_receipt == receipt
    assert evidence.to_dict()["transport_receipt"] == receipt.to_dict()

    store = ProtectedRawArtifactStore(
        root=(tmp_path / "protected-receipt").resolve(),
        store_id="receipt-store",
    )
    manifest = RawArtifactHandlingManifest(
        manifest_id="receipt-handling-v1",
        store_id="receipt-store",
        media_type="application/json",
        acl_manifest_hash="d" * 64,
        observed_preflight_hash="e" * 64,
        retention_manifest_hash="f" * 64,
        public_export_forbidden=True,
        resolved_path_disclosure_forbidden=True,
    )
    protected = seal_protected_deepseek_evidence(
        evidence=evidence,
        store=store,
        handling_manifest=manifest,
        artifact_id="deepseek-receipt-response",
    )

    assert protected.transport_receipt == receipt
    assert (
        verify_protected_deepseek_evidence(
            evidence=protected,
            store=store,
            handling_manifest=manifest,
        ).transport_receipt
        == receipt
    )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("request_fingerprint", "0" * 64),
        ("request_bytes_hash", "1" * 64),
        ("data_attestation_hash", "2" * 64),
        ("criterion_id", "wrong-criterion"),
        ("requested_model_id", "deepseek-other"),
        ("observed_model_id", "deepseek-other"),
        ("response_hash", "3" * 64),
        ("response_size", 1),
    ),
)
def test_deepseek_adapter_rejects_misbound_transport_receipt(
    field_name: str,
    bad_value: object,
) -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    raw_response = _deepseek_response()
    receipt = _signed_transport_receipt(
        request=request,
        raw_response=raw_response,
        payload_changes={field_name: bad_value},
    )

    with pytest.raises(ProviderContractError, match="transport receipt binding"):
        adapter.execute(
            request=request,
            transport=_TestOnlyTransport(raw_response, receipt),
        )


def test_production_transport_requires_receipt_but_one_receipt_is_not_batch_authority() -> (
    None
):
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    raw_response = _deepseek_response()
    with pytest.raises(ProviderContractError, match="signed transport receipt"):
        adapter.execute(
            request=request,
            transport=_ProductionLabeledTransport(raw_response),
        )

    test_receipt = _signed_transport_receipt(
        request=request,
        raw_response=raw_response,
    )
    production_labeled_receipt = replace(
        test_receipt,
        envelope=replace(
            test_receipt.envelope,
            algorithm_id="production.signature.unverified.v1",
            test_only=False,
            signature_hex="d" * 64,
        ),
    )
    evidence = adapter.execute(
        request=request,
        transport=_ProductionLabeledTransport(
            raw_response,
            production_labeled_receipt,
        ),
    )
    with pytest.raises(
        ProviderContractError,
        match="aggregate production.*batch authorization",
    ):
        require_production_deepseek_evidence(evidence)


def test_deepseek_raw_response_is_write_once_protected_and_publicly_path_free(
    tmp_path: Path,
) -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )
    raw_response = _deepseek_response()
    evidence = adapter.execute(
        request=request,
        transport=_TestOnlyTransport(raw_response),
    )
    protected_root = (tmp_path / "protected-judge-raw").resolve()
    store = ProtectedRawArtifactStore(
        root=protected_root,
        store_id="deepseek-judge-raw",
    )
    manifest = RawArtifactHandlingManifest(
        manifest_id="deepseek-judge-raw-v1",
        store_id="deepseek-judge-raw",
        media_type="application/json",
        acl_manifest_hash="a" * 64,
        observed_preflight_hash="b" * 64,
        retention_manifest_hash="c" * 64,
        public_export_forbidden=True,
        resolved_path_disclosure_forbidden=True,
    )

    protected = seal_protected_deepseek_evidence(
        evidence=evidence,
        store=store,
        handling_manifest=manifest,
        artifact_id="deepseek-response-0001",
    )

    assert not hasattr(protected, "raw_response")
    assert protected.raw_artifact_receipt.raw_sha256 == (evidence.raw_response_sha256)
    assert protected.raw_artifact_receipt.source_evidence_hash == evidence.contract_hash
    assert (
        protected.raw_artifact_receipt.request_fingerprint
        == evidence.request_fingerprint
    )
    assert (
        verify_protected_deepseek_evidence(
            evidence=protected,
            store=store,
            handling_manifest=manifest,
        )
        == protected
    )
    serialized = json.dumps(protected.to_dict(), sort_keys=True)
    assert "Private model reasoning" not in serialized
    assert str(protected_root) not in serialized
    assert "resolved_path" not in serialized
    assert "content_base64" not in serialized
    assert "Private model reasoning" not in repr(protected)
    assert (protected_root / "deepseek-response-0001").read_bytes() == raw_response

    public = json.loads(protected.public_evidence_json)
    public["response_id"] = "forged-response"
    with pytest.raises(ProviderContractError, match="public evidence hash"):
        replace(
            protected,
            public_evidence_json=json.dumps(
                public,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
        )
    forged = protected.public_evidence
    forged["output"]["verdict"] = "fail"
    forged_body = {
        key: value for key, value in forged.items() if key != "contract_hash"
    }
    forged_hash = hashlib.sha256(
        json.dumps(
            forged_body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    forged["contract_hash"] = forged_hash
    forged_receipt = replace(
        protected.raw_artifact_receipt,
        source_evidence_hash=forged_hash,
    )
    self_consistent_forgery = replace(
        protected,
        public_evidence_json=json.dumps(
            forged,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode(),
        source_evidence_hash=forged_hash,
        raw_artifact_receipt=forged_receipt,
    )
    with pytest.raises(ProviderContractError, match="raw response"):
        verify_protected_deepseek_evidence(
            evidence=self_consistent_forgery,
            store=store,
            handling_manifest=manifest,
        )
    forged_authority = protected.public_evidence
    forged_authority["authority"] = "forged_authority"
    forged_authority_body = {
        key: value for key, value in forged_authority.items() if key != "contract_hash"
    }
    forged_authority_hash = hashlib.sha256(
        json.dumps(
            forged_authority_body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    forged_authority["contract_hash"] = forged_authority_hash
    with pytest.raises(ProviderContractError, match="authority boundary"):
        replace(
            protected,
            public_evidence_json=json.dumps(
                forged_authority,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            source_evidence_hash=forged_authority_hash,
            raw_artifact_receipt=replace(
                protected.raw_artifact_receipt,
                source_evidence_hash=forged_authority_hash,
            ),
        )
    with pytest.raises(ProviderContractError, match="test_only"):
        require_production_deepseek_evidence(protected)


@pytest.mark.parametrize(
    "invalid_output",
    (
        {**JUDGE_OUTPUT, "verdict": "disputed"},
        {**JUDGE_OUTPUT, "unexpected": True},
        {**JUDGE_OUTPUT, "evidence_refs": ["not-allowed"]},
        {key: value for key, value in JUDGE_OUTPUT.items() if key != "p_pass_0_1"},
        {**JUDGE_OUTPUT, "p_pass_0_1": 1.1},
        {**JUDGE_OUTPUT, "judge_version": "deepseek-v4-pro"},
    ),
)
def test_deepseek_judge_output_is_locally_strict(
    invalid_output: dict[str, object],
) -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )

    with pytest.raises(ProviderContractError, match="Judge output"):
        adapter.parse_response(
            request=request,
            transport_id="pytest-transport",
            transport_test_only=True,
            received_at="2026-07-30T12:00:01Z",
            raw_response=_deepseek_response(output=invalid_output),
        )


def test_deepseek_response_requires_frozen_model_fingerprint_and_usage() -> None:
    system_prompt = "Return strict JSON matching the frozen Judge schema."
    user_content = "Evaluate this deidentified response."
    adapter = DeepSeekV4ProJudgeAdapter()
    request = adapter.build_request(
        system_prompt=system_prompt,
        user_content=user_content,
        criterion_id="semantic-01",
        allowed_evidence_refs=("response:final",),
        data_attestation=_deepseek_attestation(
            system_prompt=system_prompt,
            user_content=user_content,
        ),
    )

    with pytest.raises(ProviderContractError, match="model"):
        adapter.parse_response(
            request=request,
            transport_id="pytest-transport",
            transport_test_only=True,
            received_at="2026-07-30T12:00:01Z",
            raw_response=_deepseek_response(model="deepseek-v4-flash"),
        )
    with pytest.raises(ProviderContractError, match="fingerprint"):
        adapter.parse_response(
            request=request,
            transport_id="pytest-transport",
            transport_test_only=True,
            received_at="2026-07-30T12:00:01Z",
            raw_response=_deepseek_response(fingerprint=""),
        )
    broken_usage = json.loads(_deepseek_response())
    broken_usage["usage"]["total_tokens"] = 999
    with pytest.raises(ProviderContractError, match="usage"):
        adapter.parse_response(
            request=request,
            transport_id="pytest-transport",
            transport_test_only=True,
            received_at="2026-07-30T12:00:01Z",
            raw_response=json.dumps(broken_usage).encode(),
        )
