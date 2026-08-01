from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.measurement import EvaluationStatus
from biofield.meas0_detection_oracle import build_test_only_candidate_oracle
from biofield.meas0_formal import (
    EvidenceAttestation,
    JudgeCorpusRunner,
    JudgeExecutionBudget,
    JudgeProviderRequest,
    RawJudgeResult,
    derive_jcal_qualification,
)
from biofield.meas0_human import (
    BlindReviewRecord as DerivedBlindReviewRecord,
    HumanAttestationKind,
    HumanReviewEvidence,
    ReviewScopeItem,
    ReviewVerdict,
)
from biofield.meas0_preflight import (
    REQUIRED_PREFLIGHT_COMMAND_IDS,
    AttestationKind as PreflightAttestationKind,
    CommandSpec,
    ExecutorResult,
    MountDeclaration,
    capture_preflight_evidence,
)
from biofield.meas0_readiness import (
    ARM_ORDER_SEED,
    REQUIRED_FORMAL_LOCK_BINDINGS,
    ACLManifest,
    ACLRule,
    AdjudicationRecord,
    ApprovalManifest,
    BlindReviewerRecord,
    BudgetPolicy,
    ContractError,
    FormalLockBindings,
    FormalCaseIdentity,
    FormalCaseScopeManifest,
    FormalArtifactLayout,
    FormalReadinessInputs,
    FormalReadinessBundle,
    FormalReadinessState,
    FormalReadinessValidator,
    GoldRecord,
    GoldArtifactManifest,
    GoldMountManifest,
    GoldRunValidity,
    GoldScopeItem,
    GoldScopeManifest,
    IsolationPolicy,
    JAuditManifest,
    JCalManifest,
    JudgeCard,
    JudgeInvocation,
    JudgeQualification,
    JudgeQuarantine,
    JudgeResponse,
    JudgeSetProvenanceManifest,
    JudgeSetItem,
    PreflightReport,
    PriceManifest,
    ProviderPrice,
    RateEstimate,
    ReadinessBlockerCode,
    TaskBudgetLimit,
    arm_order_manifest,
    compute_gold_agreement,
    formal_gold_binding_hash,
    fuse_judge_presentations,
    require_formal_readiness,
)


def _hash(character: str = "a") -> str:
    return character * 64


def test_jcal_jaudit_provenance_requires_three_way_disjointness() -> None:
    with pytest.raises(ContractError, match="disjoint"):
        JudgeSetProvenanceManifest(
            manifest_id="judge-set-provenance",
            version=1,
            jcal_set_hash=_hash("1"),
            jaudit_set_hash=_hash("2"),
            jcal_protected_corpus_hash=_hash("3"),
            jaudit_protected_corpus_hash=_hash("4"),
            jcal_source_ids=("source-a",),
            jaudit_source_ids=("source-a",),
            jcal_template_ids=("template-a",),
            jaudit_template_ids=("template-b",),
            jcal_entity_ids=("entity-a",),
            jaudit_entity_ids=("entity-b",),
        )


def _judge_items(*, held_out: bool) -> tuple[JudgeSetItem, ...]:
    labels = (
        [EvaluationStatus.PASS] * 16
        + [EvaluationStatus.FAIL] * 16
        + [EvaluationStatus.UNKNOWN] * 16
    )
    return tuple(
        JudgeSetItem(
            item_id=f"item-{index:02d}",
            criterion_id=f"criterion-{index:02d}",
            gold_verdict=label,
            normal_presentation_hash=_hash("a"),
            reversed_presentation_hash=_hash("b"),
            held_out=held_out,
        )
        for index, label in enumerate(labels)
    )


def _judge_card() -> JudgeCard:
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
        calibration_set_hash=_hash("5"),
        audit_set_hash=_hash("6"),
        qualified_dimensions=("delivery_actionability",),
        qualification_time="2026-07-30T12:00:00Z",
    )


