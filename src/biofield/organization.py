from __future__ import annotations

import hashlib
import json

from .contracts import (
    ActiveAgentState,
    AgentCostContribution,
    CentralPresetInfo,
    CommunicationEdgeRecord,
    DistributionCount,
    ExperienceStructuralChange,
    OrganizationSnapshot,
    RequirementCommitmentLink,
)


def build_organization_snapshot(
    *,
    run_id: str,
    task_id: str,
    checkpoint_id: str,
    requirement_schema_version: int,
    public_state_revision: int,
    active_agents: tuple[ActiveAgentState, ...],
    requirement_commitments: tuple[RequirementCommitmentLink, ...],
    communication_edges: tuple[CommunicationEdgeRecord, ...],
    duplicate_distribution: tuple[DistributionCount, ...],
    refusal_distribution: tuple[DistributionCount, ...],
    agent_cost_contributions: tuple[AgentCostContribution, ...],
    central_preset_info: CentralPresetInfo,
    experience_structural_changes: tuple[ExperienceStructuralChange, ...],
    parent_event_ids: tuple[str, ...],
    builder_version: str,
    created_at: str,
) -> OrganizationSnapshot:
    """Build a canonical checkpoint observation without affecting organization."""

    canonical = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": task_id,
        "checkpoint_id": checkpoint_id,
        "requirement_schema_version": requirement_schema_version,
        "public_state_revision": public_state_revision,
        "active_agents": tuple(
            sorted(active_agents, key=lambda item: item.agent_id)
        ),
        "requirement_commitments": tuple(
            sorted(
                requirement_commitments,
                key=lambda item: (item.requirement_id, item.commitment_id),
            )
        ),
        "communication_edges": tuple(
            sorted(communication_edges, key=lambda item: item.edge_id)
        ),
        "duplicate_distribution": tuple(
            sorted(duplicate_distribution, key=lambda item: item.category)
        ),
        "refusal_distribution": tuple(
            sorted(refusal_distribution, key=lambda item: item.category)
        ),
        "agent_cost_contributions": tuple(
            sorted(
                agent_cost_contributions,
                key=lambda item: item.agent_id,
            )
        ),
        "central_preset_info": central_preset_info,
        "experience_structural_changes": tuple(
            sorted(
                experience_structural_changes,
                key=lambda item: item.change_id,
            )
        ),
        "parent_event_ids": tuple(sorted(parent_event_ids)),
        "builder_version": builder_version,
        "created_at": created_at,
    }
    payload = {
        key: (
            [item.to_dict() for item in value]
            if isinstance(value, tuple) and value and hasattr(value[0], "to_dict")
            else (
                value.to_dict()
                if hasattr(value, "to_dict")
                else list(value)
                if isinstance(value, tuple)
                else value
            )
        )
        for key, value in canonical.items()
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    snapshot_hash = hashlib.sha256(encoded).hexdigest()
    return OrganizationSnapshot(
        snapshot_id=f"organization-snapshot-{snapshot_hash}",
        snapshot_hash=snapshot_hash,
        **canonical,
    )
