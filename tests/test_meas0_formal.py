from __future__ import annotations

import json
import hashlib
from dataclasses import replace

import pytest

from biofield.measurement import EvaluationStatus
from biofield.meas0_judge_probes import (
    JudgeProbeCall,
    JudgeProbeManifest,
    JudgeProbeRelation,
    ProbeKind,
)
from biofield.meas0_formal import (
    DerivedJudgeQualification,
    EvidenceAttestation,
    ExactInvocationEntry,
    ExactInvocationManifest,
    FormalEvidenceError,
    JudgeCallRecord,
    JudgeCallOutcome,
    ProbeJudgeCorpus,
    JudgeCorpusRunner,
    JudgeExecutionBudget,
    JudgeProviderRequest,
    RawJudgeResult,
    derive_jaudit_qualification,
    derive_jcal_qualification,
    derive_probe_qualification,
    derived_probe_judge_qualification_from_dict,
    derived_judge_qualification_from_dict,
    fuse_corpus_presentations,
    require_production_judge_evidence,
    require_production_probe_judge_evidence,
)
from biofield.meas0_readiness import (
    FormalReadinessInputs,
    FormalReadinessValidator,
    JAuditManifest,
    JCalManifest,
    JudgeCard,
    JudgeInvocation,
    JudgeResponse,
    JudgeSetItem,
    RateEstimate,
    ReadinessBlockerCode,
)
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
    SignatureEnvelope,
    SignedTransportReceipt,
    TLSVerificationResult,
    TransportBatchEntry,
    TransportBatchPlan,
    TransportClaimScope,
    TransportOutcome,
    TransportReceiptBatch,
    TransportReceiptPayload,
    TrustDomain,
)


def _hash(character: str) -> str:
    return character * 64


def test_exact_invocation_manifest_rejects_duplicate_or_reordered_membership() -> None:
    first = ExactInvocationEntry(
        sequence_number=0,
        phase="jcal",
        probe_call_id="probe-0",
        item_id="item-00",
        invocation_id="invocation-0",
        criterion_id="criterion-00",
        presentation_hash=_hash("1"),
        request_fingerprint=_hash("2"),
        call_record_hash=_hash("3"),
        transport_entry_hash=_hash("4"),
        receipt_hash=_hash("5"),
        stage_cost_entry_hash=_hash("6"),
    )
    valid = ExactInvocationManifest(
        schema_version=1,
        manifest_id="jcal-exact-invocations",
        phase="jcal",
        probe_manifest_hash=_hash("7"),
        corpus_hash=_hash("8"),
        transport_batch_hash=_hash("9"),
        stage_cost_ledger_hash=_hash("a"),
        entries=(first,),
    )
    assert ExactInvocationManifest.from_dict(valid.to_dict()) == valid
    with pytest.raises(FormalEvidenceError, match="contiguous|unique"):
        ExactInvocationManifest(
            schema_version=1,
            manifest_id="jcal-exact-invocations",
            phase="jcal",
            probe_manifest_hash=_hash("7"),
            corpus_hash=_hash("8"),
            transport_batch_hash=_hash("9"),
            stage_cost_ledger_hash=_hash("a"),
            entries=(first, replace(first, probe_call_id="probe-1")),
        )


def _manifest() -> JCalManifest:
    labels = (
        [EvaluationStatus.PASS] * 16
        + [EvaluationStatus.FAIL] * 16
        + [EvaluationStatus.UNKNOWN] * 16
    )
    return JCalManifest(
        manifest_id="J-CAL-v1",
        version=1,
        effective_seeds=(8111, 8117),
        items=tuple(
            JudgeSetItem(
                item_id=f"item-{index:02d}",
                criterion_id=f"criterion-{index:02d}",
                gold_verdict=verdict,
                normal_presentation_hash=_hash("a"),
                reversed_presentation_hash=_hash("b"),
                held_out=False,
            )
            for index, verdict in enumerate(labels)
        ),
    )


def _audit_manifest() -> JAuditManifest:
    calibration = _manifest()
    return JAuditManifest(
        manifest_id="J-AUDIT-v1",
        version=1,
        effective_seeds=(8111, 8117),
        items=tuple(
            replace(
                item,
                item_id=f"audit-{index:02d}",
                held_out=True,
            )
            for index, item in enumerate(calibration.items)
        ),
    )


def _card(
    manifest: JCalManifest | JAuditManifest,
) -> JudgeCard:
    return JudgeCard(
        card_id="judge-card-v1",
        version=1,
        provider="provider-a",
        model_id="model-a",
        model_digest=_hash("1"),
        prompt_hash=_hash("2"),
        rubric_hash=_hash("3"),
        parser_hash=_hash("4"),
        sampling_config=(("temperature", 0),),
        calibration_set_hash=(
            manifest.contract_hash if isinstance(manifest, JCalManifest) else _hash("5")
        ),
        audit_set_hash=(
            manifest.contract_hash
            if isinstance(manifest, JAuditManifest)
            else _hash("6")
        ),
        qualified_dimensions=("delivery_actionability",),
        qualification_time="2026-07-30T12:00:00Z",
    )


