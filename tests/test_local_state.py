from __future__ import annotations

import hashlib
import json

import pytest

from biofield.contracts import (
    ExperienceUpdateRecord,
    ExperienceValidationStatus,
    LocalStateSnapshot,
    LocalStateUpdate,
    LocalStateUpdateIssuer,
    LocalStateUpdateProposal,
    UpdateSurfaceManifest,
    UpdateSurfaceRule,
)
from biofield.local_state import (
    LocalStateGovernanceError,
    apply_local_state_update,
    compile_local_state_update,
    consume_experience,
    replay_local_state_updates,
    rollback_local_state_update,
)


FROZEN_SURFACES = (
    "permissions",
    "residual",
    "goal_graph",
    "requirement_graph",
    "measurement_graph",
    "measurement_spec",
    "evaluator",
    "ledger",
    "event_schema",
    "experiment_score",
)


def _manifest(**overrides: object) -> UpdateSurfaceManifest:
    values: dict[str, object] = {
        "schema_version": 1,
        "manifest_id": "manifest-1",
        "run_id": "run-1",
        "manifest_version": 1,
        "mutable_surface_rules": (
            UpdateSurfaceRule(
                surface="local.capability",
                surface_schema_version=1,
                max_serialized_bytes=512,
                max_updates_per_run=8,
            ),
            UpdateSurfaceRule(
                surface="experience.capability",
                surface_schema_version=1,
                max_serialized_bytes=512,
                max_updates_per_run=4,
            ),
        ),
        "frozen_surfaces": FROZEN_SURFACES,
        "promotion_rules": ("validated-feedback-only",),
        "invalidation_rules": ("source-event-invalidated",),
        "rollback_policy": "sealed-checkpoint-v1",
    }
    values.update(overrides)
    return UpdateSurfaceManifest(**values)


def _snapshot(**overrides: object) -> LocalStateSnapshot:
    values: dict[str, object] = {
        "schema_version": 1,
        "agent_id": "agent-1",
        "state_version": 0,
        "values": {
            "local.capability.alpha": 0.2,
            "local.capability.note": "initial",
        },
        "source_update_ids": (),
    }
    values.update(overrides)
    return LocalStateSnapshot(**values)


def _proposal(**overrides: object) -> LocalStateUpdateProposal:
    values: dict[str, object] = {
        "schema_version": 1,
        "proposal_id": "proposal-1",
        "agent_id": "agent-1",
        "manifest_id": "manifest-1",
        "manifest_version": 1,
        "previous_state_version": 0,
        "destination_surface": "local.capability",
        "update_kind": "feedback_assimilation",
        "source_event_window": ("feedback-1",),
        "changed_fields": ("local.capability.alpha",),
        "proposed_values": {"local.capability.alpha": 0.7},
        "reversible": True,
        "rollback_ref": "checkpoint://run-1/agent-1/v0",
    }
    values.update(overrides)
    return LocalStateUpdateProposal(**values)


def _compile(**overrides: object) -> LocalStateUpdate:
    values: dict[str, object] = {
        "snapshot": _snapshot(),
        "proposal": _proposal(),
        "manifest": _manifest(),
        "authorized_event_ids": ("feedback-1", "action-1"),
        "compiler_policy_version": "compiler-v1",
        "run_finalized": False,
    }
    values.update(overrides)
    return compile_local_state_update(**values)


def _experience(
    status: ExperienceValidationStatus,
    **overrides: object,
) -> ExperienceUpdateRecord:
    promoted = status is ExperienceValidationStatus.PROMOTED
    values: dict[str, object] = {
        "schema_version": 1,
        "experience_update_id": f"experience-{status.value}",
        "agent_id": "agent-1",
        "manifest_id": "manifest-1",
        "manifest_version": 1,
        "source_event_window": ("feedback-1",),
        "compiler_policy_version": "experience-compiler-v1",
        "destination_surface": "experience.capability",
        "previous_version": 0,
        "candidate_hash": hashlib.sha256(b"candidate").hexdigest(),
        "validation_status": status,
        "promoted_version": 1 if promoted else None,
        "rejected_reason": None if promoted else "validation did not pass",
        "expires_at": "2026-08-30T09:00:00+08:00",
        "invalidation_conditions": ("feedback-1-invalidated",),
        "rollback_ref": "experience://agent-1/v0",
        "issuer": LocalStateUpdateIssuer.HARNESS_COMPILER,
    }
    values.update(overrides)
    return ExperienceUpdateRecord(**values)


def test_manifest_requires_frozen_governance_surfaces_and_disjoint_mutability() -> None:
    with pytest.raises(ValueError, match="required frozen surfaces"):
        _manifest(frozen_surfaces=("ledger",))

    with pytest.raises(ValueError, match="both mutable and frozen"):
        _manifest(
            mutable_surface_rules=(
                UpdateSurfaceRule(
                    surface="ledger",
                    surface_schema_version=1,
                    max_serialized_bytes=32,
                    max_updates_per_run=1,
                ),
            )
        )

    with pytest.raises(ValueError, match="both mutable and frozen"):
        _manifest(
            mutable_surface_rules=(
                UpdateSurfaceRule(
                    surface="permissions.agent",
                    surface_schema_version=1,
                    max_serialized_bytes=32,
                    max_updates_per_run=1,
                ),
            )
        )