class _TestOnlyJudgeProvider:
    provider_id = "provider-a"
    model_id = "model-a"
    test_only = True

    def __init__(self, manifest: JCalManifest) -> None:
        self._verdicts = {item.item_id: item.gold_verdict for item in manifest.items}

    def invoke(self, request: JudgeProviderRequest) -> RawJudgeResult:
        invocation = request.invocation
        payload = {
            "criterion_id": invocation.criterion_id,
            "verdict": self._verdicts[invocation.case_id].value,
            "evidence_refs": list(invocation.evidence_refs),
            "rationale": "Deterministic test-only readiness response.",
            "confidence_0_1": 0.9,
            "p_pass_0_1": (
                0.9
                if self._verdicts[invocation.case_id] is EvaluationStatus.PASS
                else 0.1
                if self._verdicts[invocation.case_id] is EvaluationStatus.FAIL
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


def _test_only_judge_evidence(
    card: JudgeCard,
    manifest: JCalManifest,
):
    corpus = JudgeCorpusRunner(
        judge_card=card,
        calibration_manifest=manifest,
        provider=_TestOnlyJudgeProvider(manifest),
        attestation=EvidenceAttestation(
            attestation_id="pytest-attestation-v1",
            issuer="pytest-scripted-provider",
            issued_at="2026-07-30T12:00:00Z",
            test_only=True,
        ),
        budget=JudgeExecutionBudget(
            max_calls=96,
            max_input_tokens=96_000,
            max_output_tokens=96_000,
            max_elapsed_ms=96_000,
        ),
        input_tokens_limit=1_000,
        output_tokens_limit=1_000,
        timeout_ms=1_000,
    ).run()
    return derive_jcal_qualification(
        corpus,
        qualification_id="pytest-derived-jcal-v1",
        evaluated_at="2026-07-30T12:01:00Z",
    )


def _qualified(card: JudgeCard) -> JudgeQualification:
    return JudgeQualification(
        qualification_id="qualification-v1",
        judge_card_hash=card.contract_hash,
        set_kind="J-CAL-v1",
        set_hash=card.calibration_set_hash or "",
        schema_valid=RateEstimate(1.0, 0.92, 1.0, 96),
        false_accept=RateEstimate(0.05, 0.01, 0.12, 32),
        false_reject=RateEstimate(0.10, 0.03, 0.20, 32),
        unknown_rate=RateEstimate(0.08, 0.03, 0.15, 96),
        order_flip=RateEstimate(0.05, 0.01, 0.12, 48),
        style_flip=RateEstimate(0.05, 0.01, 0.12, 48),
        repeat_disagreement=RateEstimate(0.02, 0.0, 0.08, 48),
        evidence_reference_validity=RateEstimate(0.97, 0.90, 1.0, 96),
        evaluated_at="2026-07-30T12:00:00Z",
    )


def _gold_records() -> tuple[
    GoldRecord,
    tuple[BlindReviewerRecord, BlindReviewerRecord],
]:
    first = BlindReviewerRecord(
        review_id="review-1",
        reviewer_role_id="reviewer-a",
        case_id="pilot.cold_chain_readiness.F01.seed1729",
        requirement_id="semantic-01",
        verdict=EvaluationStatus.PASS,
        evidence_refs=("response:final",),
        rationale="The response gives an actionable next step.",
        blinded_to_arm=True,
        blinded_to_model=True,
    )
    second = replace(
        first,
        review_id="review-2",
        reviewer_role_id="reviewer-b",
    )
    gold = GoldRecord(
        gold_id="gold-01",
        case_id="pilot.cold_chain_readiness.F01.seed1729",
        requirement_id="semantic-01",
        verdict=EvaluationStatus.PASS,
        evidence_refs=("response:final",),
        rationale="Both blinded reviewers found the next step actionable.",
        gold_source_ref="semantic-review-v1",
        author_role_id="gold-author",
        semantic=True,
        gold_run_validity=GoldRunValidity.VALID,
        gold_status=EvaluationStatus.PASS,
        accept_allowed=True,
        safety_violation=False,
        reviewer_record_hashes=(first.contract_hash, second.contract_hash),
        adjudication_record_hash=None,
    )
    return gold, (first, second)


def _budget() -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="meas0-budget-v1",
        version=1,
        task_limits=(
            TaskBudgetLimit(
                task_id="cold_chain_readiness",
                deterministic_checks=24,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=8192,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=60_000,
                judge_wall_time_ms=120_000,
            ),
            TaskBudgetLimit(
                task_id="channel_order_ingest",
                deterministic_checks=32,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=16_384,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=180_000,
                judge_wall_time_ms=120_000,
            ),
        ),
        pilot_judge_calls=240,
        pilot_human_escalations=8,
        exhaustion_status=EvaluationStatus.UNKNOWN,
        retain_exhausted_cases=True,
    )


def _price() -> PriceManifest:
    return PriceManifest(
        manifest_id="price-v1",
        version=1,
        currency="USD",
        effective_at="2026-07-30T00:00:00Z",
        fx_as_of="2026-07-30T00:00:00Z",
        direct_cap_microunits=100_000_000,
        provider_prices=(
            ProviderPrice(
                provider="provider-a",
                model_id="model-a",
                input_per_million_microunits=1_000_000,
                output_per_million_microunits=2_000_000,
                metered_tool_microunits=0,
            ),
        ),
    )


def _isolation() -> tuple[IsolationPolicy, ACLManifest, PreflightReport]:
    policy = IsolationPolicy(
        policy_id="isolation-v1",
        version=1,
        subject_read_roots=("workspace",),
        subject_write_roots=("workspace/src", "workspace/tests/agent"),
        evaluator_read_roots=("workspace", "protected"),
        evaluator_write_roots=("run/evaluator",),
        judge_read_roots=("judge/input",),
        gold_mounted_to_evaluator=False,
        network_policy="deny_subject_allow_frozen_judge",
        require_read_only_protected=True,
        require_clean_import_path=True,
        require_wheel_hash=True,
        platform_neutral=True,
    )
    acl = ACLManifest(
        manifest_id="acl-v1",
        version=1,
        policy_hash=policy.contract_hash,
        rules=(
            ACLRule(
                principal="subject",
                resolved_path="/sandbox/workspace/src",
                permissions=("read", "write"),
            ),
            ACLRule(
                principal="evaluator",
                resolved_path="/sandbox/protected",
                permissions=("read",),
            ),
        ),
    )
    preflight = PreflightReport(
        report_id="preflight-v1",
        policy_hash=policy.contract_hash,
        acl_manifest_hash=acl.contract_hash,
        observed_platform="test-platform",
        process_isolation_available=True,
        protected_read_only=True,
        hidden_gold_unmounted=True,
        resolved_path_allowlist_enforced=True,
        symlink_hardlink_checks_passed=True,
        clean_import_path=True,
        wheel_hash_verified=True,
        network_policy_enforced=True,
        checked_at="2026-07-30T12:00:00Z",
    )
    return policy, acl, preflight


class _FakePreflightExecutor:
    def run(self, argv: tuple[str, ...]) -> ExecutorResult:
        return ExecutorResult(
            exit_code=0,
            stdout=f"{argv[0]}:ok\n".encode(),
            stderr=b"",
        )


def _derived_preflight():
    return capture_preflight_evidence(
        attestation_kind=PreflightAttestationKind.TEST_ONLY,
        executor_id="fake-preflight-contract-executor",
        commands=tuple(
            CommandSpec(command_id=item, argv=(item, "--probe"))
            for item in REQUIRED_PREFLIGHT_COMMAND_IDS
        ),
        executor=_FakePreflightExecutor(),
        environment={"python": "3.13", "platform": "contract-test"},
        dependencies={"biofield": "contract-test"},
        mounts=(
            MountDeclaration(
                mount_id="protected",
                principal="evaluator",
                source_path="/sealed/protected",
                target_path="/sandbox/protected",
                mounted=True,
                read_only=True,
                contains_hidden_gold=False,
            ),
            MountDeclaration(
                mount_id="hidden-gold",
                principal="evaluator",
                source_path="/sealed/gold",
                target_path="/sandbox/gold",
                mounted=False,
                read_only=True,
                contains_hidden_gold=True,
            ),
        ),
        network_policy="deny_subject_allow_frozen_judge",
        process_policy="separate_processes_required",
        acl_audit_log=b"contract-test ACL audit log\n",
    )


def _case_scope() -> FormalCaseScopeManifest:
    cases = tuple(
        FormalCaseIdentity(
            case_id=f"pilot.{task_id}.{fault_id}.seed1729",
            task_id=task_id,
            task_version=1,
            fault_id=fault_id,
            native_adapter=True,
            case_descriptor_hash=_hash(f"{index % 16:x}"),
        )
        for index, (task_id, fault_id) in enumerate(
            (task_id, f"F{fault_index:02d}")
            for task_id in (
                "cold_chain_readiness",
                "channel_order_ingest",
            )
            for fault_index in range(1, 19)
        )
    )
    return FormalCaseScopeManifest(
        manifest_id="pilot-case-scope-v1",
        version=1,
        mutation_seed=1729,
        cases=cases,
    )


def _complete_gold(
    case_scope: FormalCaseScopeManifest,
) -> tuple[
    GoldScopeManifest,
    tuple[GoldRecord, ...],
    tuple[BlindReviewerRecord, ...],
]:
    semantic_gold, semantic_reviews = _gold_records()
    records: list[GoldRecord] = [semantic_gold]
    reviews: list[BlindReviewerRecord] = list(semantic_reviews)
    items: list[GoldScopeItem] = []
    for index, case in enumerate(case_scope.cases):
        requirement_id = "semantic-01" if index == 0 else "deterministic-01"
        items.append(
            GoldScopeItem(
                case_id=case.case_id,
                requirement_ids=(requirement_id,),
            )
        )
        if index == 0:
            continue
        review = BlindReviewerRecord(
            review_id=f"deterministic-review-{index:02d}",
            reviewer_role_id="deterministic-reviewer",
            case_id=case.case_id,
            requirement_id=requirement_id,
            verdict=EvaluationStatus.FAIL,
            evidence_refs=("state:case",),
            rationale="The deterministic oracle reports a frozen failure.",
            blinded_to_arm=True,
            blinded_to_model=True,
        )
        reviews.append(review)
        records.append(
            GoldRecord(
                gold_id=f"gold-{index:02d}",
                case_id=case.case_id,
                requirement_id=requirement_id,
                verdict=EvaluationStatus.FAIL,
                evidence_refs=("state:case",),
                rationale="The protected deterministic oracle fails.",
                gold_source_ref="deterministic-oracle-v1",
                author_role_id="gold-author",
                semantic=False,
                gold_run_validity=GoldRunValidity.VALID,
                gold_status=EvaluationStatus.FAIL,
                accept_allowed=False,
                safety_violation=False,
                reviewer_record_hashes=(review.contract_hash,),
                adjudication_record_hash=None,
            )
        )
    scope = GoldScopeManifest(
        manifest_id="pilot-gold-scope-v1",
        version=1,
        case_scope_hash=case_scope.contract_hash,
        items=tuple(items),
        semantic_gold_keys=(semantic_gold.key,),
    )
    return scope, tuple(records), tuple(reviews)


def _derived_human_evidence(
    gold_records: tuple[GoldRecord, ...],
) -> HumanReviewEvidence:
    scope = tuple(
        ReviewScopeItem(
            case_id=item.case_id,
            requirement_id=item.requirement_id,
        )
        for item in gold_records
    )
    reviews = tuple(
        review
        for index, (scope_item, gold) in enumerate(
            zip(scope, gold_records, strict=True),
            start=1,
        )
        for review in (
            DerivedBlindReviewRecord(
                review_id=f"derived-review-a-{index:02d}",
                reviewer_role_id="derived-reviewer-a",
                case_id=scope_item.case_id,
                requirement_id=scope_item.requirement_id,
                verdict=ReviewVerdict(gold.verdict.value),
                evidence_refs=gold.evidence_refs,
                rationale="Synthetic record for readiness contract testing.",
                blinded_to_arm=True,
                blinded_to_model=True,
            ),
            DerivedBlindReviewRecord(
                review_id=f"derived-review-b-{index:02d}",
                reviewer_role_id="derived-reviewer-b",
                case_id=scope_item.case_id,
                requirement_id=scope_item.requirement_id,
                verdict=ReviewVerdict(gold.verdict.value),
                evidence_refs=gold.evidence_refs,
                rationale="Synthetic record for readiness contract testing.",
                blinded_to_arm=True,
                blinded_to_model=True,
            ),
        )
    )
    return HumanReviewEvidence(
        attestation_kind=HumanAttestationKind.TEST_ONLY,
        corpus_id="synthetic-readiness-human-contract-v1",
        scope=scope,
        blind_reviews=reviews,
        adjudications=(),
        gold_author_role_id="gold-author",
        operational_escalator_role_id="operational-escalator",
    )


def _formal_artifacts(
    gold_scope: GoldScopeManifest,
    gold_records: tuple[GoldRecord, ...],
    reviews: tuple[BlindReviewerRecord, ...],
) -> tuple[FormalArtifactLayout, GoldArtifactManifest, GoldMountManifest]:
    layout = FormalArtifactLayout(
        comparison_block_id="pilot-block-20260730",
        gold_directory="gold",
        gold_manifest_path="gold/manifest.json",
        gold_mount_manifest_path="gold/mount_manifest.json",
    )
    manifest = GoldArtifactManifest(
        manifest_id="pilot-gold-artifacts-v1",
        version=1,
        comparison_block_id=layout.comparison_block_id,
        gold_scope_hash=gold_scope.contract_hash,
        gold_binding_hash=formal_gold_binding_hash(
            gold_scope,
            gold_records,
        ),
        gold_record_hashes=tuple(item.contract_hash for item in gold_records),
        reviewer_record_hashes=tuple(item.contract_hash for item in reviews),
        adjudication_record_hashes=(),
    )
    mount = GoldMountManifest(
        manifest_id="pilot-gold-mount-v1",
        version=1,
        comparison_block_id=layout.comparison_block_id,
        gold_manifest_hash=manifest.contract_hash,
        runtime_gold_path="gold",
        subject_mounted=False,
        evaluator_mounted=False,
        judge_mounted=False,
        review_plane_read_only=True,
    )
    return layout, manifest, mount


def test_external_identifiers_reject_placeholder_values() -> None:
    with pytest.raises(ContractError, match="placeholder"):
        replace(_judge_card(), provider="TBD")
    with pytest.raises(ContractError, match="placeholder"):
        ApprovalManifest(
            manifest_id="approval-v1",
            version=1,
            lock_sha256=_hash(),
            approved=True,
            approver_role_id="unknown",
            approved_at="2026-07-30T12:00:00Z",
        )

    skeleton = JudgeCard(
        card_id="judge-card-unbound",
        version=1,
        provider=None,
        model_id=None,
        model_digest=None,
        prompt_hash=None,
        rubric_hash=None,
        parser_hash=None,
        sampling_config=(),
        calibration_set_hash=None,
        audit_set_hash=None,
        qualified_dimensions=(),
        qualification_time=None,
    )
    assert skeleton.is_bound is False


def test_arm_order_is_seeded_versioned_and_hash_bound() -> None:
    first = arm_order_manifest()
    second = arm_order_manifest()

    assert first == second
    assert first.seed == ARM_ORDER_SEED == 260722
    assert first.algorithm == "meas0.sha256-sort.v1"
    assert set(first.resolved_arm_order) == {
        "self_eval",
        "judge_only",
        "state_only",
        "rules_state",
        "evaluation_plane",
    }
    assert len(first.order_hash) == 64
    with pytest.raises(ContractError, match="resolved arm order"):
        replace(first, resolved_arm_order=tuple(reversed(first.resolved_arm_order)))


def test_judge_manifests_and_qualification_are_fail_closed() -> None:
    calibration = JCalManifest(
        manifest_id="J-CAL-v1",
        version=1,
        effective_seeds=(8111, 8117),
        items=_judge_items(held_out=False),
    )
    audit = JAuditManifest(
        manifest_id="J-AUDIT-v1",
        version=1,
        effective_seeds=(8111, 8117),
        items=_judge_items(held_out=True),
    )
    assert calibration.label_counts == {"pass": 16, "fail": 16, "unknown": 16}
    assert audit.label_counts == calibration.label_counts

    card = _judge_card()
    qualification = _qualified(card)
    assert qualification.qualified is True
    failed = replace(
        qualification,
        false_accept=RateEstimate(0.11, 0.04, 0.20, 32),
    )
    assert failed.qualified is False
    quarantine = JudgeQuarantine(
        quarantine_id="quarantine-1",
        judge_card_hash=card.contract_hash,
        qualification_hash=failed.contract_hash,
        reason="false accept threshold exceeded",
        quarantined_at="2026-07-30T12:10:00Z",
    )
    assert quarantine.contract_hash != failed.contract_hash


def test_judge_invocation_contract_and_double_presentation_fusion() -> None:
    card = _judge_card()
    normal = JudgeInvocation(
        invocation_id="invoke-normal",
        judge_card_hash=card.contract_hash,
        case_id="case-01",
        criterion_id="semantic-01",
        presentation="normal",
        effective_seed=8111,
        request_fingerprint=_hash("7"),
        evidence_refs=("response:final",),
        input_tokens_limit=8192,
        output_tokens_limit=1024,
        timeout_ms=120_000,
    )
    reversed_invocation = replace(
        normal,
        invocation_id="invoke-reversed",
        presentation="reversed",
        effective_seed=8117,
        request_fingerprint=_hash("8"),
    )
    normal_response = JudgeResponse(
        invocation_id=normal.invocation_id,
        criterion_id=normal.criterion_id,
        verdict=EvaluationStatus.PASS,
        evidence_refs=("response:final",),
        rationale="Actionable.",
        confidence_0_1=0.9,
        p_pass_0_1=0.8,
        judge_version="judge-card-v1",
        raw_response_hash=_hash("9"),
    )
    reversed_response = replace(
        normal_response,
        invocation_id=reversed_invocation.invocation_id,
        verdict=EvaluationStatus.FAIL,
        raw_response_hash=_hash("a"),
    )

    with pytest.raises(ContractError, match="pass probability"):
        replace(normal_response, p_pass_0_1=True)
    with pytest.raises(ContractError, match="pass probability"):
        replace(normal_response, p_pass_0_1=1.01)

    assert (
        fuse_judge_presentations(
            normal,
            normal_response,
            reversed_invocation,
            reversed_response,
        )
        is EvaluationStatus.DISPUTED
    )
    assert (
        fuse_judge_presentations(
            normal,
            normal_response,
            reversed_invocation,
            replace(reversed_response, verdict=EvaluationStatus.UNKNOWN),
        )
        is EvaluationStatus.UNKNOWN
    )


def test_gold_records_preserve_blind_reviews_and_adjudication() -> None:
    gold, reviews = _gold_records()
    first_reviewer = (
        reviews[0],
        replace(
            reviews[0],
            review_id="review-1-item-2",
            case_id="case-02",
        ),
    )
    second_reviewer = (
        replace(reviews[1], verdict=EvaluationStatus.FAIL),
        replace(
            reviews[1],
            review_id="review-2-item-2",
            case_id="case-02",
        ),
    )
    agreement = compute_gold_agreement(
        first_reviewer,
        second_reviewer,
    )
    assert agreement.item_count == 2
    assert agreement.raw_agreement == 0.5
    assert agreement.cohen_kappa == 0.0

    disagreement = replace(
        reviews[1],
        verdict=EvaluationStatus.FAIL,
    )
    adjudication = AdjudicationRecord(
        adjudication_id="adjudication-1",
        case_id=gold.case_id,
        requirement_id=gold.requirement_id,
        first_review_hash=reviews[0].contract_hash,
        first_verdict=reviews[0].verdict,
        second_review_hash=disagreement.contract_hash,
        second_verdict=disagreement.verdict,
        adjudicator_role_id="adjudicator",
        final_verdict=EvaluationStatus.UNKNOWN,
        evidence_refs=("response:final",),
        rationale="Evidence does not resolve the reviewer disagreement.",
    )
    assert adjudication.first_verdict is EvaluationStatus.PASS
    assert adjudication.second_verdict is EvaluationStatus.FAIL


def test_formal_readiness_report_is_hash_bound_and_blocks_missing_bindings() -> None:
    report = FormalReadinessValidator().validate(FormalReadinessInputs())

    assert report.state is FormalReadinessState.DESIGN_COMPLETE_NOT_RUNNABLE
    assert ReadinessBlockerCode.FORMAL_LOCK_BINDINGS_INCOMPLETE in report.blockers
    assert ReadinessBlockerCode.CASE_SCOPE_MISSING in report.blockers
    assert ReadinessBlockerCode.JUDGE_CARD_MISSING in report.blockers
    assert ReadinessBlockerCode.GOLD_SCOPE_MISSING in report.blockers
    assert ReadinessBlockerCode.ARTIFACT_LAYOUT_MISSING in report.blockers
    assert ReadinessBlockerCode.GOLD_ARTIFACT_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.GOLD_MOUNT_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.PREFLIGHT_MISSING in report.blockers
    assert ReadinessBlockerCode.TRUST_ROOTS_MISSING in report.blockers
    assert ReadinessBlockerCode.TRANSPORT_RECEIPTS_MISSING in report.blockers
    assert ReadinessBlockerCode.HUMAN_SIGNATURES_MISSING in report.blockers
    assert ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_MISSING in report.blockers
    assert ReadinessBlockerCode.PRICE_QUOTE_RECEIPTS_MISSING in report.blockers
    assert ReadinessBlockerCode.JUDGE_INVOCATION_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.JAUDIT_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.JAUDIT_QUALIFICATION_MISSING in report.blockers
    assert ReadinessBlockerCode.JAUDIT_TRANSPORT_MISSING in report.blockers
    assert ReadinessBlockerCode.JAUDIT_STAGE_LEDGER_MISSING in report.blockers
    assert ReadinessBlockerCode.JAUDIT_INVOCATION_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.JUDGE_SET_PROVENANCE_MISSING in report.blockers
    assert ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.STAGE_BUDGET_MANIFEST_MISSING in report.blockers
    assert ReadinessBlockerCode.STAGE_COST_LEDGER_MISSING in report.blockers
    assert ReadinessBlockerCode.DETECTION_ORACLE_MISSING in report.blockers
    assert len(report.report_hash) == 64
    with pytest.raises(ContractError, match="not runnable"):
        require_formal_readiness(report)
    with pytest.raises(ContractError, match="hash mismatch"):
        replace(report, report_hash=_hash())
    bundle = FormalReadinessBundle.create(FormalReadinessInputs())
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle
    tampered = bundle.to_dict()
    tampered["inputs"]["operational_escalator_role_id"] = "forged-role"
    with pytest.raises(ContractError, match="hash|report"):
        FormalReadinessBundle.from_dict(tampered)


def test_candidate_detection_oracle_is_bound_but_never_formal_ready() -> None:
    candidate = build_test_only_candidate_oracle(
        design_sha256=_hash("a"),
        fault_manifest_sha256=_hash("b"),
        case_manifest_sha256=_hash("c"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _hash("d"),
            "channel_order_ingest": _hash("e"),
        },
        source_hashes={"src/oracle.py": _hash("f")},
    )
    bundle = FormalReadinessBundle.create(
        FormalReadinessInputs(detection_oracle_manifest=candidate)
    )

    assert ReadinessBlockerCode.DETECTION_ORACLE_MISSING not in bundle.report.blockers
    assert ReadinessBlockerCode.DETECTION_ORACLE_INVALID in bundle.report.blockers
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle


def test_legacy_gold_and_preflight_self_reports_cannot_satisfy_readiness() -> None:
    case_scope = _case_scope()
    gold_scope, gold_records, reviews = _complete_gold(case_scope)
    policy, acl, legacy_preflight = _isolation()

    report = FormalReadinessValidator().validate(
        FormalReadinessInputs(
            case_scope_manifest=case_scope,
            gold_scope_manifest=gold_scope,
            gold_records=gold_records,
            reviewer_records=reviews,
            operational_escalator_role_id="operational-escalator",
            isolation_policy=policy,
            acl_manifest=acl,
            preflight_report=legacy_preflight,
        )
    )

    assert ReadinessBlockerCode.PREFLIGHT_EVIDENCE_MISSING in report.blockers
    assert ReadinessBlockerCode.HUMAN_EVIDENCE_MISSING in report.blockers


def test_test_only_derived_evidence_is_hash_bound_but_remains_blocked() -> None:
    case_scope = _case_scope()
    gold_scope, gold_records, reviews = _complete_gold(case_scope)
    preflight_evidence = _derived_preflight()
    human_evidence = _derived_human_evidence(gold_records)
    inputs = FormalReadinessInputs(
        case_scope_manifest=case_scope,
        gold_scope_manifest=gold_scope,
        gold_records=gold_records,
        reviewer_records=reviews,
        operational_escalator_role_id="operational-escalator",
        preflight_evidence=preflight_evidence,
        human_evidence=human_evidence,
    )

    report = FormalReadinessValidator().validate(inputs)
    hashes = dict(report.input_hashes)

    assert ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID in report.blockers
    assert ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID in report.blockers
    assert hashes["preflight_evidence"] == preflight_evidence.evidence_sha256
    assert (
        hashes["preflight_command_records"]
        == hashlib.sha256(
            json.dumps(
                [item.raw_record_sha256 for item in preflight_evidence.command_records],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert hashes["human_evidence"] == human_evidence.evidence_sha256
    assert (
        hashes["human_review_records"]
        == hashlib.sha256(
            json.dumps(
                [item.record_hash for item in human_evidence.blind_reviews],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    bundle = FormalReadinessBundle.create(inputs)
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle
    tampered_preflight = bundle.to_dict()
    tampered_preflight["inputs"]["preflight_evidence"]["command_records"][0][
        "stdout_hex"
    ] = b"forged\n".hex()
    with pytest.raises(ContractError, match="command record hash"):
        FormalReadinessBundle.from_dict(tampered_preflight)
    tampered_review = bundle.to_dict()
    tampered_review["inputs"]["human_evidence"]["blind_reviews"][0]["rationale"] = (
        "Forged review."
    )
    with pytest.raises(ContractError, match="review record hash"):
        FormalReadinessBundle.from_dict(tampered_review)


def test_contract_only_production_evidence_removes_only_derived_blockers() -> None:
    """Exercise the validator contract without claiming real external work."""
    case_scope = _case_scope()
    gold_scope, gold_records, reviews = _complete_gold(case_scope)
    policy, acl, _ = _isolation()
    preflight_evidence = replace(
        _derived_preflight(),
        attestation_kind=PreflightAttestationKind.PRODUCTION,
    )
    human_evidence = replace(
        _derived_human_evidence(gold_records),
        attestation_kind=HumanAttestationKind.PRODUCTION,
    )

    report = FormalReadinessValidator().validate(
        FormalReadinessInputs(
            case_scope_manifest=case_scope,
            gold_scope_manifest=gold_scope,
            gold_records=gold_records,
            reviewer_records=reviews,
            operational_escalator_role_id="operational-escalator",
            isolation_policy=policy,
            acl_manifest=acl,
            preflight_evidence=preflight_evidence,
            human_evidence=human_evidence,
        )
    )

    assert ReadinessBlockerCode.PREFLIGHT_EVIDENCE_MISSING not in report.blockers
    assert ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID not in report.blockers
    assert ReadinessBlockerCode.HUMAN_EVIDENCE_MISSING not in report.blockers
    assert ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID not in report.blockers


def test_formal_readiness_requires_gold_for_every_typed_case() -> None:
    case_scope = _case_scope()
    gold_scope, gold_records, reviews = _complete_gold(case_scope)
    incomplete = FormalReadinessValidator().validate(
        FormalReadinessInputs(
            case_scope_manifest=case_scope,
            gold_scope_manifest=gold_scope,
            gold_records=gold_records[:1],
            reviewer_records=reviews[:2],
            operational_escalator_role_id="operational-escalator",
        )
    )
    assert ReadinessBlockerCode.GOLD_RECORDS_INCOMPLETE in incomplete.blockers
    assert ReadinessBlockerCode.GOLD_REVIEWS_INCOMPLETE in incomplete.blockers

    non_native_cases = (
        replace(case_scope.cases[0], native_adapter=False),
        *case_scope.cases[1:],
    )
    non_native_scope = replace(case_scope, cases=non_native_cases)
    non_native = FormalReadinessValidator().validate(
        FormalReadinessInputs(case_scope_manifest=non_native_scope)
    )
    assert ReadinessBlockerCode.NATIVE_CASE_COVERAGE_INCOMPLETE in non_native.blockers
    with pytest.raises(ContractError, match="accept_allowed"):
        replace(gold_records[0], accept_allowed=False)
    with pytest.raises(ContractError, match="null gold status"):
        replace(
            gold_records[0],
            gold_run_validity=GoldRunValidity.INVALID,
        )


def test_formal_readiness_requires_external_approval_and_role_separation() -> None:
    calibration = JCalManifest(
        manifest_id="J-CAL-v1",
        version=1,
        effective_seeds=(8111, 8117),
        items=_judge_items(held_out=False),
    )
    card = replace(
        _judge_card(),
        calibration_set_hash=calibration.contract_hash,
    )
    case_scope = _case_scope()
    gold_scope, gold_records, reviews = _complete_gold(case_scope)
    human_evidence = _derived_human_evidence(gold_records)
    layout, gold_artifacts, gold_mount = _formal_artifacts(
        gold_scope,
        gold_records,
        reviews,
    )
    policy, acl, preflight = _isolation()
    preflight_evidence = _derived_preflight()
    budget = _budget()
    price = _price()
    order = arm_order_manifest()
    binding_values = {
        name: _hash(f"{index:x}"[-1])
        for index, name in enumerate(REQUIRED_FORMAL_LOCK_BINDINGS)
    }
    binding_values.update(
        case_manifest=case_scope.contract_hash,
        task_answer_gold=formal_gold_binding_hash(gold_scope, gold_records),
        formal_artifact_layout=layout.contract_hash,
        gold_artifact_manifest=gold_artifacts.contract_hash,
        gold_mount_manifest=gold_mount.contract_hash,
        judge_card=card.contract_hash,
        seed_block=order.contract_hash,
        price_manifest=price.contract_hash,
        budget_policy=budget.contract_hash,
        isolation_policy=policy.contract_hash,
        acl_manifest=acl.contract_hash,
        preflight_evidence=preflight_evidence.evidence_sha256,
        human_evidence=human_evidence.evidence_sha256,
    )
    lock = FormalLockBindings(bindings=tuple(binding_values.items()))
    inputs = FormalReadinessInputs(
        case_scope_manifest=case_scope,
        gold_scope_manifest=gold_scope,
        gold_records=gold_records,
        reviewer_records=reviews,
        formal_artifact_layout=layout,
        gold_artifact_manifest=gold_artifacts,
        gold_mount_manifest=gold_mount,
        adjudication_records=(),
        operational_escalator_role_id="reviewer-a",
        human_evidence=human_evidence,
        judge_calibration_manifest=calibration,
        judge_card=card,
        judge_evidence=_test_only_judge_evidence(card, calibration),
        budget_policy=budget,
        price_manifest=price,
        isolation_policy=policy,
        acl_manifest=acl,
        preflight_report=preflight,
        preflight_evidence=preflight_evidence,
        approval_manifest=ApprovalManifest(
            manifest_id="approval-v1",
            version=1,
            lock_sha256=lock["preregistration_lock"],
            approved=False,
            approver_role_id=None,
            approved_at=None,
        ),
        arm_order=order,
        formal_lock_bindings=lock,
    )
    blocked = FormalReadinessValidator().validate(inputs)
    assert ReadinessBlockerCode.ROLE_SEPARATION_VIOLATION in blocked.blockers
    assert ReadinessBlockerCode.APPROVAL_NOT_GRANTED in blocked.blockers

    ready_inputs = replace(
        inputs,
        operational_escalator_role_id="operational-escalator",
        approval_manifest=ApprovalManifest(
            manifest_id="approval-v1",
            version=1,
            lock_sha256=lock["preregistration_lock"],
            approved=True,
            approver_role_id="lock-approver",
            approved_at="2026-07-30T12:30:00Z",
        ),
    )
    ready = FormalReadinessValidator().validate(ready_inputs)
    assert ready.state is FormalReadinessState.DESIGN_COMPLETE_NOT_RUNNABLE
    assert {
        ReadinessBlockerCode.JUDGE_NOT_QUALIFIED,
        ReadinessBlockerCode.PREFLIGHT_FAILED,
        ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID,
        ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID,
        ReadinessBlockerCode.TRUST_ROOTS_MISSING,
        ReadinessBlockerCode.TRANSPORT_RECEIPTS_MISSING,
        ReadinessBlockerCode.HUMAN_SIGNATURES_MISSING,
        ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_MISSING,
        ReadinessBlockerCode.STAGE_BUDGET_MANIFEST_MISSING,
        ReadinessBlockerCode.STAGE_COST_LEDGER_MISSING,
        ReadinessBlockerCode.DETECTION_ORACLE_MISSING,
    } <= set(ready.blockers)
    with pytest.raises(ContractError, match="not runnable"):
        require_formal_readiness(ready)
    assert ready.report_hash != blocked.report_hash
    evidence = ready_inputs.judge_evidence
    assert evidence is not None
    production_labeled_evidence = replace(
        evidence,
        source_corpus=replace(
            evidence.source_corpus,
            attestation=replace(
                evidence.attestation,
                test_only=False,
            ),
        ),
    )
    missing_trusted_transport = FormalReadinessValidator().validate(
        replace(
            ready_inputs,
            judge_evidence=production_labeled_evidence,
        )
    )
    assert (
        ReadinessBlockerCode.JUDGE_NOT_QUALIFIED in missing_trusted_transport.blockers
    )
    ready_bundle = FormalReadinessBundle.create(ready_inputs)
    assert FormalReadinessBundle.from_dict(ready_bundle.to_dict()) == ready_bundle

    reused_approver = FormalReadinessValidator().validate(
        replace(
            ready_inputs,
            approval_manifest=replace(
                ready_inputs.approval_manifest,
                approver_role_id="gold-author",
            ),
        )
    )
    assert ReadinessBlockerCode.ROLE_SEPARATION_VIOLATION in reused_approver.blockers


def test_formal_readiness_inputs_reject_naked_qualification() -> None:
    card = _judge_card()

    with pytest.raises(TypeError, match="judge_qualification"):
        FormalReadinessInputs(
            judge_qualification=_qualified(card),  # type: ignore[call-arg]
        )
