from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.contracts import (
    CommitmentStatus,
    FeedbackDisposition,
    RequirementStatus,
    ResourceAmount,
)
from biofield.dispute_runtime import (
    IndependentRevalidationDecision,
    RevalidationEvidence,
    RevalidationIssuer,
    replay_disputed_revalidation,
    resume_disputed_revalidation,
    run_disputed_revalidation,
    run_dispute_to_checkpoint,
)
from biofield.local_runtime import HarnessCycleError
from test_local_runtime import (
    _admission_policy,
    _candidate,
    _execution,
    _manifest,
    _plan,
    _selection,
    _state_proposal,
    _state_snapshot,
    _task,
    _verifier,
)
from biofield.multi_admission import MultiAdmissionPolicy


def _multi_policy():
    return MultiAdmissionPolicy(
        schema_version=1,
        policy_version="multi-v1",
        max_concurrent_commitments=1,
        max_commitments_per_requirement=1,
        exploration_min_slots=0,
        tie_break_rule="bid_id_lexicographic",
    )


def _disputed_verifier():
    return _verifier(
        feedback_disposition=FeedbackDisposition.DISPUTED,
        confidence=0.5,
        evaluator_version="initial-verifier-v1",
    )


def _new_evidence(**overrides):
    values = {
        "evidence_id": "revalidation-evidence-1",
        "content": b"independent source reproduction",
        "artifact_refs": ("artifact://independent-source",),
        "provenance_refs": ("verifier://independent-v2/run-1",),
        "invalidates_evidence_ids": ("evidence-1",),
        "resource_cost": (ResourceAmount("tokens", 5),),
        "collected_at": "2026-07-30T09:02:00+08:00",
        "issuer": RevalidationIssuer.INDEPENDENT_EVIDENCE_COLLECTOR,
    }
    values.update(overrides)
    return RevalidationEvidence(**values)


def _resolution(**overrides):
    values = {
        "decision_id": "revalidation-decision-1",
        "evidence_id": "revalidation-evidence-1",
        "disposition": FeedbackDisposition.ACCEPTED,
        "confidence": 0.95,
        "verifier_authority": "independent-verifier-v2",
        "invalidates_feedback_ids": ("feedback-plan-1",),
        "invalidates_evidence_ids": ("evidence-1",),
        "decided_at": "2026-07-30T09:02:10+08:00",
        "issuer": RevalidationIssuer.INDEPENDENT_VERIFIER,
    }
    values.update(overrides)
    return IndependentRevalidationDecision(**values)


def _resolution_proposal():
    return replace(
        _state_proposal(),
        proposal_id="state-proposal-revalidation-1",
        source_event_window=("feedback-revalidation-decision-1",),
    )


def _base_kwargs():
    candidate = _candidate()
    return {
        "run_id": "dispute-run-1",
        "task": _task(),
        "selection": _selection(candidate),
        "candidate": candidate,
        "admission_policy": _admission_policy(),
        "multi_admission_policy": _multi_policy(),
        "plan": _plan(),
        "execution": _execution(),
        "disputed_verifier_decision": _disputed_verifier(),
        "initial_local_state": _state_snapshot(),
        "state_update_manifest": replace(_manifest(), run_id="dispute-run-1"),
        "quarantined_state_update_proposal": _state_proposal(),
        "state_compiler_policy_version": "state-compiler-v1",
        "run_budget": (ResourceAmount("tokens", 100),),
        "admission_at": "2026-07-30T09:00:30+08:00",
        "action_at": "2026-07-30T09:01:10+08:00",
        "finished_at": "2026-07-30T09:01:20+08:00",
    }


def _run(**overrides):
    values = {
        **_base_kwargs(),
        "revalidation_evidence": _new_evidence(),
        "revalidation_decision": _resolution(),
        "resolution_state_update_proposal": _resolution_proposal(),
    }
    values.update(overrides)
    return run_disputed_revalidation(**values)


def _replay(events, *, resolution_proposal=_resolution_proposal()):
    return replay_disputed_revalidation(
        **_base_kwargs(),
        resolution_state_update_proposal=resolution_proposal,
        events=tuple(events),
    )


def _rehash(event, payload):
    return replace(
        event,
        payload=payload,
        payload_sha256=hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    )