def test_agent_proposal_requires_sources_and_manifest_scoped_fields() -> None:
    with pytest.raises(ValueError, match="source_event_window cannot be empty"):
        _proposal(source_event_window=())

    with pytest.raises(LocalStateGovernanceError, match="outside destination"):
        _compile(
            proposal=_proposal(
                changed_fields=("permissions.admin",),
                proposed_values={"permissions.admin": True},
            )
        )


def test_compiler_rejects_unauthorized_sources_frozen_surfaces_and_finalized_run() -> None:
    with pytest.raises(LocalStateGovernanceError, match="unauthorized source"):
        _compile(authorized_event_ids=("action-1",))

    with pytest.raises(LocalStateGovernanceError, match="not mutable"):
        _compile(
            proposal=_proposal(
                destination_surface="ledger",
                changed_fields=("ledger.tokens",),
                proposed_values={"ledger.tokens": 1_000_000},
            )
        )

    with pytest.raises(LocalStateGovernanceError, match="finalized"):
        _compile(run_finalized=True)


def test_local_state_update_is_deterministic_replayable_and_reversible() -> None:
    before = _snapshot()
    first = _compile(snapshot=before)
    second = _compile(snapshot=before)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.previous_state_version == 0
    assert first.next_state_version == 1

    after = apply_local_state_update(before, first)
    assert after.state_version == 1
    assert after.values["local.capability.alpha"] == 0.7
    assert after.state_hash() == first.after_hash
    assert replay_local_state_updates(before, (first,)) == after
    assert rollback_local_state_update(after, first, before) == before


def test_update_rejects_version_jump_and_agent_self_submission() -> None:
    update = _compile()
    payload = update.to_dict()

    with pytest.raises(ValueError, match="next_state_version"):
        LocalStateUpdate.from_dict({**payload, "next_state_version": 2})

    with pytest.raises(ValueError, match="Harness compiler"):
        LocalStateUpdate.from_dict(
            {**payload, "issuer": LocalStateUpdateIssuer.AGENT_PROPOSAL}
        )


def test_apply_rejects_wrong_before_hash_and_non_contiguous_replay() -> None:
    update = _compile()

    with pytest.raises(LocalStateGovernanceError, match="before_hash"):
        apply_local_state_update(
            _snapshot(values={"local.capability.alpha": 0.1}),
            update,
        )

    with pytest.raises(LocalStateGovernanceError, match="version"):
        replay_local_state_updates(
            _snapshot(
                state_version=1,
                source_update_ids=("prior-update",),
            ),
            (update,),
        )


@pytest.mark.parametrize(
    "status",
    (
        ExperienceValidationStatus.REJECTED,
        ExperienceValidationStatus.QUARANTINED,
    ),
)
def test_rejected_or_quarantined_experience_cannot_be_consumed(status) -> None:
    with pytest.raises(LocalStateGovernanceError, match="not promoted"):
        consume_experience(
            _experience(status),
            _manifest(),
            authorized_event_ids=("feedback-1",),
            at="2026-08-01T09:00:00+08:00",
        )


def test_experience_record_requires_compiler_validation_and_rollback_contracts() -> None:
    with pytest.raises(ValueError, match="compiler_policy_version"):
        _experience(
            ExperienceValidationStatus.PROMOTED,
            compiler_policy_version="",
        )
    with pytest.raises(ValueError, match="validation_status"):
        _experience(
            ExperienceValidationStatus.PROMOTED,
            validation_status="forged",
        )
    with pytest.raises(ValueError, match="rollback_ref"):
        _experience(
            ExperienceValidationStatus.PROMOTED,
            rollback_ref="",
        )


def test_experience_outside_manifest_surface_cannot_be_consumed() -> None:
    with pytest.raises(LocalStateGovernanceError, match="not mutable"):
        consume_experience(
            _experience(
                ExperienceValidationStatus.PROMOTED,
                destination_surface="experience.unapproved",
            ),
            _manifest(),
            authorized_event_ids=("feedback-1",),
            at="2026-08-01T09:00:00+08:00",
        )


def test_only_authorized_unexpired_promoted_experience_is_consumable() -> None:
    record = _experience(ExperienceValidationStatus.PROMOTED)
    assert (
        consume_experience(
            record,
            _manifest(),
            authorized_event_ids=("feedback-1",),
            at="2026-08-01T09:00:00+08:00",
        )
        == record.candidate_hash
    )

    with pytest.raises(LocalStateGovernanceError, match="unauthorized source"):
        consume_experience(
            record,
            _manifest(),
            authorized_event_ids=("other",),
            at="2026-08-01T09:00:00+08:00",
        )
    with pytest.raises(LocalStateGovernanceError, match="expired"):
        consume_experience(
            record,
            _manifest(),
            authorized_event_ids=("feedback-1",),
            at="2026-09-01T09:00:00+08:00",
        )


def test_state_and_experience_contracts_round_trip_canonically() -> None:
    contracts = (
        _manifest(),
        _snapshot(),
        _proposal(),
        _compile(),
        _experience(ExperienceValidationStatus.PROMOTED),
    )

    for contract in contracts:
        encoded = contract.to_json()
        restored = type(contract).from_dict(json.loads(encoded))
        assert restored == contract
        assert restored.to_json() == encoded
