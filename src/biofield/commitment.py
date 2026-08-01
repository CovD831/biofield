from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .contracts import (
    ActionAuthorization,
    ActionProposal,
    AgentCommitment,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    CommitmentTransition,
    GovernanceIssuer,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from .ledger import SHARED_POOL, agent_escrow_account


class CommitmentGovernanceError(ValueError):
    """An action or lifecycle transition violated Commitment governance."""


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise CommitmentGovernanceError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommitmentGovernanceError(
            f"{field_name} must include a UTC offset"
        )
    return parsed


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resource_map(values: tuple[ResourceAmount, ...]) -> dict[str, float]:
    return {item.resource_type: item.amount for item in values}


def initial_commitment_lifecycle(
    commitment: AgentCommitment,
) -> CommitmentLifecycleSnapshot:
    return CommitmentLifecycleSnapshot(
        schema_version=1,
        commitment_id=commitment.commitment_id,
        status=CommitmentStatus.ACTIVE,
        revision=0,
        transition_ids=(),
    )


def authorize_action(
    *,
    proposal: ActionProposal,
    commitment: AgentCommitment,
    lifecycle: CommitmentLifecycleSnapshot,
    resource_grants: tuple[ResourceEvent, ...],
    consumed_resources: tuple[ResourceAmount, ...] = (),
    at: str,
    run_finalized: bool,
) -> ActionAuthorization:
    if run_finalized:
        raise CommitmentGovernanceError(
            "cannot authorize an action after run is finalized"
        )
    if lifecycle.commitment_id != commitment.commitment_id:
        raise CommitmentGovernanceError(
            "lifecycle commitment_id does not match commitment"
        )
    if lifecycle.status is not CommitmentStatus.ACTIVE:
        raise CommitmentGovernanceError("commitment is not active")
    if proposal.commitment_id != commitment.commitment_id:
        raise CommitmentGovernanceError(
            "action proposal commitment_id does not match"
        )
    if proposal.agent_id != commitment.agent_id:
        raise CommitmentGovernanceError(
            "action proposal agent_id does not match commitment"
        )
    if proposal.task_id != commitment.task_id:
        raise CommitmentGovernanceError(
            "action proposal task_id does not match commitment"
        )
    if (
        proposal.requirement_schema_version
        != commitment.requirement_schema_version
    ):
        raise CommitmentGovernanceError(
            "action proposal requirement schema version does not match"
        )
    if not set(proposal.requirement_ids).issubset(commitment.accepted_scope):
        raise CommitmentGovernanceError(
            "action requirements exceed commitment scope"
        )
    if proposal.tool not in commitment.allowed_tools:
        raise CommitmentGovernanceError(
            "action tool is not allowed by commitment"
        )

    admitted = _resource_map(commitment.admitted_resources)
    consumed = _resource_map(tuple(consumed_resources))
    if len(consumed) != len(tuple(consumed_resources)):
        raise CommitmentGovernanceError(
            "consumed resources contain duplicate resource types"
        )
    for resource_type, amount in consumed.items():
        if resource_type not in admitted or amount > admitted[resource_type]:
            raise CommitmentGovernanceError(
                "cumulative resource use exceeds commitment"
            )
    for item in proposal.requested_resources:
        if (
            item.resource_type not in admitted
            or item.amount > admitted[item.resource_type]
        ):
            raise CommitmentGovernanceError(
                "action requested resource exceeds commitment"
            )
        if consumed.get(item.resource_type, 0) + item.amount > admitted[
            item.resource_type
        ]:
            raise CommitmentGovernanceError(
                "cumulative resource use exceeds commitment"
            )

    grants = tuple(resource_grants)
    if not grants:
        raise CommitmentGovernanceError("action has no supporting grant")
    if tuple(item.event_id for item in grants) != (
        commitment.admitted_resource_grant_ids
    ):
        raise CommitmentGovernanceError(
            "action grant IDs do not match commitment"
        )
    expected_target = agent_escrow_account(commitment.agent_id)
    granted_by_type: dict[str, float] = {}
    for grant in grants:
        if grant.operation is not ResourceOperation.GRANT:
            raise CommitmentGovernanceError(
                "action references a non-grant resource event"
            )
        if (
            grant.source_account != SHARED_POOL
            or grant.target_account != expected_target
        ):
            raise CommitmentGovernanceError(
                "action grant authority or audience does not match"
            )
        if grant.resource_type in granted_by_type:
            raise CommitmentGovernanceError(
                "action grants contain duplicate resource types"
            )
        granted_by_type[grant.resource_type] = grant.amount
    if granted_by_type != admitted:
        raise CommitmentGovernanceError(
            "action grants do not match committed resources"
        )

    checked_at = _parse_timestamp(at, "at")
    proposal_created_at = _parse_timestamp(proposal.created_at, "created_at")
    if proposal_created_at < _parse_timestamp(
        commitment.created_at,
        "commitment created_at",
    ):
        raise CommitmentGovernanceError(
            "action proposal predates its commitment"
        )
    if checked_at < proposal_created_at:
        raise CommitmentGovernanceError(
            "action cannot be authorized before proposal creation"
        )
    proposal_expiry = _parse_timestamp(proposal.expires_at, "expires_at")
    commitment_deadline = _parse_timestamp(commitment.deadline, "deadline")
    if checked_at >= proposal_expiry:
        raise CommitmentGovernanceError("action proposal has expired")
    if checked_at >= commitment_deadline:
        raise CommitmentGovernanceError("commitment has expired")

    digest = _stable_digest(
        {
            "at": at,
            "commitment": commitment.to_dict(),
            "consumed_resources": [
                item.to_dict()
                for item in sorted(
                    consumed_resources,
                    key=lambda value: value.resource_type,
                )
            ],
            "lifecycle": lifecycle.to_dict(),
            "proposal": proposal.to_dict(),
            "resource_grants": [item.to_dict() for item in grants],
            "run_finalized": run_finalized,
        }
    )
    expires_at = (
        proposal.expires_at
        if proposal_expiry <= commitment_deadline
        else commitment.deadline
    )
    grant_ids = tuple(item.event_id for item in grants)
    return ActionAuthorization(
        schema_version=1,
        authorization_id=f"action-authorization-{digest}",
        action_proposal_id=proposal.action_proposal_id,
        commitment_id=commitment.commitment_id,
        agent_id=proposal.agent_id,
        task_id=proposal.task_id,
        requirement_schema_version=proposal.requirement_schema_version,
        authorized_requirement_ids=proposal.requirement_ids,
        authorized_tool=proposal.tool,
        authorized_resources=proposal.requested_resources,
        resource_grant_ids=grant_ids,
        causal_parent_ids=(
            commitment.commitment_id,
            proposal.action_proposal_id,
            *grant_ids,
        ),
        created_at=at,
        expires_at=expires_at,
        issuer=GovernanceIssuer.HARNESS_ADMISSION,
    )


def transition_commitment(
    commitment: AgentCommitment,
    lifecycle: CommitmentLifecycleSnapshot,
    *,
    next_status: CommitmentStatus,
    reason: str,
    at: str,
    run_finalized: bool,
) -> tuple[CommitmentTransition, CommitmentLifecycleSnapshot]:
    if run_finalized:
        raise CommitmentGovernanceError(
            "cannot transition a commitment after run is finalized"
        )
    if lifecycle.commitment_id != commitment.commitment_id:
        raise CommitmentGovernanceError(
            "lifecycle commitment_id does not match commitment"
        )
    if lifecycle.status is not CommitmentStatus.ACTIVE:
        raise CommitmentGovernanceError(
            "terminal commitment cannot transition again"
        )
    if next_status not in {
        CommitmentStatus.COMPLETED,
        CommitmentStatus.CANCELLED,
        CommitmentStatus.EXPIRED,
    }:
        raise CommitmentGovernanceError(
            "next commitment status must be terminal"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise CommitmentGovernanceError("transition reason must be non-empty")
    if _parse_timestamp(at, "at") < _parse_timestamp(
        commitment.created_at,
        "commitment created_at",
    ):
        raise CommitmentGovernanceError(
            "transition cannot predate commitment"
        )

    digest = _stable_digest(
        {
            "at": at,
            "commitment_id": commitment.commitment_id,
            "lifecycle": lifecycle.to_dict(),
            "next_status": next_status.value,
            "reason": reason,
            "run_finalized": run_finalized,
        }
    )
    transition = CommitmentTransition(
        schema_version=1,
        transition_id=f"commitment-transition-{digest}",
        commitment_id=commitment.commitment_id,
        previous_status=lifecycle.status,
        next_status=next_status,
        previous_revision=lifecycle.revision,
        next_revision=lifecycle.revision + 1,
        reason=reason,
        occurred_at=at,
        causal_parent_ids=(commitment.commitment_id,),
        issuer=GovernanceIssuer.HARNESS_ADMISSION,
    )
    terminal = _apply_transition(lifecycle, transition)
    return transition, terminal


def _apply_transition(
    lifecycle: CommitmentLifecycleSnapshot,
    transition: CommitmentTransition,
) -> CommitmentLifecycleSnapshot:
    if transition.commitment_id != lifecycle.commitment_id:
        raise CommitmentGovernanceError(
            "transition commitment_id does not match lifecycle"
        )
    if lifecycle.status is not CommitmentStatus.ACTIVE:
        raise CommitmentGovernanceError(
            "terminal commitment cannot transition again"
        )
    if transition.previous_status is not lifecycle.status:
        raise CommitmentGovernanceError(
            "transition previous status does not match lifecycle"
        )
    if transition.previous_revision != lifecycle.revision:
        raise CommitmentGovernanceError(
            "transition revision is not contiguous"
        )
    return CommitmentLifecycleSnapshot(
        schema_version=1,
        commitment_id=lifecycle.commitment_id,
        status=transition.next_status,
        revision=transition.next_revision,
        transition_ids=(
            *lifecycle.transition_ids,
            transition.transition_id,
        ),
    )


def replay_commitment_transitions(
    commitment: AgentCommitment,
    transitions: tuple[CommitmentTransition, ...],
) -> CommitmentLifecycleSnapshot:
    lifecycle = initial_commitment_lifecycle(commitment)
    for transition in transitions:
        lifecycle = _apply_transition(lifecycle, transition)
    return lifecycle