def test_disputed_feedback_quarantines_without_credit_or_state_update_then_accepts():
    result = _run()
    checkpoint = result.checkpoint
    prefix = result.events[: checkpoint.next_public_state_revision]

    assert checkpoint.residual.requirement(
        "sources"
    ).status is RequirementStatus.DISPUTED
    assert checkpoint.residual.complete is False
    assert checkpoint.local_state_version == 0
    assert checkpoint.ledger_totals["tokens"]["spent"] == "40"
    assert checkpoint.ledger_totals["tokens"]["shared_pool"] == "60"
    assert checkpoint.quarantine.commitment_status == "quarantined"
    assert checkpoint.quarantine.evidence_status == "quarantined"
    assert checkpoint.quarantine.feedback_status == "quarantined"
    assert checkpoint.quarantine.accepted_contribution == 0
    assert checkpoint.quarantine.experience_update_ids == ()
    assert not any(
        event.event_type
        in {"local_state_update", "local_state_snapshot", "experience_update"}
        for event in prefix
    )

    resumed = resume_disputed_revalidation(
        checkpoint=checkpoint,
        **_base_kwargs(),
        revalidation_evidence=_new_evidence(),
        revalidation_decision=_resolution(),
        resolution_state_update_proposal=_resolution_proposal(),
    )
    assert resumed.events == result.events[
        checkpoint.next_public_state_revision :
    ]
    assert result.residual.requirement(
        "sources"
    ).status is RequirementStatus.SATISFIED
    assert result.local_state.state_version == 1
    assert result.lifecycle.status is CommitmentStatus.COMPLETED
    assert result.ledger_totals["tokens"]["spent"] == "45"
    assert result.ledger_totals["tokens"]["shared_pool"] == "55"
    original = next(
        item
        for item in result.organization_snapshot.agent_cost_contributions
        if item.agent_id == "agent-1"
    )
    assert original.accepted_contribution == 1
    assert _replay(result.events).terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_independent_revalidation_can_reject_without_positive_local_state():
    result = _run(
        revalidation_decision=_resolution(
            disposition=FeedbackDisposition.REJECTED,
        ),
        resolution_state_update_proposal=None,
    )

    assert result.residual.requirement(
        "sources"
    ).status is RequirementStatus.UNMET
    assert result.local_state.state_version == 0
    assert result.lifecycle.status is CommitmentStatus.CANCELLED
    assert not any(
        event.event_type
        in {"local_state_update", "local_state_snapshot", "experience_update"}
        for event in result.events
    )
    original = next(
        item
        for item in result.organization_snapshot.agent_cost_contributions
        if item.agent_id == "agent-1"
    )
    assert original.accepted_contribution == 0
    replayed = _replay(
        result.events,
        resolution_proposal=None,
    )
    assert replayed.terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_original_agent_cannot_self_clear_and_old_evidence_cannot_be_reused():
    with pytest.raises(HarnessCycleError, match="independent verifier"):
        _run(
            revalidation_decision=_resolution(
                verifier_authority="agent-1",
            )
        )

    with pytest.raises(HarnessCycleError, match="new Evidence"):
        _run(
            revalidation_evidence=_new_evidence(
                evidence_id="evidence-1",
            ),
            revalidation_decision=_resolution(
                evidence_id="evidence-1",
            ),
        )

    with pytest.raises(HarnessCycleError, match="new Evidence"):
        _run(
            revalidation_evidence=_new_evidence(
                content=b"verified source record",
            )
        )


def test_replay_rejects_skipped_quarantine_double_resolution_and_semantic_tamper():
    result = _run()
    quarantine_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "dispute_quarantine"
    )
    disguised = replace(
        result.events[quarantine_index],
        event_type="untrusted_marker",
    )
    with pytest.raises(HarnessCycleError, match="quarantine"):
        _replay(
            (
                *result.events[:quarantine_index],
                disguised,
                *result.events[quarantine_index + 1 :],
            )
        )

    decision_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "revalidation_decision"
    )
    duplicate = replace(
        result.events[decision_index],
        public_state_revision=decision_index + 1,
    )
    shifted = tuple(
        replace(event, public_state_revision=event.public_state_revision + 1)
        for event in result.events[decision_index + 1 :]
    )
    with pytest.raises(HarnessCycleError, match="double.*resolution|duplicate"):
        _replay(
            (
                *result.events[: decision_index + 1],
                duplicate,
                *shifted,
            )
        )

    decision = result.events[decision_index]
    payload = decision.to_dict()["payload"]
    payload["decision"]["invalidates_feedback_ids"] = ()
    tampered = _rehash(decision, payload)
    with pytest.raises(HarnessCycleError, match="invalidates"):
        _replay(
            (
                *result.events[:decision_index],
                tampered,
                *result.events[decision_index + 1 :],
            )
        )

    payload = decision.to_dict()["payload"]
    payload["decision"]["verifier_authority"] = "agent-1"
    forged_verifier = _rehash(decision, payload)
    with pytest.raises(HarnessCycleError, match="independent verifier"):
        _replay(
            (
                *result.events[:decision_index],
                forged_verifier,
                *result.events[decision_index + 1 :],
            )
        )

    wrong_parent = replace(
        decision,
        causal_parent_ids=tuple(
            parent
            for parent in decision.causal_parent_ids
            if not parent.startswith("quarantine-")
        ),
    )
    with pytest.raises(HarnessCycleError, match="parent"):
        _replay(
            (
                *result.events[:decision_index],
                wrong_parent,
                *result.events[decision_index + 1 :],
            )
        )

    evidence_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "revalidation_evidence"
    )
    evidence_event = result.events[evidence_index]
    evidence_payload = evidence_event.to_dict()["payload"]
    evidence_payload["content_hex"] = b"verified source record".hex()
    evidence_payload["evidence"]["content_sha256"] = hashlib.sha256(
        b"verified source record"
    ).hexdigest()
    reused_content = _rehash(evidence_event, evidence_payload)
    with pytest.raises(HarnessCycleError, match="new Evidence"):
        _replay(
            (
                *result.events[:evidence_index],
                reused_content,
                *result.events[evidence_index + 1 :],
            )
        )


def test_checkpoint_is_public_and_semantically_bound():
    checkpointed = run_dispute_to_checkpoint(**_base_kwargs())
    encoded = json.dumps(
        checkpointed.checkpoint.to_dict(),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert '"events"' not in encoded
    assert '"values"' not in encoded
    assert '"proposed_values"' not in encoded
    assert checkpointed.checkpoint.prefix_event_ids == tuple(
        event.event_id for event in checkpointed.events
    )
    assert len(checkpointed.checkpoint.checkpoint_sha256) == 64
