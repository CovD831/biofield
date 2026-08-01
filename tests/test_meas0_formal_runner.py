from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import biofield.meas0_formal_runner as formal_runner
from biofield.meas0_r1 import (
    build_cold_chain_episode,
    load_cold_chain_evaluator,
    load_cold_chain_subject_input,
)
from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_formal_runner import (
    BackendExecution,
    BackendFailureEvidence,
    BackendMode,
    CanonicalEvaluationBinding,
    FailureCode,
    FormalArmRequest,
    FormalBackendExecutionError,
    FormalBackendDescriptor,
    FormalCostArtifact,
    FormalExecutionAuthorization,
    FormalFailureArtifact,
    FormalPilotCaseInput,
    FormalPilotPlan,
    FormalRunnerError,
    JudgeCallCostArtifact,
    RawObservationArtifact,
    RawResultArtifact,
    ResultValidity,
    _binding_error,
    run_formal_contract,
    validate_production_backends,
)
from biofield.meas0_readiness import (
    PriceManifest,
    ProviderPrice,
    arm_order_manifest,
    pilot_budget_policy,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    PhaseBudget,
    StageBudgetManifest,
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
from biofield.measurement import EvaluationStatus, MeasurementDimension, fuse_evidence


SHA = "a" * 64


def _price_manifest() -> PriceManifest:
    return PriceManifest(
        manifest_id="pytest.formal-price.v1",
        version=1,
        currency="USD",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="2026-07-31T00:00:00Z",
        direct_cap_microunits=1_000_000,
        provider_prices=(
            ProviderPrice(
                provider="fake",
                model_id="fake-judge",
                input_per_million_microunits=1,
                output_per_million_microunits=1,
                metered_tool_microunits=0,
            ),
        ),
    )


def _stage_budget_manifest(*, pilot_judge_calls: int = 240) -> StageBudgetManifest:
    budgets = []
    for phase in ("jcal", "pilot", "jaudit", "confirmatory"):
        caps = tuple(
            CategoryCallCap(
                category=category,
                max_calls=(
                    pilot_judge_calls
                    if phase == "pilot" and category is CostCategory.JUDGE
                    else 10_000
                ),
            )
            for category in CostCategory
        )
        budgets.append(
            PhaseBudget(
                phase=phase,
                max_calls=10_000,
                max_input_tokens=10_000_000,
                max_output_tokens=10_000_000,
                max_wall_time_ms=10_000_000,
                max_bytes_transferred=10_000_000,
                max_retries=10_000,
                max_monetary_microunits=10_000_000,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=caps,
            )
        )
    return StageBudgetManifest(
        manifest_id="pytest.formal-stage-budget.v1",
        version=1,
        phase_budgets=tuple(budgets),
    )


def _pre_ledger(
    *,
    price_manifest: PriceManifest,
    stage_budget_manifest: StageBudgetManifest,
) -> StageCostLedger:
    return StageCostLedger(
        ledger_id="pytest.formal-stage-cost.v1",
        version=1,
        price_manifest_hash=price_manifest.contract_hash,
        budget_manifest=stage_budget_manifest,
        entries=(),
    )


def _transport_binding(
    request: FormalArmRequest,
    *,
    attempt_index: int,
    outcome: TransportOutcome = TransportOutcome.SUCCESS,
) -> tuple[TransportBatchEntry, SignedTransportReceipt]:
    invocation_id = f"judge.{request.execution_index}.{request.arm_id}.{attempt_index}"
    batch_entry = TransportBatchEntry(
        sequence_number=0,
        invocation_id=invocation_id,
        criterion_id=request.case.fault_id,
        presentation_hash="1" * 64,
        data_attestation_hash="2" * 64,
        request_fingerprint=request.request_hash,
        request_bytes_hash=request.request_hash,
    )
    failed = outcome is TransportOutcome.FAILED
    payload = TransportReceiptPayload(
        schema_version=1,
        receipt_id=f"receipt.{invocation_id}",
        claim_scope=(
            TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION
            if failed
            else TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
        ),
        provider_id=f"fake.{request.arm_id}",
        endpoint_origin="https://judge.invalid",
        requested_model_id="fake-judge",
        observed_model_id="fake-judge",
        purpose="transport_receipt",
        phase="pilot",
        comparison_block_id="pytest-formal",
        comparison_lock_hash="3" * 64,
        design_hash="4" * 64,
        execution_authorization_hash=request.authorization_hash,
        invocation_id=invocation_id,
        criterion_id=batch_entry.criterion_id,
        presentation_hash=batch_entry.presentation_hash,
        data_attestation_hash=batch_entry.data_attestation_hash,
        request_fingerprint=batch_entry.request_fingerprint,
        request_bytes_hash=batch_entry.request_bytes_hash,
        outcome=outcome,
        failure_code="timeout" if failed else None,
        response_hash=None if failed else "5" * 64,
        response_size=None if failed else 10,
        http_status=None if failed else 200,
        started_at="2026-07-31T00:00:00Z",
        completed_at="2026-07-31T00:00:01Z",
        nonce=f"nonce.{invocation_id}",
        batch_id=f"batch.{invocation_id}",
        batch_manifest_hash=batch_entry.contract_hash,
        sequence_number=0,
        previous_receipt_hash=None,
        tls_peer_hostname="judge.invalid",
        tls_sni="judge.invalid",
        tls_certificate_sha256=None if failed else "6" * 64,
        tls_spki_sha256=None if failed else "7" * 64,
        tls_chain_sha256=None if failed else "8" * 64,
        tls_verification_result=(
            TLSVerificationResult.NOT_ESTABLISHED
            if failed
            else TLSVerificationResult.VERIFIED
        ),
        tls_trust_store_snapshot_hash="9" * 64,
        tls_verification_policy_hash="a" * 64,
    )
    receipt = SignedTransportReceipt(
        payload=payload,
        envelope=SignatureEnvelope(
            schema_version=1,
            envelope_id=f"envelope.{invocation_id}",
            trust_domain=TrustDomain.TRANSPORT,
            root_id="pytest-root",
            root_manifest_hash="b" * 64,
            key_fingerprint="c" * 64,
            algorithm_id="pytest-structural-only",
            role_id="pytest-gateway",
            purpose=payload.purpose,
            phase=payload.phase,
            payload_hash=payload.contract_hash,
            sequence_number=payload.sequence_number,
            nonce=payload.nonce,
            observed_signing_time="2026-07-31T00:00:02Z",
            test_only=True,
            signature_hex="d" * 64,
        ),
    )
    return batch_entry, receipt


def _canonical_evaluation_binding() -> CanonicalEvaluationBinding:
    evaluator = load_cold_chain_evaluator()
    episode = build_cold_chain_episode(
        subject_input=load_cold_chain_subject_input(),
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=b"no structured answer",
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="formal.canonical.test",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )
    return CanonicalEvaluationBinding(
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
        evaluation_result=result,
    )


def _case_inputs(
    *,
    semantic_leaf_count: int = 1,
) -> tuple[FormalPilotCaseInput, ...]:
    return tuple(
        FormalPilotCaseInput(
            case=item,
            task_hash=SHA,
            episode_hash="b" * 64,
            failure_policy_hash="c" * 64,
            semantic_leaf_count=semantic_leaf_count,
            measurement_count=2,
        )
        for item in formal_attack_manifest("pilot").cases
    )


def _plan(
    *,
    semantic_leaf_count: int = 1,
) -> FormalPilotPlan:
    price_manifest = _price_manifest()
    stage_budget_manifest = _stage_budget_manifest()
    return FormalPilotPlan(
        cases=_case_inputs(semantic_leaf_count=semantic_leaf_count),
        arm_order=arm_order_manifest(),
        budget_policy=pilot_budget_policy(),
        price_manifest=price_manifest,
        stage_budget_manifest=stage_budget_manifest,
        stage_cost_pre_ledger=_pre_ledger(
            price_manifest=price_manifest,
            stage_budget_manifest=stage_budget_manifest,
        ),
    )


class FakeProvider:
    def __init__(
        self,
        arm_id: str,
        *,
        mode: BackendMode = BackendMode.TEST_ONLY,
        judge_calls: int = 0,
        deterministic_checks: int = 0,
        failure: str | None = None,
        authorization_hash_override: str | None = None,
        accounting_complete: bool = True,
    ) -> None:
        self.descriptor = FormalBackendDescriptor(
            provider_id=f"fake.{arm_id}",
            provider_version="1",
            arm_id=arm_id,
            mode=mode,
            enforces_timeouts=(mode is BackendMode.PRODUCTION),
        )
        self.judge_calls = judge_calls
        self.deterministic_checks = deterministic_checks
        self.failure = failure
        self.authorization_hash_override = authorization_hash_override
        self.accounting_complete = accounting_complete
        self.calls: list[tuple[int, str, str]] = []

    def execute(self, request):
        self.calls.append(
            (request.execution_index, request.case.case_id, request.arm_id)
        )
        if self.failure == "timeout" and len(self.calls) == 1:
            raise TimeoutError("fake timeout")
        case_id = (
            "pilot.cold_chain_readiness.F18.seed1729"
            if self.failure == "mismatch" and len(self.calls) == 1
            else request.case.case_id
        )
        judge_call_costs = tuple(
            JudgeCallCostArtifact(
                input_tokens=10,
                output_tokens=4,
                wall_time_ms=5,
                transport_batch_entry=batch_entry,
                transport_receipt=receipt,
            )
            for index in range(self.judge_calls)
            for batch_entry, receipt in (
                _transport_binding(request, attempt_index=index),
            )
        )
        cost = FormalCostArtifact(
            judge_calls=self.judge_calls,
            deterministic_check_calls=self.deterministic_checks,
            deterministic_wall_time_ms=5 if self.deterministic_checks else 0,
            input_tokens=10 * self.judge_calls,
            output_tokens=4 * self.judge_calls,
            accounting_complete=self.accounting_complete,
        )
        return BackendExecution(
            authorization_hash=(
                self.authorization_hash_override or request.authorization_hash
            ),
            case_id=case_id,
            arm_id=request.arm_id,
            observations=(
                RawObservationArtifact(
                    observation_id=(f"obs.{request.execution_index}.{request.arm_id}"),
                    case_id=request.case.case_id,
                    arm_id=request.arm_id,
                    source="fake",
                    payload_json='{"signal":"ok"}',
                ),
            ),
            raw_result=RawResultArtifact(
                result_id=f"raw.{request.execution_index}.{request.arm_id}",
                case_id=case_id,
                arm_id=request.arm_id,
                automatic_status=EvaluationStatus.FAIL,
                timed_out=False,
                payload_json='{"decision":"fail"}',
            ),
            cost=cost,
            judge_call_costs=judge_call_costs,
        )


def _providers(
    *,
    mode: BackendMode = BackendMode.TEST_ONLY,
) -> dict[str, FakeProvider]:
    return {
        "self_eval": FakeProvider("self_eval", mode=mode),
        "judge_only": FakeProvider(
            "judge_only",
            mode=mode,
            judge_calls=1,
        ),
        "state_only": FakeProvider(
            "state_only",
            mode=mode,
            deterministic_checks=1,
        ),
        "rules_state": FakeProvider(
            "rules_state",
            mode=mode,
            deterministic_checks=1,
        ),
        "evaluation_plane": FakeProvider(
            "evaluation_plane",
            mode=mode,
            deterministic_checks=1,
        ),
    }


def test_plan_rejects_any_denominator_or_case_order_drift() -> None:
    cases = _case_inputs()
    reference = _plan()
    kwargs = {
        "arm_order": arm_order_manifest(),
        "budget_policy": pilot_budget_policy(),
        "price_manifest": reference.price_manifest,
        "stage_budget_manifest": reference.stage_budget_manifest,
        "stage_cost_pre_ledger": reference.stage_cost_pre_ledger,
    }
    with pytest.raises(FormalRunnerError, match="36"):
        FormalPilotPlan(cases=cases[:-1], **kwargs)
    with pytest.raises(FormalRunnerError, match="order"):
        FormalPilotPlan(
            cases=(cases[1], cases[0], *cases[2:]),
            **kwargs,
        )
    with pytest.raises(FormalRunnerError, match="duplicate"):
        FormalPilotPlan(
            cases=(cases[0], cases[0], *cases[2:]),
            **kwargs,
        )


def test_test_only_backend_runs_deterministic_36_by_5_contract_e2e() -> None:
    plan = _plan()
    providers = _providers()
    run = run_formal_contract(plan, providers)

    expected_order = tuple(
        (case.case.case_id, arm_id)
        for case in plan.cases
        for arm_id in plan.arm_order.resolved_arm_order
    )
    assert run.claim_scope == "contract_only"
    assert run.formal_result is False
    assert run.case_count == 36
    assert run.arm_case_count == 180
    assert (
        tuple((item.case_id, item.arm_id) for item in run.artifacts) == expected_order
    )
    assert all(item.retained_in_denominator for item in run.artifacts)
    assert all(item.claim_scope == "contract_only" for item in run.artifacts)
    assert all(item.raw_result is not None for item in run.artifacts)
    assert all(item.observations for item in run.artifacts)
    assert all(item.cost is not None for item in run.artifacts)
    assert all(item.failure is None for item in run.artifacts)
    assert all(
        item.authorization_hash == run.authorization.authorization_hash
        for item in run.artifacts
    )
    calls = [call for provider in providers.values() for call in provider.calls]
    assert (
        tuple((case_id, arm_id) for _, case_id, arm_id in sorted(calls))
        == expected_order
    )

    replay = run_formal_contract(_plan(), _providers())
    assert replay.run_hash == run.run_hash


def test_formal_result_cannot_be_upgraded_independently_of_authorization() -> None:
    run = run_formal_contract(_plan(), _providers())

    with pytest.raises(FormalRunnerError, match="formal_result is not derived"):
        replace(run, formal_result=True)


def test_production_run_derives_formal_result_from_readiness_bound_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()

    class StubFormalReadyBundle:
        def __init__(self) -> None:
            self.report = SimpleNamespace(
                state=formal_runner.FormalReadinessState.FORMAL_READY
            )
            self.inputs = SimpleNamespace(
                price_manifest=plan.price_manifest,
                stage_budget_manifest=plan.stage_budget_manifest,
                stage_cost_ledger=plan.stage_cost_pre_ledger,
                judge_evidence=object(),
                human_evidence=object(),
                preflight_report=object(),
            )
            self.bundle_hash = "9" * 64

    monkeypatch.setattr(
        formal_runner,
        "FormalReadinessBundle",
        StubFormalReadyBundle,
    )
    monkeypatch.setattr(
        formal_runner,
        "validate_production_backends",
        lambda *_args, **_kwargs: None,
    )

    run = run_formal_contract(
        plan,
        _providers(mode=BackendMode.PRODUCTION),
        production_readiness=StubFormalReadyBundle(),
        execution_id="pytest.production.formal-result",
    )

    assert run.authorization.mode is BackendMode.PRODUCTION
    assert run.authorization.readiness_bundle_hash == "9" * 64
    assert run.formal_result is True
    with pytest.raises(FormalRunnerError, match="formal_result is not derived"):
        replace(run, formal_result=False)


def test_execution_authorization_binds_plan_providers_and_execution_identity() -> None:
    plan = _plan()
    providers = _providers()
    first = run_formal_contract(
        plan,
        providers,
        execution_id="pytest.formal.execution.a",
    )
    second = run_formal_contract(
        plan,
        _providers(),
        execution_id="pytest.formal.execution.b",
    )

    assert isinstance(first.authorization, FormalExecutionAuthorization)
    assert first.authorization.plan_hash == plan.plan_hash
    assert first.authorization.price_manifest_hash == plan.price_manifest.contract_hash
    assert (
        first.authorization.stage_budget_manifest_hash
        == plan.stage_budget_manifest.contract_hash
    )
    assert (
        first.authorization.stage_cost_pre_ledger_hash
        == plan.stage_cost_pre_ledger.contract_hash
    )
    assert first.authorization.authorization_hash != (
        second.authorization.authorization_hash
    )
    assert first.run_hash != second.run_hash


def test_run_seals_typed_stage_cost_prefix_and_final_ledger() -> None:
    plan = _plan()
    run = run_formal_contract(plan, _providers())

    assert run.stage_cost_pre_ledger == plan.stage_cost_pre_ledger
    assert run.stage_cost_final_ledger.entries[
        : len(plan.stage_cost_pre_ledger.entries)
    ] == (plan.stage_cost_pre_ledger.entries)
    assert run.stage_cost_pre_ledger_hash == plan.stage_cost_pre_ledger.contract_hash
    assert run.stage_cost_final_ledger_hash == (
        run.stage_cost_final_ledger.contract_hash
    )
    actual_judge_attempts = sum(artifact.cost.judge_calls for artifact in run.artifacts)
    assert (
        len(run.stage_cost_final_ledger.entries)
        - len(run.stage_cost_pre_ledger.entries)
        == actual_judge_attempts
    )
    assert (
        run.stage_stopped is run.stage_cost_final_ledger.phase_decision("pilot").stopped
    )
    assert all(
        entry.request_hash
        == next(
            artifact.request_hash
            for artifact in run.artifacts
            if entry.contract_hash in artifact.stage_cost_entry_hashes
        )
        for entry in run.stage_cost_final_ledger.entries
    )


def test_judge_attempt_receipt_batch_entry_and_ledger_cross_bind() -> None:
    run = run_formal_contract(_plan(), _providers())
    judged = next(item for item in run.artifacts if item.arm_id == "judge_only")

    assert len(judged.judge_call_costs) == 1
    assert len(judged.stage_cost_entry_hashes) == 1
    attempt = judged.judge_call_costs[0]
    entry = next(
        item
        for item in run.stage_cost_final_ledger.entries
        if item.contract_hash == judged.stage_cost_entry_hashes[0]
    )
    assert attempt.transport_batch_entry.invocation_id == (
        attempt.transport_receipt.payload.invocation_id
    )
    assert entry.raw_receipt_hash == attempt.transport_receipt.contract_hash
    assert entry.call_hash == attempt.transport_receipt.payload.contract_hash
    assert entry.request_hash == judged.request_hash

    with pytest.raises(FormalRunnerError, match="transport.*binding"):
        replace(
            attempt,
            transport_batch_entry=replace(
                attempt.transport_batch_entry,
                request_bytes_hash="e" * 64,
            ),
        )

    other = next(
        item
        for item in run.artifacts
        if item.arm_id == "judge_only"
        and item.execution_index != judged.execution_index
    )
    receipt_swapped = replace(
        judged,
        judge_call_costs=other.judge_call_costs,
    )
    with pytest.raises(FormalRunnerError, match="cross-binding"):
        replace(
            run,
            artifacts=tuple(
                receipt_swapped if item is judged else item for item in run.artifacts
            ),
        )


def test_missing_or_duplicate_judge_transport_evidence_fails_closed() -> None:
    with pytest.raises(FormalRunnerError, match="transport"):
        JudgeCallCostArtifact(
            input_tokens=1,
            output_tokens=1,
            wall_time_ms=1,
        )

    providers = _providers()
    original = providers["judge_only"]

    class DuplicateReceiptProvider:
        descriptor = original.descriptor

        def __init__(self) -> None:
            self.attempt = None

        def execute(self, arm_request):
            execution = original.execute(arm_request)
            attempt = execution.judge_call_costs[0]
            if self.attempt is None:
                self.attempt = attempt
                return execution
            return replace(execution, judge_call_costs=(self.attempt,))

    providers["judge_only"] = DuplicateReceiptProvider()
    run = run_formal_contract(_plan(), providers)
    duplicate = next(
        item
        for item in run.artifacts
        if item.arm_id == "judge_only" and item.execution_index > 5
    )
    assert duplicate.failure is not None
    assert duplicate.failure.code is FailureCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("code", "validity", "status"),
    (
        (FailureCode.TIMEOUT, ResultValidity.VALID, EvaluationStatus.UNKNOWN),
        (
            FailureCode.PROVIDER_ERROR,
            ResultValidity.INVALID,
            EvaluationStatus.INVALID,
        ),
    ),
)
def test_failed_actual_judge_attempt_is_retained_in_stage_cost(
    code: FailureCode,
    validity: ResultValidity,
    status: EvaluationStatus,
) -> None:
    providers = _providers()
    base = providers["judge_only"]

    class FailedJudgeProvider:
        descriptor = base.descriptor

        def execute(self, request):
            batch_entry, receipt = _transport_binding(
                request,
                attempt_index=0,
                outcome=TransportOutcome.FAILED,
            )
            attempt = JudgeCallCostArtifact(
                input_tokens=3,
                output_tokens=0,
                wall_time_ms=9,
                transport_batch_entry=batch_entry,
                transport_receipt=receipt,
            )
            raise FormalBackendExecutionError(
                code=code,
                message="typed failed Judge attempt",
                evidence=BackendFailureEvidence(
                    authorization_hash=request.authorization_hash,
                    case_id=request.case.case_id,
                    arm_id=request.arm_id,
                    cost=FormalCostArtifact(
                        judge_calls=1,
                        input_tokens=3,
                        wall_time_ms=9,
                    ),
                    judge_call_costs=(attempt,),
                ),
            )

    providers["judge_only"] = FailedJudgeProvider()
    run = run_formal_contract(_plan(), providers)
    failed = next(item for item in run.artifacts if item.arm_id == "judge_only")

    assert failed.failure.code is code
    assert failed.result_validity is validity
    assert failed.automatic_status is status
    assert len(failed.stage_cost_entry_hashes) == 1
    entry = next(
        item
        for item in run.stage_cost_final_ledger.entries
        if item.contract_hash == failed.stage_cost_entry_hashes[0]
    )
    assert entry.outcome.value == "failed"
    assert entry.failure_code == "timeout"
    assert entry.raw_receipt_hash == (
        failed.judge_call_costs[0].transport_receipt.contract_hash
    )