def _attestation(*, test_only: bool = True) -> EvidenceAttestation:
    return EvidenceAttestation(
        attestation_id="attestation-test-v1",
        issuer="pytest-scripted-provider",
        issued_at="2026-07-30T12:00:00Z",
        test_only=test_only,
    )


class ScriptedProvider:
    provider_id = "provider-a"
    model_id = "model-a"
    test_only = True

    def __init__(
        self,
        manifest: JCalManifest | JAuditManifest,
        *,
        invalid_invocation_id: str | None = None,
        timeout_invocation_id: str | None = None,
        flipped_invocation_id: str | None = None,
        provider_error_invocation_id: str | None = None,
    ) -> None:
        self._verdicts = {item.item_id: item.gold_verdict for item in manifest.items}
        self.invalid_invocation_id = invalid_invocation_id
        self.timeout_invocation_id = timeout_invocation_id
        self.flipped_invocation_id = flipped_invocation_id
        self.provider_error_invocation_id = provider_error_invocation_id
        self.calls: list[str] = []

    def invoke(self, request: JudgeProviderRequest) -> RawJudgeResult:
        invocation = request.invocation
        self.calls.append(invocation.invocation_id)
        if invocation.invocation_id == self.provider_error_invocation_id:
            raise RuntimeError("scripted provider failure")
        if invocation.invocation_id == self.invalid_invocation_id:
            return RawJudgeResult(
                raw_response=b'{"criterion_id":"missing-required-fields"}',
                input_tokens=10,
                output_tokens=4,
                elapsed_ms=5,
            )
        if invocation.invocation_id == self.timeout_invocation_id:
            return RawJudgeResult(
                raw_response=b"{}",
                input_tokens=10,
                output_tokens=1,
                elapsed_ms=invocation.timeout_ms + 1,
            )
        verdict = self._verdicts[invocation.case_id]
        if invocation.invocation_id == self.flipped_invocation_id:
            verdict = (
                EvaluationStatus.FAIL
                if verdict is EvaluationStatus.PASS
                else EvaluationStatus.PASS
            )
        payload = {
            "criterion_id": invocation.criterion_id,
            "verdict": verdict.value,
            "evidence_refs": list(invocation.evidence_refs),
            "rationale": "Deterministic scripted response.",
            "confidence_0_1": 0.9,
            "p_pass_0_1": (
                0.9
                if verdict is EvaluationStatus.PASS
                else 0.1
                if verdict is EvaluationStatus.FAIL
                else 0.5
            ),
            "judge_version": "judge-card-v1",
        }
        return RawJudgeResult(
            raw_response=json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            input_tokens=10,
            output_tokens=20,
            elapsed_ms=5,
        )


def _stage_ledger(
    budget: JudgeExecutionBudget,
    *,
    phase: str = "jcal",
    pre_ledger: StageCostLedger | None = None,
) -> StageCostLedger:
    phase_budgets = []
    for item_phase in PHASES:
        selected = item_phase == phase
        phase_budgets.append(
            PhaseBudget(
                phase=item_phase,
                max_calls=budget.max_calls if selected else 10_000,
                max_input_tokens=(budget.max_input_tokens if selected else 10_000_000),
                max_output_tokens=(
                    budget.max_output_tokens if selected else 10_000_000
                ),
                max_wall_time_ms=(budget.max_elapsed_ms if selected else 10_000_000),
                max_bytes_transferred=10_000_000,
                max_retries=0,
                max_monetary_microunits=0,
                counts_toward_per_arm_equality=item_phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(
                        category=category,
                        max_calls=(
                            budget.max_calls
                            if selected and category.value == "judge"
                            else 10_000
                        ),
                    )
                    for category in CostCategory
                ),
            )
        )
    manifest = StageBudgetManifest(
        manifest_id="meas0.stage-budget.contract-test.v1",
        version=1,
        phase_budgets=tuple(phase_budgets),
    )
    if pre_ledger is not None:
        return replace(pre_ledger, budget_manifest=manifest)
    return StageCostLedger(
        ledger_id="meas0.judge-stage-cost.contract-test.v1",
        version=1,
        price_manifest_hash=_hash("9"),
        budget_manifest=manifest,
        entries=(),
    )