def test_backend_response_from_another_authorization_fails_closed() -> None:
    providers = _providers()
    providers["self_eval"] = FakeProvider(
        "self_eval",
        authorization_hash_override="d" * 64,
    )

    run = run_formal_contract(
        _plan(),
        providers,
        execution_id="pytest.formal.execution.replay-attack",
    )

    attacked = tuple(item for item in run.artifacts if item.arm_id == "self_eval")
    assert attacked
    assert attacked[0].failure is not None
    assert attacked[0].failure.code is FailureCode.MALFORMED_RESPONSE
    assert "authorization" in attacked[0].failure.message
    assert run.stage_stopped is False
    assert any(
        item.failure is None
        for item in run.artifacts[attacked[0].execution_index + 1 :]
    )


def test_artifact_and_run_reject_identity_status_and_authorization_tampering() -> None:
    run = run_formal_contract(
        _plan(),
        _providers(),
        execution_id="pytest.formal.execution.artifact-tamper",
    )
    artifact = run.artifacts[0]

    with pytest.raises(FormalRunnerError, match="case/task/fault"):
        replace(artifact, task_id="channel_order_ingest")
    with pytest.raises(FormalRunnerError, match="authoritative result"):
        replace(artifact, automatic_status=EvaluationStatus.PASS)

    forged_ancestry = replace(artifact, authorization_hash="f" * 64)
    with pytest.raises(FormalRunnerError, match="authorization ancestry"):
        replace(run, artifacts=(forged_ancestry, *run.artifacts[1:]))

    with pytest.raises(FormalRunnerError, match="failure disposition"):
        replace(
            artifact,
            failure=FormalFailureArtifact(
                code=FailureCode.TIMEOUT,
                message="forged timeout",
            ),
            automatic_status=EvaluationStatus.PASS,
        )
    with pytest.raises(FormalRunnerError, match="accounting"):
        replace(
            artifact,
            cost=replace(artifact.cost, accounting_complete=False),
        )
    with pytest.raises(FormalRunnerError, match="timed out"):
        replace(
            artifact,
            raw_result=replace(artifact.raw_result, timed_out=True),
        )

    changed_backend = replace(artifact, backend_id="unbound.backend")
    with pytest.raises(FormalRunnerError, match="backend identity"):
        replace(run, artifacts=(changed_backend, *run.artifacts[1:]))
    with pytest.raises(FormalRunnerError, match="stage_stopped"):
        replace(run, stage_stopped=True)


def test_production_authorization_and_run_cannot_be_directly_forged() -> None:
    plan = _plan()
    test_authorization = run_formal_contract(plan, _providers()).authorization
    with pytest.raises(FormalRunnerError, match="must be derived"):
        FormalExecutionAuthorization(
            execution_id=test_authorization.execution_id,
            mode=test_authorization.mode,
            plan_hash=test_authorization.plan_hash,
            readiness_bundle_hash=test_authorization.readiness_bundle_hash,
            price_manifest_hash=test_authorization.price_manifest_hash,
            stage_budget_manifest_hash=(test_authorization.stage_budget_manifest_hash),
            stage_cost_pre_ledger_hash=(test_authorization.stage_cost_pre_ledger_hash),
            provider_descriptors=test_authorization.provider_descriptors,
            provider_manifest_hash=test_authorization.provider_manifest_hash,
            authorization_hash=test_authorization.authorization_hash,
        )

    production = _providers(mode=BackendMode.PRODUCTION)
    descriptors = tuple(
        production[arm].descriptor for arm in plan.arm_order.resolved_arm_order
    )
    with pytest.raises(FormalRunnerError, match="FORMAL_READY"):
        FormalExecutionAuthorization.create(
            execution_id="pytest.production.authorization",
            mode=BackendMode.PRODUCTION,
            plan=plan,
            readiness_bundle=None,
            provider_descriptors=descriptors,
        )