def _runner(
    *,
    provider: ScriptedProvider | None = None,
    budget: JudgeExecutionBudget | None = None,
    timeout_ms: int = 1_000,
    manifest: JCalManifest | JAuditManifest | None = None,
    stage_cost_ledger: StageCostLedger | None = None,
) -> tuple[JudgeCorpusRunner, ScriptedProvider]:
    selected_manifest = manifest or _manifest()
    selected_budget = budget or JudgeExecutionBudget(
        max_calls=96,
        max_input_tokens=96_000,
        max_output_tokens=96_000,
        max_elapsed_ms=96_000,
    )
    selected_provider = provider or ScriptedProvider(selected_manifest)
    return (
        JudgeCorpusRunner(
            judge_card=_card(selected_manifest),
            calibration_manifest=selected_manifest,
            provider=selected_provider,
            attestation=_attestation(),
            budget=selected_budget,
            stage_cost_ledger=stage_cost_ledger
            or _stage_ledger(
                selected_budget,
                phase=(
                    "jcal" if isinstance(selected_manifest, JCalManifest) else "jaudit"
                ),
            ),
            input_tokens_limit=1_000,
            output_tokens_limit=1_000,
            timeout_ms=timeout_ms,
        ),
        selected_provider,
    )


def _probe_manifest_for(
    judge_set_hash: str,
    *,
    test_only: bool = True,
) -> JudgeProbeManifest:
    calls = []
    relations = []
    for index in range(48):
        item_id = f"item-{index:02d}"
        specs = (
            ("order-base", _hash("a")),
            ("order-reversed", _hash("b")),
            ("style-base", _hash("c")),
            ("style-variant", _hash("d")),
            ("repeat-a", _hash("e")),
            ("repeat-b", _hash("e")),
        )
        for offset, (presentation, presentation_hash) in enumerate(specs):
            calls.append(
                JudgeProbeCall(
                    call_id=f"{item_id}.{presentation}",
                    item_id=item_id,
                    presentation=presentation,
                    presentation_hash=presentation_hash,
                    schedule_id=f"schedule-{index:02d}-{offset}",
                )
            )
        for kind, left, right in (
            (ProbeKind.ORDER, "order-base", "order-reversed"),
            (ProbeKind.STYLE, "style-base", "style-variant"),
            (ProbeKind.REPEAT, "repeat-a", "repeat-b"),
        ):
            relations.append(
                JudgeProbeRelation(
                    relation_id=f"{item_id}.{kind.value}",
                    item_id=item_id,
                    kind=kind,
                    left_call_id=f"{item_id}.{left}",
                    right_call_id=f"{item_id}.{right}",
                )
            )
    return JudgeProbeManifest(
        manifest_id="J-CAL-PROBES-v2",
        version=2,
        judge_set_hash=judge_set_hash,
        protected_corpus_hash=_hash("0"),
        calls=tuple(calls),
        relations=tuple(relations),
        test_only=test_only,
    )