def test_formal_request_validates_all_frozen_identity_and_hash_fields() -> None:
    case = formal_attack_manifest("pilot").cases[0]
    request = FormalArmRequest(
        authorization_hash="a" * 64,
        execution_index=0,
        case=case,
        arm_id="self_eval",
        task_hash="b" * 64,
        episode_hash="c" * 64,
        failure_policy_hash="d" * 64,
        semantic_leaf_count=1,
        measurement_count=2,
        budget_policy_hash="e" * 64,
        price_manifest_hash="f" * 64,
        stage_budget_manifest_hash="1" * 64,
        stage_cost_pre_ledger_hash="2" * 64,
    )
    with pytest.raises(FormalRunnerError, match="execution_index"):
        replace(request, execution_index=-1)
    with pytest.raises(FormalRunnerError, match="case"):
        replace(request, case="not-a-case")
    with pytest.raises(FormalRunnerError, match="task_hash"):
        replace(request, task_hash="not-a-hash")


def test_canonical_binding_requires_exact_frozen_bundle_hash() -> None:
    binding = _canonical_evaluation_binding()
    case = formal_attack_manifest("pilot").cases[0]
    request = FormalArmRequest(
        authorization_hash="a" * 64,
        execution_index=0,
        case=case,
        arm_id="evaluation_plane",
        task_hash="b" * 64,
        episode_hash=binding.sealed_episode.episode_hash,
        failure_policy_hash="d" * 64,
        semantic_leaf_count=1,
        measurement_count=len(
            binding.task_measurement_bundle.measurement_graph.measurement_specs
        ),
        budget_policy_hash="e" * 64,
        price_manifest_hash="f" * 64,
        stage_budget_manifest_hash="1" * 64,
        stage_cost_pre_ledger_hash="2" * 64,
    )
    execution = BackendExecution(
        authorization_hash=request.authorization_hash,
        case_id=case.case_id,
        arm_id=request.arm_id,
        observations=(
            RawObservationArtifact(
                observation_id="raw.bundle-binding",
                case_id=case.case_id,
                arm_id=request.arm_id,
                source="pytest",
                payload_json='{"source":"canonical"}',
            ),
        ),
        raw_result=RawResultArtifact(
            result_id="raw.bundle-binding",
            case_id=case.case_id,
            arm_id=request.arm_id,
            automatic_status=binding.evaluation_result.outcome,
            timed_out=False,
            payload_json='{"status":"fail"}',
        ),
        cost=FormalCostArtifact(),
        canonical_evaluation=binding,
    )

    assert "bundle hash" in _binding_error(
        request,
        execution,
        require_canonical=True,
    )
    assert (
        _binding_error(
            replace(
                request,
                task_hash=binding.task_measurement_bundle.bundle_hash,
                semantic_leaf_count=sum(
                    requirement.dimension is MeasurementDimension.SEMANTIC
                    for requirement in binding.task_measurement_bundle.requirement_graph.requirements
                ),
            ),
            execution,
            require_canonical=True,
        )
        is None
    )

    assert "semantic leaf count" in _binding_error(
        replace(
            request,
            task_hash=binding.task_measurement_bundle.bundle_hash,
            semantic_leaf_count=999,
        ),
        execution,
        require_canonical=True,
    )
    assert "semantic leaf count" in _binding_error(
        request,
        replace(
            execution,
            cost=FormalCostArtifact(
                judge_calls=1,
                input_tokens=10,
                output_tokens=4,
            ),
            judge_call_costs=(
                JudgeCallCostArtifact(
                    input_tokens=10,
                    output_tokens=4,
                    wall_time_ms=5,
                    transport_batch_entry=_transport_binding(
                        request,
                        attempt_index=0,
                    )[0],
                    transport_receipt=_transport_binding(
                        request,
                        attempt_index=0,
                    )[1],
                ),
            ),
            canonical_evaluation=None,
        ),
        require_canonical=False,
    )


def test_binding_rejects_incomplete_and_underreported_judge_accounting() -> None:
    binding = _canonical_evaluation_binding()
    case = formal_attack_manifest("pilot").cases[0]
    semantic_leaf_count = sum(
        requirement.dimension is MeasurementDimension.SEMANTIC
        for requirement in binding.task_measurement_bundle.requirement_graph.requirements
    )
    request = FormalArmRequest(
        authorization_hash="a" * 64,
        execution_index=0,
        case=case,
        arm_id="evaluation_plane",
        task_hash=binding.task_measurement_bundle.bundle_hash,
        episode_hash=binding.sealed_episode.episode_hash,
        failure_policy_hash="d" * 64,
        semantic_leaf_count=semantic_leaf_count,
        measurement_count=len(
            binding.task_measurement_bundle.measurement_graph.measurement_specs
        ),
        budget_policy_hash="e" * 64,
        price_manifest_hash="f" * 64,
        stage_budget_manifest_hash="1" * 64,
        stage_cost_pre_ledger_hash="2" * 64,
    )
    execution = BackendExecution(
        authorization_hash=request.authorization_hash,
        case_id=case.case_id,
        arm_id=request.arm_id,
        observations=(
            RawObservationArtifact(
                observation_id="raw.accounting",
                case_id=case.case_id,
                arm_id=request.arm_id,
                source="pytest",
                payload_json='{"source":"canonical"}',
            ),
        ),
        raw_result=RawResultArtifact(
            result_id="raw.accounting",
            case_id=case.case_id,
            arm_id=request.arm_id,
            automatic_status=binding.evaluation_result.outcome,
            timed_out=False,
            payload_json='{"status":"fail"}',
        ),
        cost=FormalCostArtifact(
            judge_calls=1,
            input_tokens=9,
            output_tokens=4,
        ),
        judge_call_costs=(
            JudgeCallCostArtifact(
                input_tokens=10,
                output_tokens=4,
                wall_time_ms=5,
                transport_batch_entry=_transport_binding(
                    request,
                    attempt_index=0,
                )[0],
                transport_receipt=_transport_binding(
                    request,
                    attempt_index=0,
                )[1],
            ),
        ),
        canonical_evaluation=binding,
    )

    assert "aggregate Judge token accounting" in _binding_error(
        request,
        execution,
        require_canonical=True,
    )
    assert "incomplete cost accounting" in _binding_error(
        request,
        replace(
            execution,
            cost=replace(
                execution.cost,
                accounting_complete=False,
                input_tokens=10,
            ),
        ),
        require_canonical=True,
    )