def _perfect_probe_corpus() -> ProbeJudgeCorpus:
    manifest = _manifest()
    probe = _probe_manifest_for(manifest.contract_hash)
    card = _card(manifest)
    budget = JudgeExecutionBudget(
        max_calls=288,
        max_input_tokens=288_000,
        max_output_tokens=288_000,
        max_elapsed_ms=288_000,
    )
    pre = _stage_ledger(budget, phase="jcal")
    ledger = pre
    records = []
    gold_by_item = {item.item_id: item.gold_verdict for item in manifest.items}
    for sequence, call in enumerate(probe.calls):
        request_hash = hashlib.sha256(call.call_id.encode()).hexdigest()
        invocation = JudgeInvocation(
            invocation_id=call.call_id,
            judge_card_hash=card.contract_hash,
            case_id=call.item_id,
            criterion_id=f"criterion-{int(call.item_id[-2:]):02d}",
            presentation=call.presentation,
            effective_seed="unsupported",
            request_fingerprint=request_hash,
            evidence_refs=(f"jcal:{call.item_id}:evidence",),
            input_tokens_limit=1_000,
            output_tokens_limit=1_000,
            timeout_ms=1_000,
        )
        verdict = gold_by_item[call.item_id]
        raw = json.dumps(
            {
                "criterion_id": invocation.criterion_id,
                "verdict": verdict.value,
                "evidence_refs": list(invocation.evidence_refs),
                "rationale": "probe verdict",
                "confidence_0_1": 1.0,
                "p_pass_0_1": (1.0 if verdict is EvaluationStatus.PASS else 0.0),
                "judge_version": card.card_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        raw_hash = hashlib.sha256(raw).hexdigest()
        response = JudgeResponse(
            invocation_id=call.call_id,
            criterion_id=invocation.criterion_id,
            verdict=verdict,
            evidence_refs=invocation.evidence_refs,
            rationale="probe verdict",
            confidence_0_1=1.0,
            p_pass_0_1=(1.0 if verdict is EvaluationStatus.PASS else 0.0),
            judge_version=card.card_id,
            raw_response_hash=raw_hash,
        )
        previous = ledger.entries[-1].contract_hash if ledger.entries else None
        entry = StageCostEntry(
            entry_id=f"jcal.probe.{sequence:03d}",
            sequence=sequence,
            phase="jcal",
            category=CostCategory.JUDGE,
            outcome=CostOutcome.SUCCEEDED,
            failure_code=None,
            request_hash=request_hash,
            call_hash=hashlib.sha256(f"call-{sequence}".encode()).hexdigest(),
            raw_receipt_hash=hashlib.sha256(f"receipt-{sequence}".encode()).hexdigest(),
            calls=1,
            input_tokens=1,
            output_tokens=1,
            wall_time_ms=1,
            bytes_transferred=2,
            retry_count=0,
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=False,
            arm_id=None,
            provider_id=card.provider,
            model_id=card.model_id,
            cost_class="judge_probe.test",
            retry_of_entry_hash=None,
            previous_entry_hash=previous,
        )
        ledger = ledger.append(entry)
        records.append(
            JudgeCallRecord(
                invocation=invocation,
                presentation_hash=call.presentation_hash,
                outcome=JudgeCallOutcome.OK,
                response=response,
                raw_response=raw,
                raw_response_hash=raw_hash,
                input_tokens=1,
                output_tokens=1,
                elapsed_ms=1,
                error=None,
                attempted=True,
                stage_cost_entry_hash=entry.contract_hash,
            )
        )
    return ProbeJudgeCorpus(
        judge_card=card,
        calibration_manifest=manifest,
        probe_manifest=probe,
        attestation=_attestation(),
        records=tuple(records),
        stage_cost_pre_ledger=pre,
        stage_cost_ledger=ledger,
    )


def _exact_probe_bundle() -> tuple[
    ProbeJudgeCorpus,
    TransportReceiptBatch,
    ExactInvocationManifest,
]:
    initial = _perfect_probe_corpus()
    plan = TransportBatchPlan(
        schema_version=1,
        plan_id="jcal-probe-plan",
        batch_id="jcal-probe-batch",
        phase="jcal",
        comparison_block_id="jcal-probes",
        comparison_lock_hash=_hash("1"),
        design_hash=_hash("2"),
        execution_authorization_hash=_hash("3"),
        provider_id="provider-a",
        endpoint_origin="https://provider.invalid",
        requested_model_id="model-a",
        expected_observed_model_id="model-a",
        entries=tuple(
            TransportBatchEntry(
                sequence_number=index,
                invocation_id=record.invocation.invocation_id,
                criterion_id=record.invocation.criterion_id,
                presentation_hash=record.presentation_hash,
                data_attestation_hash=_hash("4"),
                request_fingerprint=record.invocation.request_fingerprint,
                request_bytes_hash=hashlib.sha256(
                    f"request-{index}".encode()
                ).hexdigest(),
            )
            for index, record in enumerate(initial.records)
        ),
    )
    receipts = []
    previous_hash = None
    for index, (entry, record) in enumerate(
        zip(plan.entries, initial.records, strict=True)
    ):
        payload = TransportReceiptPayload(
            schema_version=1,
            receipt_id=f"probe-receipt-{index}",
            claim_scope=(TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION),
            provider_id="provider-a",
            endpoint_origin="https://provider.invalid",
            requested_model_id="model-a",
            observed_model_id="model-a",
            purpose="transport_receipt",
            phase="jcal",
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
            outcome=TransportOutcome.SUCCESS,
            failure_code=None,
            response_hash=record.raw_response_hash,
            response_size=len(record.raw_response),
            http_status=200,
            started_at="2026-07-30T12:00:00Z",
            completed_at="2026-07-30T12:00:01Z",
            nonce=f"probe-{index}",
            batch_id=plan.batch_id,
            batch_manifest_hash=plan.contract_hash,
            sequence_number=index,
            previous_receipt_hash=previous_hash,
            tls_peer_hostname="provider.invalid",
            tls_sni="provider.invalid",
            tls_certificate_sha256=_hash("5"),
            tls_spki_sha256=_hash("6"),
            tls_chain_sha256=_hash("7"),
            tls_verification_result=TLSVerificationResult.VERIFIED,
            tls_trust_store_snapshot_hash=_hash("8"),
            tls_verification_policy_hash=_hash("9"),
        )
        envelope = SignatureEnvelope(
            schema_version=1,
            envelope_id=f"probe-envelope-{index}",
            trust_domain=TrustDomain.TRANSPORT,
            root_id="test-root",
            root_manifest_hash=_hash("a"),
            key_fingerprint=_hash("b"),
            algorithm_id="test-only",
            role_id="transport",
            purpose=payload.purpose,
            phase=payload.phase,
            payload_hash=payload.contract_hash,
            sequence_number=index,
            nonce=payload.nonce,
            observed_signing_time="2026-07-30T12:00:01Z",
            test_only=True,
            signature_hex=_hash("c"),
        )
        receipt = SignedTransportReceipt(payload=payload, envelope=envelope)
        receipts.append(receipt)
        previous_hash = receipt.contract_hash
    batch = TransportReceiptBatch(
        schema_version=1,
        plan=plan,
        receipts=tuple(receipts),
    )
    ledger = initial.stage_cost_pre_ledger
    rebound_records = []
    for record, old_entry, receipt in zip(
        initial.records,
        initial.stage_cost_ledger.entries,
        receipts,
        strict=True,
    ):
        previous = ledger.entries[-1].contract_hash if ledger.entries else None
        entry = replace(
            old_entry,
            raw_receipt_hash=receipt.contract_hash,
            previous_entry_hash=previous,
        )
        ledger = ledger.append(entry)
        rebound_records.append(
            replace(record, stage_cost_entry_hash=entry.contract_hash)
        )
    corpus = replace(
        initial,
        records=tuple(rebound_records),
        stage_cost_ledger=ledger,
    )
    exact = ExactInvocationManifest.derive(
        manifest_id="jcal-probe-exact",
        probe_manifest=corpus.probe_manifest,
        corpus=corpus,
        transport_batch=batch,
        stage_cost_ledger=ledger,
    )
    return corpus, batch, exact


def test_probe_qualification_uses_288_calls_and_independent_relations() -> None:
    evidence = derive_probe_qualification(
        _perfect_probe_corpus(),
        qualification_id="probe-derived-v1",
        evaluated_at="2026-07-30T12:03:00Z",
    )
    assert evidence.qualification.qualified
    assert evidence.qualification.schema_valid.denominator == 288
    assert evidence.qualification.evidence_reference_validity.denominator == 288
    assert evidence.qualification.false_accept.denominator == 96
    assert evidence.qualification.false_reject.denominator == 96
    assert evidence.qualification.order_flip.denominator == 48
    assert evidence.qualification.style_flip.denominator == 48
    assert evidence.qualification.repeat_disagreement.denominator == 48
    assert evidence.qualification.order_flip.value == 0
    assert evidence.qualification.style_flip.value == 0
    assert evidence.qualification.repeat_disagreement.value == 0
    assert derived_probe_judge_qualification_from_dict(evidence.to_dict()) == evidence
    with pytest.raises(FormalEvidenceError, match="test-only"):
        require_production_probe_judge_evidence(evidence)


def test_exact_288_bundle_passes_membership_and_rejects_reorder() -> None:
    corpus, batch, exact = _exact_probe_bundle()
    exact.verify_membership(
        probe_manifest=corpus.probe_manifest,
        corpus=corpus,
        transport_batch=batch,
        stage_cost_ledger=corpus.stage_cost_ledger,
    )
    reordered = replace(
        batch,
        receipts=(batch.receipts[1], batch.receipts[0], *batch.receipts[2:]),
    )
    with pytest.raises(FormalEvidenceError, match="reordered|misbound|ancestry"):
        exact.verify_membership(
            probe_manifest=corpus.probe_manifest,
            corpus=corpus,
            transport_batch=reordered,
            stage_cost_ledger=corpus.stage_cost_ledger,
        )


def test_readiness_classifies_complete_test_only_288_evidence_as_trust_blocked() -> (
    None
):
    corpus, batch, exact = _exact_probe_bundle()
    evidence = derive_probe_qualification(
        corpus,
        qualification_id="readiness-probe-288",
        evaluated_at="2026-07-30T12:05:00Z",
    )
    report = FormalReadinessValidator().validate(
        FormalReadinessInputs(
            judge_calibration_manifest=corpus.calibration_manifest,
            judge_card=corpus.judge_card,
            judge_evidence=evidence,
            transport_receipt_batch=batch,
            judge_probe_manifest=corpus.probe_manifest,
            judge_invocation_manifest=exact,
            stage_cost_ledger=corpus.stage_cost_ledger,
        )
    )
    assert (
        ReadinessBlockerCode.JUDGE_EVIDENCE_PRODUCTION_TRUST_UNAVAILABLE
        in report.blockers
    )
    assert (
        ReadinessBlockerCode.JUDGE_PROBE_PRODUCTION_TRUST_UNAVAILABLE in report.blockers
    )
    assert ReadinessBlockerCode.JUDGE_NOT_QUALIFIED not in report.blockers
    assert ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_INVALID not in report.blockers
    assert (
        ReadinessBlockerCode.JUDGE_INVOCATION_MEMBERSHIP_INVALID not in report.blockers
    )


def test_probe_corpus_rejects_missing_duplicate_reorder_and_misbind() -> None:
    corpus = _perfect_probe_corpus()
    attacks = (
        corpus.records[:-1],
        (*corpus.records[:-1], corpus.records[0]),
        (corpus.records[1], corpus.records[0], *corpus.records[2:]),
        (
            replace(
                corpus.records[0],
                invocation=replace(
                    corpus.records[0].invocation,
                    criterion_id="wrong-criterion",
                ),
                response=replace(
                    corpus.records[0].response,
                    criterion_id="wrong-criterion",
                ),
            ),
            *corpus.records[1:],
        ),
    )
    for records in attacks:
        with pytest.raises(
            FormalEvidenceError,
            match="288|order|binding|bound|unique",
        ):
            replace(corpus, records=records)


def test_probe_instability_rates_do_not_reuse_other_relation_pairs() -> None:
    corpus = _perfect_probe_corpus()
    target = corpus.records[3]  # item-00.style-variant
    assert target.response is not None
    changed_verdict = EvaluationStatus.FAIL
    payload = json.loads(target.raw_response)
    payload["verdict"] = changed_verdict.value
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    changed = replace(
        target,
        response=replace(
            target.response,
            verdict=changed_verdict,
            raw_response_hash=hashlib.sha256(raw).hexdigest(),
        ),
        raw_response=raw,
        raw_response_hash=hashlib.sha256(raw).hexdigest(),
    )
    altered = replace(
        corpus,
        records=(*corpus.records[:3], changed, *corpus.records[4:]),
    )
    qualification = derive_probe_qualification(
        altered,
        qualification_id="probe-independent-relations",
        evaluated_at="2026-07-30T12:04:00Z",
    ).qualification
    assert qualification.order_flip.value == 0
    assert qualification.style_flip.value == pytest.approx(1 / 48)
    assert qualification.repeat_disagreement.value == 0


def test_runner_builds_deterministic_complete_bound_corpus() -> None:
    first_runner, _ = _runner()
    second_runner, _ = _runner()

    first = first_runner.run()
    second = second_runner.run()

    assert len(first.records) == 96
    assert first.contract_hash == second.contract_hash
    assert first.calibration_manifest_hash == _manifest().contract_hash
    assert {record.outcome for record in first.records} == {JudgeCallOutcome.OK}
    assert first.records[0].invocation.presentation == "normal"
    assert first.records[1].invocation.presentation == "reversed"
    assert first.records[0].response is not None
    assert first.records[0].response.invocation_id == (
        first.records[0].invocation.invocation_id
    )
    assert all(record.attempted for record in first.records)
    assert len(first.stage_cost_ledger.entries) == 96
    assert tuple(record.stage_cost_entry_hash for record in first.records) == tuple(
        entry.contract_hash for entry in first.stage_cost_ledger.entries
    )
    assert first.ledger_pre_head_hash == first.stage_cost_pre_ledger.contract_hash
    assert first.final_ledger_hash == first.stage_cost_ledger.contract_hash
    assert first.stage_cost_ledger.production_ready is False
    assert first.budget.production_ready is False
    assert first.production_ready is False

    forged_record = replace(
        first.records[0],
        stage_cost_entry_hash=first.records[1].stage_cost_entry_hash,
    )
    with pytest.raises(FormalEvidenceError, match="one-to-one"):
        replace(
            first,
            records=(forged_record, *first.records[1:]),
        )


def test_fusion_is_fail_closed_for_flip_schema_timeout_and_budget() -> None:
    manifest = _manifest()
    provider = ScriptedProvider(
        manifest,
        invalid_invocation_id="J-CAL-v1.item-01.normal",
        timeout_invocation_id="J-CAL-v1.item-02.reversed",
        flipped_invocation_id="J-CAL-v1.item-00.reversed",
    )
    runner, _ = _runner(
        provider=provider,
        budget=JudgeExecutionBudget(
            max_calls=95,
            max_input_tokens=96_000,
            max_output_tokens=96_000,
            max_elapsed_ms=96_000,
        ),
        timeout_ms=100,
    )

    corpus = runner.run()
    outcomes = {
        record.invocation.invocation_id: record.outcome for record in corpus.records
    }
    fused = {item.item_id: item for item in fuse_corpus_presentations(corpus)}

    assert outcomes["J-CAL-v1.item-01.normal"] is JudgeCallOutcome.SCHEMA_INVALID
    assert outcomes["J-CAL-v1.item-02.reversed"] is JudgeCallOutcome.TIMEOUT
    assert outcomes["J-CAL-v1.item-47.reversed"] is JudgeCallOutcome.BUDGET_EXHAUSTED
    assert len(provider.calls) == 95
    attempted = tuple(record for record in corpus.records if record.attempted)
    unattempted = tuple(record for record in corpus.records if not record.attempted)
    assert len(attempted) == 95
    assert len(unattempted) == 1
    assert unattempted[0].stage_cost_entry_hash is None
    assert len(corpus.stage_cost_ledger.entries) == 95
    assert all(record.stage_cost_entry_hash is not None for record in attempted)
    with pytest.raises(FormalEvidenceError, match="one-to-one"):
        replace(
            corpus,
            records=(
                *corpus.records[:-1],
                replace(
                    unattempted[0],
                    attempted=True,
                    stage_cost_entry_hash=attempted[0].stage_cost_entry_hash,
                ),
            ),
        )
    assert fused["item-00"].status is EvaluationStatus.DISPUTED
    assert fused["item-01"].status is EvaluationStatus.UNKNOWN
    assert fused["item-02"].status is EvaluationStatus.UNKNOWN
    assert fused["item-47"].status is EvaluationStatus.UNKNOWN


def test_qualification_is_derived_from_corpus_with_wilson_intervals() -> None:
    runner, _ = _runner()
    corpus = runner.run()

    evidence = derive_jcal_qualification(
        corpus,
        qualification_id="jcal-derived-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )

    assert isinstance(evidence, DerivedJudgeQualification)
    assert evidence.source_corpus_hash == corpus.contract_hash
    assert evidence.qualification.schema_valid.value == 1.0
    assert evidence.qualification.schema_valid.denominator == 96
    assert evidence.qualification.schema_valid.lower == pytest.approx(0.96152, abs=1e-5)
    assert evidence.qualification.false_accept.value == 0.0
    assert evidence.qualification.false_accept.denominator == 32
    assert evidence.qualification.false_accept.upper == pytest.approx(0.10718, abs=1e-5)
    assert evidence.qualification.false_reject.value == 0.0
    assert evidence.qualification.unknown_rate.value == pytest.approx(1 / 3)
    assert evidence.qualification.order_flip.value == 0.0
    # The legacy two-presentation runner only registers an order relation.
    # Missing independent style/repeat probes fail closed instead of reusing
    # the same pair for all three metrics.
    assert evidence.qualification.style_flip.value == 1.0
    assert evidence.qualification.repeat_disagreement.value == 1.0
    assert evidence.qualification.evidence_reference_validity.value == 1.0
    assert evidence.qualification.qualified is False
    assert evidence.quarantine is not None
    assert "style_flip" in evidence.quarantine.reason


def test_invalid_corpus_derives_unqualified_result_and_quarantine() -> None:
    manifest = _manifest()
    provider = ScriptedProvider(
        manifest,
        invalid_invocation_id="J-CAL-v1.item-01.normal",
    )
    runner, _ = _runner(provider=provider)

    evidence = derive_jcal_qualification(
        runner.run(),
        qualification_id="jcal-derived-invalid-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )

    assert evidence.qualification.schema_valid.value == pytest.approx(95 / 96)
    assert evidence.qualification.qualified is False
    assert evidence.quarantine is not None
    assert evidence.quarantine.qualification_hash == (
        evidence.qualification.contract_hash
    )
    assert "schema_valid" in evidence.quarantine.reason


def test_derived_evidence_rejects_caller_supplied_rate_changes() -> None:
    runner, _ = _runner()
    evidence = derive_jcal_qualification(
        runner.run(),
        qualification_id="jcal-derived-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )
    submitted_rate = RateEstimate(
        value=0.5,
        lower=0.4,
        upper=0.6,
        denominator=96,
    )

    with pytest.raises(FormalEvidenceError, match="derived"):
        replace(
            evidence,
            qualification=replace(
                evidence.qualification,
                schema_valid=submitted_rate,
            ),
        )


def test_jaudit_qualification_is_independent_and_cannot_reuse_jcal_corpus() -> None:
    audit_runner, _ = _runner(manifest=_audit_manifest())
    audit = derive_jaudit_qualification(
        audit_runner.run(),
        qualification_id="jaudit-derived-v1",
        evaluated_at="2026-07-30T12:02:00Z",
    )
    assert audit.qualification.set_kind == "J-AUDIT-v1"
    assert audit.qualification.set_hash == _audit_manifest().contract_hash

    jcal_runner, _ = _runner()
    with pytest.raises(FormalEvidenceError, match="J-AUDIT"):
        derive_jaudit_qualification(
            jcal_runner.run(),
            qualification_id="reused-jcal",
            evaluated_at="2026-07-30T12:02:00Z",
        )


def test_derived_evidence_round_trips_sealed_raw_corpus() -> None:
    runner, _ = _runner()
    evidence = derive_jcal_qualification(
        runner.run(),
        qualification_id="jcal-derived-roundtrip-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )

    restored = derived_judge_qualification_from_dict(evidence.to_dict())

    assert restored == evidence
    assert restored.source_corpus.records[0].raw_response
    tampered = evidence.to_dict()
    tampered["source_corpus"]["records"][0]["raw_response_base64"] = "e30="
    with pytest.raises(FormalEvidenceError, match="hash|raw|derived"):
        derived_judge_qualification_from_dict(tampered)


def test_test_only_attestation_is_explicit_and_rejected_for_production() -> None:
    runner, _ = _runner()
    evidence = derive_jcal_qualification(
        runner.run(),
        qualification_id="jcal-derived-test-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )

    assert evidence.attestation.test_only is True
    with pytest.raises(FormalEvidenceError, match="test-only"):
        require_production_judge_evidence(evidence)


def test_non_test_label_cannot_bypass_missing_independent_probes() -> None:
    runner, _ = _runner()
    evidence = derive_jcal_qualification(
        runner.run(),
        qualification_id="jcal-derived-untrusted-production-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )
    relabeled = replace(
        evidence,
        source_corpus=replace(
            evidence.source_corpus,
            attestation=replace(
                evidence.attestation,
                test_only=False,
            ),
        ),
    )

    with pytest.raises(FormalEvidenceError, match="quarantined or unqualified"):
        require_production_judge_evidence(relabeled)


def test_fake_provider_cannot_be_mislabeled_as_external_evidence() -> None:
    manifest = _manifest()
    provider = ScriptedProvider(manifest)

    with pytest.raises(FormalEvidenceError, match="attestation"):
        JudgeCorpusRunner(
            judge_card=_card(manifest),
            calibration_manifest=manifest,
            provider=provider,
            attestation=replace(_attestation(), test_only=False),
            budget=JudgeExecutionBudget(
                max_calls=96,
                max_input_tokens=96_000,
                max_output_tokens=96_000,
                max_elapsed_ms=96_000,
            ),
            stage_cost_ledger=_stage_ledger(
                JudgeExecutionBudget(
                    max_calls=96,
                    max_input_tokens=96_000,
                    max_output_tokens=96_000,
                    max_elapsed_ms=96_000,
                )
            ),
            input_tokens_limit=1_000,
            output_tokens_limit=1_000,
            timeout_ms=1_000,
        )


def test_schema_timeout_and_provider_failure_attempts_are_retained_in_stage_cost() -> (
    None
):
    manifest = _manifest()
    provider = ScriptedProvider(
        manifest,
        invalid_invocation_id="J-CAL-v1.item-00.normal",
        timeout_invocation_id="J-CAL-v1.item-00.reversed",
        provider_error_invocation_id="J-CAL-v1.item-01.normal",
    )
    runner, _ = _runner(provider=provider, timeout_ms=100)

    corpus = runner.run()
    records = {record.invocation.invocation_id: record for record in corpus.records}
    entries = {entry.contract_hash: entry for entry in corpus.stage_cost_ledger.entries}

    for invocation_id in (
        "J-CAL-v1.item-00.normal",
        "J-CAL-v1.item-00.reversed",
        "J-CAL-v1.item-01.normal",
    ):
        record = records[invocation_id]
        assert record.attempted is True
        assert record.stage_cost_entry_hash in entries
        assert entries[record.stage_cost_entry_hash].outcome is CostOutcome.FAILED


def test_legacy_budget_must_be_an_exact_contract_only_stage_projection() -> None:
    budget = JudgeExecutionBudget(
        max_calls=96,
        max_input_tokens=96_000,
        max_output_tokens=96_000,
        max_elapsed_ms=96_000,
    )
    ledger = _stage_ledger(budget)

    assert budget.is_stage_budget_projection(ledger.budget_manifest, "jcal")
    with pytest.raises(FormalEvidenceError, match="projection"):
        JudgeCorpusRunner(
            judge_card=_card(_manifest()),
            calibration_manifest=_manifest(),
            provider=ScriptedProvider(_manifest()),
            attestation=_attestation(),
            budget=budget,
            stage_cost_ledger=replace(
                ledger,
                budget_manifest=replace(
                    ledger.budget_manifest,
                    phase_budgets=tuple(
                        replace(item, max_input_tokens=95_999)
                        if item.phase == "jcal"
                        else item
                        for item in ledger.budget_manifest.phase_budgets
                    ),
                ),
            ),
            input_tokens_limit=1_000,
            output_tokens_limit=1_000,
            timeout_ms=1_000,
        )


def test_phase_generic_audit_corpus_uses_jaudit_entries_and_stays_test_only() -> None:
    manifest = _audit_manifest()
    runner, _ = _runner(manifest=manifest)

    corpus = runner.run()

    assert corpus.phase == "jaudit"
    assert {entry.phase for entry in corpus.stage_cost_ledger.entries} == {"jaudit"}
    assert corpus.stage_cost_ledger.production_ready is False