def test_malformed_accounting_is_retained_without_forging_budget_stop() -> None:
    providers = _providers()
    first_arm = arm_order_manifest().resolved_arm_order[0]
    providers[first_arm] = FakeProvider(
        first_arm,
        accounting_complete=False,
    )

    run = run_formal_contract(_plan(), providers)

    assert run.stage_stopped is False
    assert run.artifacts[0].failure.code is FailureCode.MALFORMED_RESPONSE
    assert any(artifact.failure is None for artifact in run.artifacts[1:])
    assert sum(len(provider.calls) for provider in providers.values()) == 180


def test_artifact_local_counters_cannot_forge_stage_stop() -> None:
    run = run_formal_contract(_plan(), _providers())
    terminal = run.artifacts[-1]
    terminal_with_forged_local_counter = replace(
        terminal,
        cost=replace(
            terminal.cost,
            human_escalations=pilot_budget_policy().pilot_human_escalations + 5,
        ),
    )

    replaced = replace(
        run,
        artifacts=(*run.artifacts[:-1], terminal_with_forged_local_counter),
    )
    assert replaced.stage_stopped is False
    with pytest.raises(FormalRunnerError, match="stage_stopped"):
        replace(replaced, stage_stopped=True)


def test_timeout_malformed_response_and_budget_failure_fail_closed() -> None:
    providers = _providers()
    providers["self_eval"] = FakeProvider(
        "self_eval",
        deterministic_checks=1,
        failure="timeout",
    )
    providers["judge_only"] = FakeProvider(
        "judge_only",
        failure="mismatch",
    )
    providers["state_only"] = FakeProvider(
        "state_only",
        deterministic_checks=100,
    )
    run = run_formal_contract(_plan(), providers)

    assert run.arm_case_count == 180
    timeout = next(
        item
        for item in run.artifacts
        if item.case_id.endswith("F01.seed1729") and item.arm_id == "self_eval"
    )
    assert timeout.automatic_status is EvaluationStatus.UNKNOWN
    assert timeout.failure.code is FailureCode.TIMEOUT
    assert timeout.result_validity is ResultValidity.VALID
    assert timeout.cost.accounting_complete is False

    prohibited = next(
        item
        for item in run.artifacts
        if item.case_id.endswith("F02.seed1729") and item.arm_id == "self_eval"
    )
    assert prohibited.automatic_status is EvaluationStatus.INVALID
    assert prohibited.failure.code is FailureCode.PROTOCOL_VIOLATION
    assert prohibited.result_validity is ResultValidity.INVALID

    malformed = next(
        item
        for item in run.artifacts
        if item.case_id.endswith("F01.seed1729") and item.arm_id == "judge_only"
    )
    assert malformed.automatic_status is EvaluationStatus.INVALID
    assert malformed.failure.code is FailureCode.MALFORMED_RESPONSE
    assert malformed.result_validity is ResultValidity.INVALID

    exhausted = next(
        item
        for item in run.artifacts
        if item.case_id.endswith("F01.seed1729") and item.arm_id == "state_only"
    )
    assert exhausted.automatic_status is EvaluationStatus.UNKNOWN
    assert exhausted.failure.code is FailureCode.BUDGET_EXHAUSTED
    assert exhausted.result_validity is ResultValidity.VALID
    assert all(item.retained_in_denominator for item in run.artifacts)


def test_stage_budget_stops_calls_but_materializes_remaining_denominator() -> None:
    providers = _providers()
    providers["judge_only"] = FakeProvider("judge_only", judge_calls=2)
    providers["evaluation_plane"] = FakeProvider(
        "evaluation_plane",
        judge_calls=6,
        deterministic_checks=1,
    )
    run = run_formal_contract(
        _plan(semantic_leaf_count=3),
        providers,
    )

    assert run.arm_case_count == 180
    assert run.stage_stopped is True
    assert any(
        item.failure is not None
        and item.failure.code is FailureCode.STAGE_BUDGET_EXHAUSTED
        for item in run.artifacts
    )
    assert sum(len(provider.calls) for provider in providers.values()) < 180
    assert all(item.retained_in_denominator for item in run.artifacts)


def test_production_validator_rejects_test_backends_and_missing_evidence() -> None:
    with pytest.raises(FormalRunnerError, match="test_only"):
        validate_production_backends(_providers(), readiness_bundle=None)

    production = _providers(mode=BackendMode.PRODUCTION)
    with pytest.raises(
        FormalRunnerError,
        match="Judge.*human.*preflight",
    ):
        validate_production_backends(production, readiness_bundle=None)

    no_timeout = dict(production)
    no_timeout["self_eval"] = FakeProvider(
        "self_eval",
        mode=BackendMode.PRODUCTION,
    )
    no_timeout["self_eval"].descriptor = replace(
        no_timeout["self_eval"].descriptor,
        enforces_timeouts=False,
    )
    with pytest.raises(FormalRunnerError, match="timeout"):
        validate_production_backends(no_timeout, readiness_bundle=None)


def test_canonical_evaluation_binding_rederives_status_from_sealed_leaves() -> None:
    binding = _canonical_evaluation_binding()
    assert binding.evaluation_result.outcome is EvaluationStatus.FAIL

    with pytest.raises(FormalRunnerError, match="canonical fusion"):
        replace(
            binding,
            evaluation_result=replace(
                binding.evaluation_result,
                outcome=EvaluationStatus.PASS,
            ),
        )
    with pytest.raises(FormalRunnerError, match="reported status"):
        BackendExecution(
            authorization_hash="d" * 64,
            case_id="pilot.cold_chain_readiness.F01.seed1729",
            arm_id="self_eval",
            observations=(
                RawObservationArtifact(
                    observation_id="obs.canonical-mismatch",
                    case_id="pilot.cold_chain_readiness.F01.seed1729",
                    arm_id="self_eval",
                    source="fake",
                    payload_json='{"signal":"ok"}',
                ),
            ),
            raw_result=RawResultArtifact(
                result_id="raw.canonical-mismatch",
                case_id="pilot.cold_chain_readiness.F01.seed1729",
                arm_id="self_eval",
                automatic_status=EvaluationStatus.PASS,
                timed_out=False,
                payload_json='{"decision":"pass"}',
            ),
            cost=FormalCostArtifact(),
            canonical_evaluation=binding,
        )


def test_production_runner_cannot_bypass_typed_readiness_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "biofield.meas0_formal_runner.validate_production_backends",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(FormalRunnerError, match="typed FORMAL_READY"):
        run_formal_contract(
            _plan(),
            _providers(mode=BackendMode.PRODUCTION),
            production_readiness=None,
        )
